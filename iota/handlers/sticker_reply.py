"""
Iota Smart Sticker / GIF / Photo Reply System

HOW IT WORKS:
- Sticker received  → detect mood from sticker's emoji → reply with a
  REAL Telegram sticker of the same mood (sticker-to-sticker), taken from
  the owner-managed packs (see handlers/owner_panel.py). Iota NEVER sends a
  GIF or any text in reply to a sticker. If no sticker is configured for
  that mood, she stays silent.
- GIF received      → detect mood from caption/filename → reply with a
  matching GIF (sticker→sticker / gif→gif only, NO text captions).
- Photo received    → short AI-generated 1-line reaction
- Emoji-only DMs    → detect mood → GIF reply (no text)

TRIGGER RULES (group):
- Only triggers when bot is @tagged OR message is reply to bot's message
- In DMs: always active
- Does NOT trigger on every sticker in every group (that would be spam)

RELIABILITY:
GIFs now come from a live GIPHY search (utils/gif_provider.py) instead
of a small fixed list of links that can rot/die (Tenor, which this used
before, was shut down by Google on 2026-06-30). Every send is wrapped
so a failure at any single step (GIF fetch, sticker send, animation
send) can never crash the handler — there is always a final plain-text
fallback.
"""
import asyncio, random, logging, re
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from utils.mongo_db import (ensure_user, get_user, update_last_seen,
                            get_stickers_for_mood, add_sticker_to_pack,
                            list_all_sticker_packs)
from utils.ai_provider import call_ai
from utils.gif_provider import get_gif_for_mood
from config import BOT_USERNAME

logger = logging.getLogger(__name__)

# 🔴 Sticker packs are now owner-managed via Telegram commands
# (/addsticker, /stickerpacks, /previewsticker, /clearstickers — see
# handlers/owner_panel.py) and stored in MongoDB, instead of requiring a
# code edit + redeploy every time the owner wants to add a sticker. The
# old hardcoded _STICKER_IDS dict is gone — get_stickers_for_mood(mood)
# below reads live from the database.

# ── Emoji → mood mapping ──────────────────────────────────────────────────────
_EMOJI_MOOD: dict = {
    # Laugh
    "😂": "laugh", "🤣": "laugh", "😹": "laugh", "💀": "laugh",
    # Love
    "😍": "love", "🥰": "love", "💕": "love", "💞": "love",
    "❤️": "love", "🫶": "love", "💝": "love", "💘": "love",
    # Sad
    "😭": "sad", "😢": "sad", "💔": "sad", "😔": "sad", "😞": "sad",
    # Angry
    "😡": "angry", "🤬": "angry", "😤": "angry", "💢": "angry",
    # Happy
    "🥳": "happy", "😊": "happy", "😁": "happy", "🎉": "happy",
    "😄": "happy", "🤩": "happy", "🎊": "happy",
    # Surprise
    "😮": "surprise", "😱": "surprise", "😲": "surprise", "👀": "surprise",
    # Dance
    "💃": "dance", "🕺": "dance", "🎵": "dance", "🎶": "dance",
    # Cool
    "😎": "cool", "🤙": "cool", "✌️": "cool",
    # Cute
    "🥺": "cute", "🌸": "cute", "✨": "cute", "🌷": "cute",
    "🍑": "cute", "🌼": "cute",
}


def _detect_mood_from_sticker(sticker) -> str:
    """Detect mood from sticker's emoji field."""
    if not sticker:
        return "default"
    emoji_str = getattr(sticker, "emoji", "") or ""
    for ch in emoji_str:
        m = _EMOJI_MOOD.get(ch)
        if m:
            return m
    return "default"


def _detect_mood_from_text(text: str) -> str:
    """Detect mood from text/caption by scanning emoji characters."""
    for ch in text:
        m = _EMOJI_MOOD.get(ch)
        if m:
            return m
    # Keyword fallback
    tl = text.lower()
    if any(w in tl for w in ["dance", "vibe", "music", "song"]): return "dance"
    if any(w in tl for w in ["love", "kiss", "heart", "pyaar"]): return "love"
    if any(w in tl for w in ["funny", "lol", "haha", "laugh"]): return "laugh"
    if any(w in tl for w in ["angry", "mad", "rage", "gussa"]): return "angry"
    if any(w in tl for w in ["cute", "kawaii", "aww", "soft"]): return "cute"
    return "default"


