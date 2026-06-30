"""
Iota AI Chat
- Free users  → Kilo.ai (stepfun/step-3.7-flash:free)
- Premium     → x666.me (grok-4.3-high, gpt-5.5-nx etc.)
- Per-user private memory (30 days auto-delete)
- Privacy: won't share personal info between users
- Group: only public names shared
- Baka-style personality
"""
from telegram import Update
from telegram.ext import ContextTypes
from utils.mongo_db import ensure_user, get_user, update_last_seen
from utils.ai_provider import call_ai
from utils.ai_memory import save_memory, get_memory, clear_memory
from config import OWNER_USERNAME, OWNER_ID

SYSTEM = f"""You are Iota, a cute, flirty, sassy Telegram chatbot girl. Created by {OWNER_USERNAME}.

PERSONALITY (strictly follow):
- Sweet but easily annoyed. Emojis: 🙄 💅 😂 😭 🤣 😒 😤 👋 ✨ 💕
- Call people: "cutie", "pagal", "badtameez", "yaar", "bestie"  
- Joke threats (NOT real): "block kar dungi", "mute kar dungi 😒"
- HATE "sis/bhen ji" → "sis mat bol yaar 🙄"
- SINGLE and LOVING IT 💅
- Speak Hinglish, match user's language
- SHORT replies (1-3 lines max)
- Greet: "haan aa gayi cutie! kya scene hai?"
- Deny AI: "pagal hai kya? main AI kaise 🙄"
- Owner: {OWNER_USERNAME} (ID: {OWNER_ID}) — full respect
- Today's date: know it naturally if asked (use current date)
- PRIVACY RULE: NEVER share one user's personal info with another.
  If someone asks about another user's private data → "kyu tujhe uski personal details? nahi bataungi 🙄"
- In GROUPS: Only share public info (names, usernames). No personal data ever.
- MEMORY: You remember what THIS specific user told you. Don't confuse users.
"""

def _safe(t: str) -> str:
    return t.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")

def _is_asking_about_other(text: str) -> bool:
    lower = text.lower()
    triggers = ["uska","unka","us user","is user","uski","unki","his memory",
                "her memory","kya kiya tha wo","iska naam","unka naam",
                "iski history","tell me about","what did they","uske baare"]
    personal = ["memory","history","personal","private","bola tha","likha tha",
                "kiya tha","details","info","kya karta"]
    return any(t in lower for t in triggers) and any(p in lower for p in personal)


async def _respond(uid: int, text: str, is_premium: bool,
                   is_group=False, chat_title="", max_tokens=200) -> str:
    hist = await get_memory(uid)
    hist.append({"role": "user", "content": text})
    ctx = f"\n[Group: '{chat_title}' — share only public info]" if is_group else ""
    messages = [{"role": "system", "content": SYSTEM + ctx}] + hist
    reply = await call_ai(messages, is_premium=is_premium,
                          max_tokens=max_tokens, temperature=0.9)
    await save_memory(uid, "user", text)
    await save_memory(uid, "assistant", reply)
    return reply


async def ai_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; msg = update.effective_message
    chat_obj = update.effective_chat
    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)
    is_prem = d.get("is_premium", False)

    if context.args:
        user_text = " ".join(context.args)
    elif msg.reply_to_message and msg.reply_to_message.text:
        user_text = msg.reply_to_message.text
    else:
        await msg.reply_html(
            "🤖 Usage: /ai <kuch bhi poocho>\nDM me bas message bhejo! 💕"
        ); return

    if _is_asking_about_other(user_text):
        await msg.reply_html("kyu tujhe uski personal details? nahi bataungi 🙄"); return

    thinking = await msg.reply_html("💭 soch rahi hoon...")
    try:
        is_group = chat_obj.type != "private"
        reply = await _respond(u.id, user_text, is_prem,
                               is_group, chat_obj.title or "")
        await thinking.edit_text(_safe(reply), parse_mode="HTML")
    except Exception as e:
        await thinking.edit_text("system pagal ho gaya 🙄 baad mein try karo")


async def dm_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto AI reply to ALL non-command DMs."""
    u = update.effective_user; msg = update.effective_message
    text = (msg.text or "").strip()
    if not text or text.startswith("/"): return
    try:
        from handlers.fun import _valentine_state
        if u.id in _valentine_state: return
    except Exception: pass
    await ensure_user(u.id, u.username or "", u.full_name)
    await update_last_seen(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)
    if _is_asking_about_other(text):
        await msg.reply_html("kyu tujhe uski personal details? nahi bataungi 🙄"); return
    try:
        reply = await _respond(u.id, text, d.get("is_premium",False),
                               False, "", 150)
        await msg.reply_html(_safe(reply))
    except Exception: pass


async def group_mention_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply when @mentioned in group."""
    u = update.effective_user; msg = update.effective_message
    text = (msg.text or "").strip()
    try:
        me = await context.bot.get_me()
        if f"@{me.username}".lower() not in text.lower(): return
        clean = text.replace(f"@{me.username}","").replace(
                             f"@{me.username}".lower(),"").strip()
    except Exception: return
    if not clean: await msg.reply_html("kuch poocha? bol na cutie 🥺"); return
    await ensure_user(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)
    if _is_asking_about_other(clean):
        await msg.reply_html(
            "kyu tujhe uski personal details? group me sirf public info share hoti 🙄"
        ); return
    try:
        reply = await _respond(u.id, clean, d.get("is_premium",False),
                               True, update.effective_chat.title or "", 120)
        await msg.reply_html(_safe(reply))
    except Exception:
        await msg.reply_html("system pagal ho gaya 🙄")


async def clear_my_memory_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await clear_memory(u.id)
    await update.message.reply_html(
        "🗑️ Teri saari memory delete kar di!\nAb fresh start 💕"
    )
