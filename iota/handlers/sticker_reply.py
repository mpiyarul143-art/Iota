"""
Iota Smart Sticker / GIF / Photo Reply System

HOW IT WORKS:
- Sticker received  → detect mood from sticker's emoji field → reply with
  a matching GIF (from an effectively unlimited live search, see
  utils/gif_provider.py) + short text reaction. If the incoming message
  IS a sticker, Iota also replies with a real Telegram sticker of her own
  when one is configured for that mood (sticker-to-sticker).
- GIF received      → detect topic from caption/filename → reply with
  matching GIF + short text
- Photo received    → short AI-generated 1-line reaction
- Emoji-only DMs    → detect mood → GIF reply

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
import random, logging, re
from telegram import Update
from telegram.ext import ContextTypes
from utils.mongo_db import ensure_user, get_user, update_last_seen, get_stickers_for_mood
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

# ── Mood text reactions ───────────────────────────────────────────────────────
_MOOD_TEXTS: dict = {
    "happy":   ["haha cutie 😂", "ahahaha 😹", "lol ye kyaa tha 🤣", "LMAO 💀"],
    "sad":     ["aw 🥺", "kyu ro raha/rahi ho 💔", "chal theek ho jayega 😌", "oops 😅"],
    "love":    ["aww 🥺💕", "cutie 💗", "itna pyaar 😍", "hehe 💕", "awwww 😭💕"],
    "laugh":   ["hahaha 😂", "lmao 💀", "bhai/bhen 😹", "ahahaha 🤣", "ye kya tha 😂"],
    "angry":   ["oye shant 🤚", "chill karo 😌", "🫡 noted", "theek hai baba 😒", "okay okay 😌"],
    "surprise":["ooh 😮", "kya?? 😱", "sach mein?? 😲", "WAIT WHAT 👀", "no way 😲"],
    "dance":   ["yayyy 💃✨", "lets gooo 🕺", "vibe hai yaar 💅", "slay 💅"],
    "cool":    ["😎 slay", "king/queen 👑", "bestie behaviour 💅", "okay bestie 😎"],
    "cute":    ["awwww 🥺", "so cute 💕", "stop it 😭💗", "yaar 🥺"],
    "default": ["hehe 😄", "okay cutie 👋", "oof 😅", "hm 🤔", "😊"],
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


async def _reply_with_gif(msg, mood: str, caption_text: str = ""):
    """
    Send a GIF matching the mood, sourced from an effectively unlimited
    live search (GIPHY) instead of a small fixed list. If the owner has
    added real stickers for this mood (via /addsticker), send one of
    those instead — true sticker-to-sticker replies. Always sends
    something — every failure path has a further fallback, so this
    function can never raise and never leaves the user without a reply.
    """
    # Try a real, owner-added sticker first (if any exist for this mood).
    try:
        sids = await get_stickers_for_mood(mood)
    except Exception as e:
        logger.debug(f"get_stickers_for_mood failed for '{mood}': {e}")
        sids = []
    if sids:
        try:
            await msg.reply_sticker(random.choice(sids))
            if caption_text:
                await msg.reply_html(caption_text)
            return True
        except Exception as e:
            logger.debug(f"Sticker send failed: {e}")

    # Live GIF search (unlimited variety, always fresh).
    try:
        gif_url = await get_gif_for_mood(mood)
    except Exception as e:
        logger.debug(f"get_gif_for_mood failed for '{mood}': {e}")
        gif_url = None

    if gif_url:
        try:
            await msg.reply_animation(
                gif_url,
                caption=caption_text or "",
                parse_mode="HTML"
            )
            return True
        except Exception as e:
            logger.debug(f"GIF send failed ({gif_url}): {e}")
            # One retry with a freshly re-fetched GIF in case the first
            # link was a transient dead result from the search.
            try:
                gif_url2 = await get_gif_for_mood(mood)
                if gif_url2 and gif_url2 != gif_url:
                    await msg.reply_animation(
                        gif_url2, caption=caption_text or "", parse_mode="HTML"
                    )
                    return True
            except Exception as e2:
                logger.debug(f"GIF retry send failed: {e2}")

    # Last resort: just text — guarantees the user always gets a reply.
    if caption_text:
        try:
            await msg.reply_html(caption_text)
        except Exception:
            pass
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
    Sticker received → reply with a mood-matched GIF + short text.
    Sticker to sticker: if sticker file_ids are configured in _STICKER_IDS,
    Iota will reply with a Telegram sticker. Otherwise GIF.
    """
    msg = update.effective_message
    u   = update.effective_user
    if not msg or not u or u.is_bot:
        return

    if not await _should_respond(update, context):
        return

    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)

    mood     = _detect_mood_from_sticker(msg.sticker)
    reaction = random.choice(_MOOD_TEXTS.get(mood, _MOOD_TEXTS["default"]))

    await _reply_with_gif(msg, mood, reaction)


# ── GIF/animation handler ─────────────────────────────────────────────────────

async def gif_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    GIF received → reply with a mood-matched GIF + short text.
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
    reaction = random.choice(_MOOD_TEXTS.get(mood, _MOOD_TEXTS["default"]))

    await _reply_with_gif(msg, mood, reaction)


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
    Pure emoji message in DMs → reply with mood-matched GIF.
    Emoji-only = all characters are emoji/whitespace (no ASCII letters).
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
    reaction = random.choice(_MOOD_TEXTS.get(mood, _MOOD_TEXTS["default"]))
    await _reply_with_gif(msg, mood, reaction)