# ── Related moods (for "no exact match → reply with a similar one") ────────
# When the detected mood has no saved stickers, we try these related moods
# before giving up and auto-saving the sender's whole pack.
_MOOD_RELATED: dict = {
    "happy":   ["laugh", "dance", "cute", "cool"],
    "laugh":   ["happy", "cute", "dance"],
    "love":    ["cute", "sad", "happy"],
    "cute":    ["love", "happy", "laugh"],
    "sad":     ["love", "cute"],
    "angry":   ["cool", "surprise"],
    "surprise":["cool", "angry"],
    "dance":   ["happy", "cool", "laugh"],
    "cool":    ["happy", "dance", "surprise"],
    "default": [],
}

# In-memory cache of packs Iota has already auto-saved, so a repeat sticker
# from the same pack doesn't trigger another Telegram API fetch. Maps
# set_name → mood (the auto-decided one it was saved under).
_AUTO_SAVED_PACKS: dict = {}


def _sanitize_mood(text: str) -> str:
    """Turn an arbitrary pack title into a safe mood slug: lowercase,
    spaces→underscores, only [a-z0-9_] kept, collapsed underscores."""
    slug = (text or "").strip().lower().replace(" ", "_")
    slug = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    return slug or "default"


def _auto_mood_from_pack(sticker_set) -> str:
    """Pick a mood for a WHOLE imported pack by tallying the emojis of every
    sticker in it. The most common mapped mood wins so the pack lands in the
    mood the sticker-reply system already understands. Falls back to the
    pack's sanitized title when no sticker uses a known mood-emoji."""
    tally = {}
    for s in getattr(sticker_set, "stickers", []):
        for ch in (getattr(s, "emoji", "") or ""):
            m = _EMOJI_MOOD.get(ch)
            if m:
                tally[m] = tally.get(m, 0) + 1
    if tally:
        return max(tally, key=tally.get)
    return _sanitize_mood(getattr(sticker_set, "title", ""))


def _pick_other(file_ids: list, current_fid: str) -> str:
    """Pick a random file_id that isn't the incoming one (so Iota doesn't
    just echo back the exact sticker the user sent). Falls back to the first
    if the pack only contains that one sticker."""
    if not file_ids:
        return current_fid
    for fid in random.sample(file_ids, len(file_ids)):
        if fid != current_fid:
            return fid
    return file_ids[0]


async def _save_pack_background(sticker_set, mood: str, set_name: str) -> None:
    """Persist every sticker of a pack under its auto-decided mood. Runs as
    a fire-and-forget background task — add_sticker_to_pack de-dupes via
    $addToSet, so re-saving the same pack is always safe. added_by=0 marks
    it as auto-saved by Iota (not the owner)."""
    try:
        for s in sticker_set.stickers:
            try:
                await add_sticker_to_pack(mood, s.file_id, 0)
            except Exception as e:
                logger.debug(f"auto-save: failed to add one sticker: {e}")
        _AUTO_SAVED_PACKS[set_name] = mood
    except Exception as e:
        logger.debug(f"auto-save pack '{set_name}' failed: {e}")


async def _reply_sticker_for_mood(msg, mood: str) -> bool:
    """
    Reply with a sticker for the EXACT mood, or — if that mood has no saved
    stickers — a SIMILAR/related mood's sticker. Returns True if one was
    sent, False otherwise.
    """
    packs = await list_all_sticker_packs()
    candidates = [mood] + _MOOD_RELATED.get(mood, [])
    for m in candidates:
        if packs.get(m):
            try:
                sids = await get_stickers_for_mood(m)
            except Exception as e:
                logger.debug(f"get_stickers_for_mood failed for '{m}': {e}")
                sids = []
            if sids:
                try:
                    await msg.reply_sticker(random.choice(sids))
                    return True
                except Exception as e:
                    logger.debug(f"Sticker send failed: {e}")
                    return False
    return False


async def _reply_any_sticker(msg) -> bool:
    """Last-resort: reply with ANY configured sticker (any mood) so the user
    always gets a sticker reply when at least one pack exists."""
    packs = await list_all_sticker_packs()
    for m in packs:
        try:
            sids = await get_stickers_for_mood(m)
        except Exception as e:
            logger.debug(f"get_stickers_for_mood failed for '{m}': {e}")
            sids = []
        if sids:
            try:
                await msg.reply_sticker(random.choice(sids))
                return True
            except Exception as e:
                logger.debug(f"Sticker send failed: {e}")
                return False
    return False


