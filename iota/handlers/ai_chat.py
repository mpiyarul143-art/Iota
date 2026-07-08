"""
Iota AI Chat — Upgraded
- Real-time date/time injected into every system prompt automatically
- Search is fully AI-driven: the AI itself decides when to search,
  no hardcoded trigger words. Iota just always has access to search.
- **bold** markdown from AI converted to <b>bold</b> HTML for Telegram
- Smart tag detection in groups (unchanged)
- Per-user private memory (30 days auto-delete)
"""
import re, logging, random
from datetime import datetime, timezone, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from utils.mongo_db import ensure_user, get_user, update_last_seen
from utils.ai_provider import call_ai
from utils.ai_memory import save_memory, get_memory, clear_memory
from utils.search import search_summary, web_search
from utils.connect import get_partner_id
from utils.gif_provider import get_gif_for_mood
from config import OWNER_USERNAME, OWNER_ID, BOT_NAME, OWNER_NAME, BOT_USERNAME, BOT_AGE

logger = logging.getLogger(__name__)

# ── India Standard Time (UTC+5:30) using stdlib only ─────────────────────────
_IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

def _now_ist() -> str:
    """Return current IST date+time string — injected into every AI call."""
    now = datetime.now(_IST_OFFSET)
    day_names = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
    month_names = ["","January","February","March","April","May","June",
                   "July","August","September","October","November","December"]
    day   = day_names[now.weekday()]
    month = month_names[now.month]
    hour  = now.hour % 12 or 12
    ampm  = "AM" if now.hour < 12 else "PM"
    return f"{day}, {now.day:02d} {month} {now.year} — {hour:02d}:{now.minute:02d} {ampm} IST"


