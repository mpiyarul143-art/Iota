import random
from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes
from utils.db import get_conn, ensure_user, get_user
from utils.helpers import mention, ts

# ── Welcome GIF URLs (Telegram file_id or web URLs fallback) ─────────────────
WELCOME_GIFS = [
    "https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExNmRiNDFmNGE2ZDM3ZjVlNzQ3NmE5M2QyZDVlNWY0ZTQ5OWFiNDU2ZCZlcD12MV9pbnRlcm5hbGdfZ2lmX2J5X2lkJmN0PWc/3ohzdIuqJoo8QdKlnW/giphy.gif",
]

WELCOME_TEXTS = [
    "💗 welcome {name}",
    "🌸 Hiee {name}, welcome to {group}!",
    "✨ Hey {name}! Glad you joined {group} 💕",
    "🎉 Welcome {name} to {group}! Have fun 🎊",
    "💫 Ayyy {name} is here! Welcome to {group} 🥳",
]

WELCOME_STICKER_IDS: list = []  # Add Telegram sticker file_ids here

# ── DB helpers ────────────────────────────────────────────────────────────────

def get_welcome_settings(chat_id: int) -> dict:
    c = get_conn()
    row = c.execute("SELECT * FROM welcome_settings WHERE chat_id=?", (chat_id,)).fetchone()
    if row:
        return dict(row)
    return {"chat_id": chat_id, "enabled": 1, "custom_msg": "", "send_gif": 1, "send_sticker": 0}

def set_welcome_settings(chat_id, enabled=None, custom_msg=None, send_gif=None, send_sticker=None):
    c = get_conn()
    cur = get_welcome_settings(chat_id)
    e   = enabled     if enabled     is not None else cur["enabled"]
    cm  = custom_msg  if custom_msg  is not None else cur["custom_msg"]
    sg  = send_gif    if send_gif    is not None else cur["send_gif"]
    ss  = send_sticker if send_sticker is not None else cur["send_sticker"]
    c.execute("""INSERT OR REPLACE INTO welcome_settings
                 (chat_id,enabled,custom_msg,send_gif,send_sticker)
                 VALUES(?,?,?,?,?)""", (chat_id, e, cm, sg, ss))
    c.commit()

def _ensure_welcome_table():
    c = get_conn()
    c.execute("""CREATE TABLE IF NOT EXISTS welcome_settings (
        chat_id     INTEGER PRIMARY KEY,
        enabled     INTEGER DEFAULT 1,
        custom_msg  TEXT    DEFAULT '',
        send_gif    INTEGER DEFAULT 1,
        send_sticker INTEGER DEFAULT 0
    )""")
    c.commit()

_ensure_welcome_table()

# ── New member handler ────────────────────────────────────────────────────────

async def new_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg  = update.effective_message
    if not msg or not msg.new_chat_members:
        return

    ws = get_welcome_settings(chat.id)
    if not ws["enabled"]:
        return

    for member in msg.new_chat_members:
        if member.is_bot:
            continue

        ensure_user(member.id, member.username or "", member.full_name)
        name_str = mention(member)
        group_str = f"<b>{chat.title}</b>"

        # Build welcome text
        if ws["custom_msg"]:
            text = ws["custom_msg"].replace("{name}", name_str).replace("{group}", group_str)
        else:
            tmpl = random.choice(WELCOME_TEXTS)
            text = tmpl.format(name=name_str, group=group_str)

        try:
            # Send GIF first if enabled
            if ws["send_gif"]:
                await context.bot.send_animation(
                    chat.id,
                    animation="https://media.giphy.com/media/3ohzdIuqJoo8QdKlnW/giphy.gif",
                    caption=text,
                    parse_mode="HTML"
                )
            else:
                await msg.reply_html(text)

            # Send sticker if we have one
            if ws["send_sticker"] and WELCOME_STICKER_IDS:
                await context.bot.send_sticker(chat.id, random.choice(WELCOME_STICKER_IDS))

        except Exception:
            # Fallback plain text
            try:
                await context.bot.send_message(chat.id, text, parse_mode="HTML")
            except Exception:
                pass


# ── Left member handler ───────────────────────────────────────────────────────

async def left_member_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg  = update.effective_message
    if not msg or not msg.left_chat_member:
        return
    member = msg.left_chat_member
    if member.is_bot:
        return
    try:
        await context.bot.send_message(
            chat.id,
            f"👋 {mention(member)} has left <b>{chat.title}</b>. Goodbye!",
            parse_mode="HTML"
        )
    except Exception:
        pass


# ── /setwelcome ───────────────────────────────────────────────────────────────

async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from utils.helpers import is_admin
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_html("🚫 Use in a group!"); return
    if not await is_admin(update, context):
        await update.message.reply_html("❌ Admins only!"); return

    args = context.args
    if not args:
        await update.message.reply_html(
            "📝 <b>Welcome Settings</b>\n\n"
            "Usage:\n"
            "/setwelcome on — Enable welcome\n"
            "/setwelcome off — Disable welcome\n"
            "/setwelcome gif on/off — Toggle GIF\n"
            "/setwelcome msg <text> — Custom message\n"
            "  Use {name} for user, {group} for group name\n"
            "/setwelcome reset — Reset to default"
        ); return

    cmd = args[0].lower()
    if cmd == "on":
        set_welcome_settings(chat.id, enabled=1)
        await update.message.reply_html("✅ Welcome messages <b>enabled</b>!")
    elif cmd == "off":
        set_welcome_settings(chat.id, enabled=0)
        await update.message.reply_html("❌ Welcome messages <b>disabled</b>!")
    elif cmd == "gif":
        val = args[1].lower() if len(args)>1 else "on"
        set_welcome_settings(chat.id, send_gif=1 if val=="on" else 0)
        await update.message.reply_html(f"🎬 Welcome GIF: <b>{'on' if val=='on' else 'off'}</b>")
    elif cmd == "msg":
        custom = " ".join(args[1:])
        if not custom:
            await update.message.reply_html("❌ Provide a message!"); return
        set_welcome_settings(chat.id, custom_msg=custom)
        await update.message.reply_html(f"✅ Welcome message set!\nPreview:\n{custom}")
    elif cmd == "reset":
        set_welcome_settings(chat.id, custom_msg="", send_gif=1)
        await update.message.reply_html("✅ Welcome reset to default!")
    else:
        await update.message.reply_html("❌ Unknown option. Use /setwelcome for help.")