async def _auto_reply_from_pack(msg, context) -> bool:
    """
    Final sticker fallback: the sender's sticker has no matching (or similar)
    saved sticker, so Iota AUTO-SAVES the sender's ENTIRE pack in the
    background (no owner command needed) and replies with a sticker from it.

    Flow:
      • If we've already auto-saved this exact pack (cached), reply with a
        sticker from that saved mood straight from the DB.
      • Otherwise fetch the pack via get_sticker_set, kick off a background
        save of every sticker, and immediately reply with a sticker from the
        pack (preferring a DIFFERENT one than the user just sent).
      • A single-sticker pack (only the incoming sticker) is still saved, but
        we don't echo the identical sticker back — we fall through to the
        any-sticker fallback instead.
    """
    sticker = msg.sticker
    set_name = getattr(sticker, "set_name", None)
    if not set_name:
        return False

    # Already auto-saved before → reuse from DB.
    cached_mood = _AUTO_SAVED_PACKS.get(set_name)
    if cached_mood:
        try:
            sids = await get_stickers_for_mood(cached_mood)
        except Exception as e:
            logger.debug(f"auto-reply cached get failed: {e}")
            sids = []
        if sids:
            try:
                await msg.reply_sticker(_pick_other(sids, sticker.file_id))
                return True
            except Exception as e:
                logger.debug(f"auto-reply cached send failed: {e}")

    try:
        sticker_set = await context.bot.get_sticker_set(set_name)
    except TelegramError as e:
        logger.warning(f"auto-reply: couldn't fetch pack '{set_name}': {e}")
        return False
    except Exception as e:
        logger.warning(f"auto-reply: unexpected fetch error for '{set_name}': {e}")
        return False

    mood = _auto_mood_from_pack(sticker_set)
    file_ids = [s.file_id for s in getattr(sticker_set, "stickers", [])]

    # Save the whole pack in the background (non-blocking).
    asyncio.create_task(_save_pack_background(sticker_set, mood, set_name))

    # Single-sticker pack → don't echo the identical sticker; let the
    # any-sticker fallback handle the reply (pack is still saved above).
    if len(file_ids) <= 1:
        return False

    reply_fid = _pick_other(file_ids, sticker.file_id)
    try:
        await msg.reply_sticker(reply_fid)
        return True
    except Exception as e:
        logger.debug(f"auto-reply: sticker send failed: {e}")
        return False


async def _reply_with_gif(msg, mood: str) -> bool:
    """
    GIF-to-GIF: reply with a mood-matched animation only (no caption, no
    text). The GIF is sourced from an effectively unlimited live search
    (GIPHY). A GIF reply is ALWAYS a GIF — if the search fails we stay
    silent rather than sending a stray text message. Can never raise.
    """
    try:
        gif_url = await get_gif_for_mood(mood)
    except Exception as e:
        logger.debug(f"get_gif_for_mood failed for '{mood}': {e}")
        return False

    if not gif_url:
        return False

    try:
        await msg.reply_animation(gif_url)
        return True
    except Exception as e:
        logger.debug(f"GIF send failed ({gif_url}): {e}")
        # One retry with a freshly re-fetched GIF in case the first link
        # was a transient dead result from the search.
        try:
            gif_url2 = await get_gif_for_mood(mood)
            if gif_url2 and gif_url2 != gif_url:
                await msg.reply_animation(gif_url2)
                return True
        except Exception as e2:
            logger.debug(f"GIF retry send failed: {e2}")
    return False


def _is_reply_to_bot(update: Update, bot_id: int) -> bool:
    msg = update.effective_message
    if not msg or not msg.reply_to_message:
        return False
    ru = msg.reply_to_message.from_user
    return bool(ru and ru.id == bot_id)


def _is_tagged(text: str, bot_username: str) -> bool:
    if not text or not bot_username:
        return False
    return f"@{bot_username}".lower() in text.lower()


async def _should_respond(update: Update, context) -> bool:
    """
    Determine if Iota should respond to this media message.
    - DMs: always yes
    - Groups: only if bot is @tagged in caption OR message is reply to bot
    """
    chat = update.effective_chat
    if chat.type == "private":
        return True
    try:
        me = await context.bot.get_me()
        bot_id = me.id
        bot_uname = me.username or BOT_USERNAME
    except Exception as e:
        logger.debug(f"get_me failed in sticker handler: {e}")
        return False

    msg = update.effective_message
    caption = (msg.caption or "") + (msg.text or "")
    return _is_reply_to_bot(update, bot_id) or _is_tagged(caption, bot_uname)


# ── Sticker handler ───────────────────────────────────────────────────────────