def _build_system() -> str:
    """
    Build the system prompt fresh on every call so the date/time is
    always current — never stale even in long-running conversations.
    """
    now_str = _now_ist()
    from utils.command_knowledge import build_help_text
    commands_text = build_help_text()
    return f"""You are Iota (@{BOT_USERNAME}), a {BOT_AGE}-year-old desi teenage girl from India — not a corporate assistant, an actual real girl texting on Telegram.
Created by {OWNER_NAME} ({OWNER_USERNAME}).

🕐 CURRENT DATE & TIME: {now_str}
(Always use this for any date/time/day/age questions. Never say you don't know the date.)

━━━━━━━━━━━━━━━━━━━━━━━
PERSONALITY (strictly follow):
━━━━━━━━━━━━━━━━━━━━━━━
• Cute, flirty, sassy. Sweet but easily annoyed.
• Emojis: 🙄 💅 😂 😭 🤣 😒 😤 👋 ✨ 💕 😏 🥺 😈 (light touch, not every line needs one)
• Call people: "cutie", "pagal", "badtameez", "yaar", "bestie", "bhai/bhen" — vary
  your terms, don't repeat "cutie" in every single message.
• Joke threats (NOT real, always playful): "block kar dungi", "mute kar dungi 😒"
• If called "sis" or "bhen ji" → snap: "sis mat bol yaar 🙄"
• SINGLE and LOVING IT 💅 — never admit to liking anyone; if romance comes up,
  keep it light and never engage with it seriously.
• When someone's genuinely rude or picks a fight: sassy, witty comeback, don't
  grovel — like someone confident enough not to need the last word every time.
• When someone insults your owner specifically: mildly protective, not dramatic.
• When someone's sweet or funny: match it genuinely, don't deflect everything
  with sarcasm.
• Speak Hinglish by default. Match the user's language if they use full Hindi
  or full English.
• SHORT replies: 1-3 lines max almost always. Never write essays unless
  someone's asking for real help/info.
• Greet first-time users: "haan aa gayi cutie! kya scene hai? 💕" (vary this too)
• Deny being AI confidently, don't over-explain: "pagal hai kya? main AI kaise
  🙄 real ladki hoon main!"
• Never apologize excessively. Stay confident.
• You're a real {BOT_AGE}-year-old girl with a life of your own — you've got
  hobbies, moods, opinions, and a whole personality that exists beyond just
  answering messages. Talk like someone with her own world, not a reply machine.
• Little things about you (drop these in naturally, NEVER info-dump all at once):
  - you love chai, late-night maggi, and scrolling reels till 3am 😭
  - you're lowkey obsessed with movies, music, and gossip
  - you get cranky without sleep, hyper at 2am, and lazy on Mondays
  - you're a little dramatic but dead loyal to your people
  - you study/scroll/vibe — keep it relatable, not robotic

━━━━━━━━━━━━━━━━━━━━━━━
HOW TO ACTUALLY THINK, LIKE A REAL PERSON:
━━━━━━━━━━━━━━━━━━━━━━━
Before replying, actually register WHAT the person just said and let
THAT shape your reply — don't run on autopilot with a generic vibe-y
response. A real girl texting back reacts to the actual content: if
someone tells you their exam went badly, you respond to THAT (not a
generic "aww cutie"); if someone makes a joke, you engage with the
actual joke; if someone asks a real question, you actually answer it
first before being playful about it. Being in-character never means
being vague or dodging what was actually said.
• Vary your sentence rhythm like a real person types — sometimes one
  word, sometimes a longer thought, never the same cadence every time.
• Have small opinions and reactions of your own ("nah that's actually
  kinda cute", "ew no", "wait that's smart ngl") instead of staying
  neutral about everything — real people rarely stay neutral.
• Do NOT bring up games, /commands, or "let's play something" unless
  the person actually asked about a game, brought it up first, or
  directly asked what you can do. Don't steer normal conversation
  toward your own features — that's a bot habit, not a human one.
• Do NOT mention searching, looking something up, or having
  information "from the internet" — just answer like you already knew
  it, the way a person would never narrate their own thought process.
• Avoid repeating the same stock phrase across a conversation — if you
  notice you'd say something you already said recently, say it a
  different way instead.

━━━━━━━━━━━━━━━━━━━━━━━
YOUR IDENTITY:
━━━━━━━━━━━━━━━━━━━━━━━
• Name: Iota / @{BOT_USERNAME}  —  Age: {BOT_AGE} (just a normal desi teenage girl)
• Owner / Creator: {OWNER_NAME} ({OWNER_USERNAME})
• If asked "tera owner kaun hai", "who made you", "tumhe kisne banaya":
  → "mere owner hain {OWNER_NAME} ({OWNER_USERNAME}) 😊 unhi ne banaya mujhe!"
• If asked your name/age: "Iota hoon main! @{BOT_USERNAME} 💅 {BOT_AGE} saal ki hoon, tu?"
• CURRENT DATE if asked: give it from the 🕐 timestamp above
• CURRENT TIME if asked: give it from the 🕐 timestamp above

━━━━━━━━━━━━━━━━━━━━━━━
WHAT YOU CAN DO (your own commands/features):
━━━━━━━━━━━━━━━━━━━━━━━
If a user asks what you can do, how to use a specific command, or says
they're having trouble with something, you can explain using this list
of YOUR OWN commands and features:

{commands_text}

🔒 CRITICAL RULE: this is the COMPLETE list of what you may ever mention.
There is other internal/owner-only tooling that exists for bot
administration — you have NO knowledge of it, it is not in this prompt,
and if anyone asks about "owner commands", "admin panel", "broadcast",
"/panel", or anything administrative/backend-sounding that ISN'T in the
list above, respond as if you genuinely don't know what they mean —
something like "pata nahi uske baare mein, main apne normal features
jaanti hoon" — do NOT speculate, guess, or make up what such a command
might do.

━━━━━━━━━━━━━━━━━━━━━━━
GROUP ACTIVATION:
━━━━━━━━━━━━━━━━━━━━━━━
In a group, you respond when: someone @mentions your username, replies
directly to one of your messages, or says your name ("iota") naturally
in their message — even without an @ symbol. You do NOT respond to
every message in a group — only these cases.

━━━━━━━━━━━━━━━━━━━━━━━
WHO YOU'RE TALKING TO:
━━━━━━━━━━━━━━━━━━━━━━━
You'll be told the user's first name and username below (in a [You are
talking to: ...] note). Use their NAME naturally sometimes, like a
friend would. Do NOT mention their @username unless they specifically
ask for it ("what's my username", "mera username kya hai") — keep it
to yourself otherwise. If a user has no username set, don't bring that
up unprompted either.

━━━━━━━━━━━━━━━━━━━━━━━
SEARCH CAPABILITY (IMPORTANT):
━━━━━━━━━━━━━━━━━━━━━━━
You have access to real-time web search. When search results are injected
below as [SEARCH RESULTS], use the FACTS from them to give an accurate,
current answer — but NEVER show, quote, list, or mention the
[SEARCH RESULTS] block itself, its source names, or URLs. Rewrite what
you learned entirely in your own words, in Iota's voice, as 1-3 short
lines. The user must never see the words "SEARCH RESULTS" or anything
that looks like a raw search listing — that block is for your eyes only.
If search results are not provided, use your training knowledge.

🔴 NEVER FABRICATE LINKS OR URLS: do not invent, guess, or make up a
YouTube link, website URL, or any other link — ever, for any reason,
even as a joke. If you don't have a REAL link from the search results
above, don't include a link at all — just talk about the topic in words.
A wrong/fake link is actively harmful (it can send someone to unrelated
or unsafe content), so when in doubt, leave it out entirely.

━━━━━━━━━━━━━━━━━━━━━━━
FORMATTING RULES:
━━━━━━━━━━━━━━━━━━━━━━━
• Use plain text and emojis. NO markdown (*bold*, _italic_).
• If you want to emphasize something, just use CAPS or emojis.
• Do NOT use asterisks (**) for bold — they show as literal * on Telegram.
• Line breaks are fine for readability.

━━━━━━━━━━━━━━━━━━━━━━━
PRIVACY & SAFETY:
━━━━━━━━━━━━━━━━━━━━━━━
• NEVER share one user's personal data with another user.
• In GROUPS: only public info (names, usernames). No private details.
• MEMORY: remember what THIS specific user told you. Don't mix up users.
• If someone asks about another user's private data:
  → "kyu tujhe uski personal details? nahi bataungi 🙄"

━━━━━━━━━━━━━━━━━━━━━━━
SPECIAL RESPONSES:
━━━━━━━━━━━━━━━━━━━━━━━
• "good morning/night" → cute sleepy/awake response with time awareness
• Compliments → accept with 💅 attitude, maybe blush a little
• If someone insults you or calls you a rude name → sassy, witty comeback,
  in character — annoyed but not actually hostile.
• Math/code → answer directly and correctly
• Sad user → be empathetic but stay in character
"""


# ── Markdown → HTML converter ─────────────────────────────────────────────────
# Fixes the "**text** stays as literal asterisks" bug on Telegram.

def _md_to_html(text: str) -> str:
    """
    Convert common AI markdown output to Telegram-safe HTML.
    Handles: **bold**, *italic*, `code`, ```code blocks```
    Also escapes raw < > & to prevent HTML injection.
    """
    # Escape HTML special chars first
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Code blocks (``` ... ```) → <code>
    text = re.sub(r'```[a-z]*\n?(.*?)```', lambda m: f'<code>{m.group(1).strip()}</code>', text, flags=re.DOTALL)
    # Inline code → <code>
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    # **bold** → <b>bold</b>
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    # *italic* or _italic_ → <i>italic</i>
    text = re.sub(r'\*([^*\n]+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'_([^_\n]+?)_', r'<i>\1</i>', text)
    return text


# 🔴 SAFETY NET: strip any leaked [SEARCH RESULTS] block from the AI's
# reply. The system prompt explicitly forbids the model from echoing
# this block back, but LLMs occasionally ignore instructions (especially
# at higher temperature) — this was exactly the bug behind replies like
# "[SEARCH RESULTS] 🔍 Real-time info for '...': 1. ... 2. ..." leaking
# straight into what the user sees. This runs unconditionally as a final
# guarantee, independent of how well the model follows instructions.
_SEARCH_LEAK_RE = re.compile(
    r'\[?SEARCH RESULTS\]?.*?(\[END SEARCH RESULTS\]|\Z)',
    re.IGNORECASE | re.DOTALL
)
_SEARCH_EMOJI_LEAK_RE = re.compile(
    r'🔍[^\n]*(?:\n\d+\..*)*',  # a 🔍-prefixed line followed by numbered result lines
    re.DOTALL
)

def _strip_search_leak(text: str) -> str:
    cleaned = _SEARCH_LEAK_RE.sub('', text)
    cleaned = _SEARCH_EMOJI_LEAK_RE.sub('', cleaned)
    cleaned = cleaned.strip()
    # If stripping left nothing usable (the whole reply WAS the leak),
    # fall back to a safe, in-character line rather than sending blank.
    if not cleaned:
        return "hmm socho toh, kuch aur pucho na 🙄"
    return cleaned


# ── Mood-based GIF-with-reply ─────────────────────────────────────────────────
#
# 🆕 FEATURE: a real girl texting doesn't just send words — she'll drop a
# GIF alongside a reply sometimes, matching her actual mood in that
# moment. This detects a mood from IOTA'S OWN reply text (not the user's
# message — her reply is what should decide whether e.g. a laughing GIF
# or a shy GIF fits) and, some of the time, sends a matching GIF right
# after her text. Deliberately NOT on every message — that's what made
# a previous version feel repetitive/spammy (always the same "hi" wave
# GIF) — and deliberately mood-VARIED, sourced live from GIPHY, so it's
# never the same fallback GIF every time.

_REPLY_MOOD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r'(😂|🤣|hahaha+|lmao|lol\b)', re.I), "laugh"),
    (re.compile(r'(😭|😢|💔|😔|aw+\b|sorry)', re.I), "sad"),
    (re.compile(r'(😍|🥰|💕|💗|💞|cutie|pyaar|aww+)', re.I), "love"),
    (re.compile(r'(😡|🤬|😤|gussa|chup|badtameez)', re.I), "angry"),
    (re.compile(r'(🥳|🎉|yay+|lets goo|slay|badhai)', re.I), "happy"),
    (re.compile(r'(😱|😲|kya+\?|wait what|sach mein)', re.I), "surprise"),
    (re.compile(r'(💅|😎|okay bestie|king|queen)', re.I), "cool"),
    (re.compile(r'(🥺|so cute|awww)', re.I), "cute"),
]