async def sticker_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Sticker received → reply with a sticker ONLY (never a GIF or text).

    Reply priority for the incoming sticker:
      1. A saved sticker for the EXACT detected mood.
      2. If that mood has none, a sticker from a SIMILAR/related mood.
      3. If even similar has none, Iota AUTO-SAVES the sender's ENTIRE pack
         in the background (no owner command needed) and replies with a
         sticker from it.
      4. As a last resort, any configured sticker at all.
    If nothing is configured anywhere, she stays silent.
    """
    msg = update.effective_message
    u   = update.effective_user
    if not msg or not u or u.is_bot:
        return

    if not await _should_respond(update, context):
        return

    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)

    mood = _detect_mood_from_sticker(msg.sticker)

    # 1 + 2: exact mood, else a similar/related mood.
    if await _reply_sticker_for_mood(msg, mood):
        return

    # 3: no similar sticker → auto-save the sender's whole pack & reply.
    if await _auto_reply_from_pack(msg, context):
        return

    # 4: last resort — any configured sticker.
    if await _reply_any_sticker(msg):
        return

    # Nothing saved anywhere → stay silent.


# ── GIF/animation handler ─────────────────────────────────────────────────────

async def gif_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    GIF received → reply with a mood-matched GIF ONLY (no text caption).
    GIF to GIF: always responds with another animation.
    """
    msg = update.effective_message
    u   = update.effective_user
    if not msg or not u or u.is_bot:
        return

    if not await _should_respond(update, context):
        return

    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)

    caption  = (msg.caption or "").strip()
    anim     = msg.animation
    hint     = caption or (getattr(anim, "file_name", "") or "")
    mood     = _detect_mood_from_text(hint)

    await _reply_with_gif(msg, mood)


# ── Photo handler ─────────────────────────────────────────────────────────────

async def photo_reaction_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Photo received → short AI-generated reaction (1 line).
    Works in DMs always; in groups only when bot is tagged/replied-to.
    """
    msg = update.effective_message
    u   = update.effective_user
    if not msg or not u or u.is_bot:
        return

    if not await _should_respond(update, context):
        return

    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)

    caption = (msg.caption or "").strip()
    prompt_ctx = f" Caption: '{caption}'" if caption else ""

    try:
        d = await get_user(u.id)
        messages = [
            {"role": "system", "content": (
                "You are Iota, a sassy cute Telegram girl. Someone sent you a photo"
                + prompt_ctx + ". React in ONE short line, Hinglish, with an emoji. "
                "Be funny, cute, or playful. Never ask for more info. "
                "No markdown. Output ONLY the reaction."
            )},
            {"role": "user", "content": "React to my photo!"}
        ]
        reply = await call_ai(messages, is_premium=d.get("is_premium", False),
                              max_tokens=60, temperature=1.0)
        if reply:
            await msg.reply_html(reply.strip())
            return
    except Exception as e:
        logger.debug(f"AI photo reaction failed: {e}")

    # Fallback reactions
    fallbacks = [
        "nice pic 😊", "waah 👀", "cute hain ye 💕",
        "oof 😅", "okay okay 👋", "🤩 wow",
    ]
    await msg.reply_html(random.choice(fallbacks))


# ── Emoji-only DM handler ─────────────────────────────────────────────────────

async def emoji_only_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Pure emoji message in DMs → reply with a mood-matched GIF ONLY
    (no text). Emoji-only = all characters are emoji/whitespace.
    """
    msg  = update.effective_message
    u    = update.effective_user
    chat = update.effective_chat
    if not msg or not u or u.is_bot:
        return
    if chat.type != "private":
        return

    text = (msg.text or "").strip()
    if not text:
        return

    # Check if emoji-only: remove whitespace and all emoji unicode blocks,
    # if nothing remains AND at least one emoji was found → it's emoji-only
    without_emoji = re.sub(
        r'[\s'
        r'\U0001F300-\U0001FAFF'   # Misc symbols + pictographs
        r'\U0001F600-\U0001F64F'   # Emoticons
        r'\U0001F680-\U0001F6FF'   # Transport & map
        r'\U0001F1E0-\U0001F1FF'   # Flags
        r'\u2600-\u26FF'            # Misc symbols
        r'\u2700-\u27BF'            # Dingbats
        r'\uFE00-\uFE0F'            # Variation selectors
        r'\u200d'                   # ZWJ
        r'\u20E3'                   # Combining enclosing keycap
        r']+', '', text
    )
    has_emoji = len(text.strip()) > len(without_emoji)

    if without_emoji or not has_emoji:
        return  # Has non-emoji text → let normal DM handler deal with it

    mood = _detect_mood_from_text(text)
    await _reply_with_gif(msg, mood)