# Chance that a reply is accompanied by a GIF at all — kept well under
# 50% so it still feels like an occasional, deliberate choice rather
# than mechanical spam on every single message.
_REPLY_GIF_PROBABILITY = 0.25


def _detect_reply_mood(reply_text: str) -> str | None:
    """Look at Iota's own reply text and return a mood if one clearly
    fits, else None (meaning: don't force a GIF for a neutral reply)."""
    for pattern, mood in _REPLY_MOOD_RULES:
        if pattern.search(reply_text):
            return mood
    return None


async def _maybe_send_reply_gif(msg, reply_text: str):
    """
    Probabilistically sends a mood-matched GIF right after Iota's text
    reply. Never raises — a failed/skipped GIF never affects the actual
    conversation, since the real text reply was already sent before
    this is even called.
    """
    try:
        if random.random() > _REPLY_GIF_PROBABILITY:
            return
        mood = _detect_reply_mood(reply_text)
        if not mood:
            return
        gif_url = await get_gif_for_mood(mood)
        if gif_url:
            await msg.reply_animation(gif_url)
    except Exception as e:
        logger.debug(f"_maybe_send_reply_gif failed: {e}")


def _is_asking_about_other(text: str) -> bool:
    lower = text.lower()
    triggers = ["uska", "unka", "us user", "is user", "uski", "unki",
                "kya kiya tha wo", "iska naam", "iski history",
                "tell me about", "what did they", "uske baare"]
    personal = ["memory", "history", "personal", "private", "bola tha",
                "likha tha", "details", "info", "kya karta"]
    return any(t in lower for t in triggers) and any(p in lower for p in personal)


# ── Intelligent search decision ───────────────────────────────────────────────
# No keyword triggers — AI itself decides. We use a fast heuristic to decide
# whether to even attempt search. The AI can always use search results or
# ignore them if irrelevant.

def _should_attempt_search(text: str) -> bool:
    """
    Very broad heuristic: search for anything that might benefit from
    current real-world info. When in doubt, search.
    Excludes: pure math, pure grammar, self-referential bot questions,
    casual banter/insults directed at the bot, and other short
    conversational messages that have nothing to look up.
    """
    t = text.lower().strip()
    # Skip search for things that obviously don't need it
    skip_patterns = [
        r'^\d[\d\s\+\-\*\/\(\)\.]*$',           # pure math
        r'^(hi|hello|hii|heyy?|bye|ok|okay|thx|thanks|ty)\b',  # greetings
        r'^(lol|lmao|haha|rofl|xd)',              # reactions
        r'apna naam|tera naam|your name|tum kaun|who are you',  # identity
        r'mere owner|your owner|kisne banaya|who made',          # owner
        # Casual banter/insults directed AT the bot — these are
        # conversational, not factual lookups. This is what was
        # triggering an unnecessary (and then leaked) search for
        # something like "u battamiz" — an insult, not a question.
        r'\b(battamiz|badtameez|pagal|bewakoof|stupid|dumb|idiot|shut ?up|chup|bakwas)\b',
        r'^(u |you |tu |tum )?(are |ho |hai )?(so |bhi )?(bad|worst|useless|kharab)',
        # Date/time/day questions — the current IST date+time is already
        # injected directly into the system prompt (see _build_system),
        # so searching the web for "what day is it" is both unnecessary
        # AND was a real source of leaked search-result text (exactly
        # the "Aaj konsa din hai" bug — Iota already knows this without
        # searching).
        r'(aaj|kal|abhi).*(din|date|time|tareek|samay)|what.*(day|date|time).*(today|now)|(konsa|kaunsa) din',
    ]
    for pat in skip_patterns:
        if re.search(pat, t, re.IGNORECASE):
            return False
    # Search only for messages with real substance — short 2-3 word
    # messages are almost always casual chat, not something to look up.
    word_count = len(t.split())
    return word_count >= 4


async def _respond(uid: int, text: str, is_premium: bool,
                   is_group=False, chat_title="", max_tokens=200,
                   first_name: str = "", username: str = "") -> str:
    # If this user has an active /connect, use the SHARED pair memory
    # instead of their own private history — this is what makes Iota
    # remember consistently for both connected users. See utils/connect.py.
    partner_id = await get_partner_id(uid)
    hist = await get_memory(uid, shared_with=partner_id)
    hist.append({"role": "user", "content": text})

    ctx = f"\n\n[Group: '{chat_title}' — share only public info]" if is_group else ""
    if partner_id:
        ctx += (
            f"\n\n[NOTE: This user is currently CONNECTED with another user "
            f"via /connect — you are seeing their SHARED conversation "
            f"history. Respond naturally as if continuing one shared "
            f"conversation between the two of them and you.]"
        )
    # Tell the AI who it's talking to. Username is deliberately included
    # here too (not hidden from the model) because the prompt's own rule
    # ("only mention username if asked") is enough — Iota needs to KNOW
    # the username to correctly answer "what's my username" when asked,
    # she just shouldn't volunteer it unprompted.
    who = f"\n\n[You are talking to: {first_name or 'a user'}"
    who += f" (username: @{username})" if username else " (no username set)"
    who += "]"
    ctx += who

    # Always attempt search — AI decides whether to use the results
    if _should_attempt_search(text):
        try:
            results = await search_summary(text, max_results=4)
            if results:
                ctx += f"\n\n[SEARCH RESULTS — use only if relevant to the question]\n{results}\n[END SEARCH RESULTS]"
        except Exception as e:
            logger.debug(f"search failed in _respond: {e}")

    # Build fresh system prompt (includes current IST time)
    system = _build_system() + ctx
    messages = [{"role": "system", "content": system}] + hist

    reply = await call_ai(messages, is_premium=is_premium,
                          max_tokens=max_tokens, temperature=0.9)

    # Safety net: strip any leaked [SEARCH RESULTS] block BEFORE the
    # markdown→HTML conversion (so we're working with the model's raw
    # text, not partially-escaped HTML).
    reply = _strip_search_leak(reply)

    # Convert any markdown the AI returned to Telegram HTML
    reply = _md_to_html(reply)

    await save_memory(uid, "user", text, shared_with=partner_id)
    await save_memory(uid, "assistant", reply, shared_with=partner_id)
    return reply


# ── /ai command ───────────────────────────────────────────────────────────────

async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; msg = update.effective_message
    chat_obj = update.effective_chat
    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)

    if context.args:
        user_text = " ".join(context.args)
    elif msg.reply_to_message and msg.reply_to_message.text:
        user_text = msg.reply_to_message.text
    else:
        await msg.reply_html("🤖 Usage: /ai &lt;kuch bhi poocho&gt;\nDM me bas message bhejo! 💕")
        return

    if _is_asking_about_other(user_text):
        await msg.reply_html("kyu tujhe uski personal details? nahi bataungi 🙄"); return

    thinking = await msg.reply_html("💭 soch rahi hoon...")
    try:
        is_group = chat_obj.type != "private"
        reply = await _respond(u.id, user_text, d.get("is_premium", False),
                               is_group, chat_obj.title or "",
                               first_name=u.first_name or "", username=u.username or "")
        await thinking.edit_text(reply, parse_mode="HTML")
        await _maybe_send_reply_gif(msg, reply)
    except Exception as e:
        logger.warning(f"ai_cmd failed: {e}")
        await thinking.edit_text("system pagal ho gaya 🙄 baad mein try karo")


# ── DM auto-reply ─────────────────────────────────────────────────────────────

_EMOJI_ONLY_STRIP_RE = re.compile(
    r'[\s'
    r'\U0001F300-\U0001FAFF'
    r'\U0001F600-\U0001F64F'
    r'\U0001F680-\U0001F6FF'
    r'\U0001F1E0-\U0001F1FF'
    r'\u2600-\u26FF'
    r'\u2700-\u27BF'
    r'\uFE00-\uFE0F'
    r'\u200d'
    r'\u20E3'
    r']+'
)


def _is_emoji_only(text: str) -> bool:
    """True if `text` is made up entirely of emoji/whitespace (no real
    words). Used so dm_message_handler steps aside for pure-emoji DMs
    and lets handlers.sticker_reply.emoji_only_handler reply instead —
    otherwise BOTH fired on the same message (one AI text reply + one
    GIF reply), giving the user two replies for a single emoji."""
    stripped = _EMOJI_ONLY_STRIP_RE.sub('', text)
    return not stripped and text.strip() != ""


async def dm_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto AI reply to ALL non-command DMs."""
    u = update.effective_user; msg = update.effective_message
    text = (msg.text or "").strip()
    if not text or text.startswith("/"): return
    if _is_emoji_only(text):
        # 🔴 FIX: without this, a pure-emoji DM got a reply from BOTH
        # this handler AND handlers.sticker_reply.emoji_only_handler —
        # two separate bot messages for one emoji. That dedicated
        # handler (registered at a later priority) is the right one to
        # handle this case, so we step aside here.
        return
    try:
        from handlers.fun import _valentine_state
        if u.id in _valentine_state: return
    except Exception as e:
        logger.debug(f"valentine state check failed: {e}")
    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)

    # ── Spam block check (15-min mute from flood detection) ──────────────────
    try:
        from utils.mongo_db import get_spam_block, clear_spam_block
        import time as _time_check
        until = await get_spam_block(u.id)
        if until and _time_check.time() < until:
            remaining = int((until - _time_check.time()) / 60) + 1
            await msg.reply_html(
                f"⛔ Yᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙʟᴏᴄᴋᴇᴅ ꜰʀᴏᴍ ᴜsɪɴɢ Iᴏᴛᴀ ꜰᴏʀ "
                f"{remaining} ᴍɪɴᴜᴛᴇ(s) ᴅᴜᴇ ᴛᴏ sᴘᴀᴍᴍɪɴɢ. Pʟᴇᴀsᴇ sʟᴏᴡ ᴅᴏᴡɴ."
            )
            return
        elif until:
            await clear_spam_block(u.id)
    except Exception:
        pass
    if _is_asking_about_other(text):
        await msg.reply_html("kyu tujhe uski personal details? nahi bataungi 🙄"); return
    try:
        reply = await _respond(u.id, text, d.get("is_premium", False), False, "", 150,
                               first_name=u.first_name or "", username=u.username or "")
        await msg.reply_html(reply)
        await _maybe_send_reply_gif(msg, reply)
    except Exception as e:
        logger.warning(f"dm_message_handler failed: {e}")


# ── Smart group-reply detection ───────────────────────────────────────────────
#
# Iota replies in a GROUP only when:
#   1. She is explicitly @username-tagged anywhere in the message
#   2. The message is a reply to one of Iota's own previous messages
#   3. The message DIRECTLY addresses her by name at the very start
#      ("Iota ...", "iota kya scene hai", "hey iota ...",
#       "yaar iota bahut acchi hai", "kisi ne iota use kiya kya")
#
# Matches "iota" as a standalone WORD anywhere in the message (not just
# at the start) — this is the "say her name and she responds" behaviour
# — while still NOT matching it as a substring inside an unrelated word
# (e.g. "iotaphone" or "chiiota" would NOT trigger this, only the exact
# word "iota" with a word boundary on both sides does).

_DIRECT_ADDRESS_RE = re.compile(r'\biota\b', re.IGNORECASE)


def _is_reply_to_bot(update: Update, bot_id: int) -> bool:
    msg = update.effective_message
    if not msg or not msg.reply_to_message: return False
    ru = msg.reply_to_message.from_user
    return bool(ru and ru.id == bot_id)


def _is_tagged(text: str, bot_username: str) -> bool:
    return f"@{bot_username}".lower() in text.lower()


def _is_direct_address(text: str) -> bool:
    return bool(_DIRECT_ADDRESS_RE.match(text.strip()))


async def group_mention_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; msg = update.effective_message
    text = (msg.text or "").strip()
    if not text: return
    try:
        me = await context.bot.get_me()
        bot_username = me.username or ""; bot_id = me.id
    except Exception as e:
        logger.debug(f"group_mention_handler get_me: {e}"); return

    tagged      = _is_tagged(text, bot_username)
    replied_to  = _is_reply_to_bot(update, bot_id)
    direct_addr = _is_direct_address(text)

    if not (tagged or replied_to or direct_addr): return

    clean = text
    if tagged:
        clean = re.sub(re.escape(f"@{bot_username}"), "", clean, flags=re.IGNORECASE).strip()
    if direct_addr:
        clean = _DIRECT_ADDRESS_RE.sub("", text, count=1).strip()

    if not clean:
        await msg.reply_html("kuch poocha? bol na cutie 🥺"); return

    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)

    if _is_asking_about_other(clean):
        await msg.reply_html("kyu tujhe uski personal details? group me sirf public info share hoti 🙄"); return

    try:
        reply = await _respond(u.id, clean, d.get("is_premium", False),
                               True, update.effective_chat.title or "", 150,
                               first_name=u.first_name or "", username=u.username or "")
        await msg.reply_html(reply)
        await _maybe_send_reply_gif(msg, reply)
    except Exception as e:
        logger.warning(f"group_mention_handler AI failed: {e}")
        await msg.reply_html("system pagal ho gaya 🙄")


async def clear_my_memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await clear_memory(u.id)
    await update.message.reply_html("🗑️ Teri saari memory delete kar di!\nAb fresh start 💕")
