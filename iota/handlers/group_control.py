"""
Iota Group Control — powerful admin tools to manage the chat itself
- /setgtitle <text>   → rename the group
- /setgdesc <text>    → set group description
- /setgpic            → reply to a photo to set it as group pic
- /slowmode <secs>    → set chat slow-mode (0 = off)
- /invitelink         → show the current primary invite link
- /revoke             → generate a fresh primary invite link
- /del                → delete the replied message
All commands are admin-only (bot-owner bypasses, as elsewhere).
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from utils.helpers import is_admin
from utils.safe_html import safe_html
from config import OWNER_ID

logger = logging.getLogger(__name__)


async def _is_admin_or_owner(update, context) -> bool:
    if update.effective_user.id == OWNER_ID:
        return True
    return await is_admin(update, context)


async def setgtitle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 <b>Groups only!</b>"); return
    if not await _is_admin_or_owner(update, context):
        await msg.reply_html("❌ <b>Admins only!</b>"); return
    if not context.args:
        await msg.reply_html("Usage: <code>/setgtitle &lt;new title&gt;</code>"); return
    title = " ".join(context.args)
    try:
        await context.bot.set_chat_title(chat.id, title[:128])
        await msg.reply_html(f"✅ <b>Title updated!</b>\n📛 {safe_html(title[:128])}")
    except TelegramError as e:
        await msg.reply_html(f"❌ Failed: {safe_html(str(e))}")


async def setgdesc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 <b>Groups only!</b>"); return
    if not await _is_admin_or_owner(update, context):
        await msg.reply_html("❌ <b>Admins only!</b>"); return
    if not context.args:
        await msg.reply_html("Usage: <code>/setgdesc &lt;new description&gt;</code>"); return
    desc = " ".join(context.args)
    try:
        await context.bot.set_chat_description(chat.id, desc[:255])
        await msg.reply_html("✅ <b>Description updated!</b>")
    except TelegramError as e:
        await msg.reply_html(f"❌ Failed: {safe_html(str(e))}")


async def setgpic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 <b>Groups only!</b>"); return
    if not await _is_admin_or_owner(update, context):
        await msg.reply_html("❌ <b>Admins only!</b>"); return
    if not (msg.reply_to_message and msg.reply_to_message.photo):
        await msg.reply_html("📷 Reply to a <b>photo</b> with <code>/setgpic</code>"); return
    photo = msg.reply_to_message.photo[-1]
    try:
        await context.bot.set_chat_photo(chat.id, photo)
        await msg.reply_html("✅ <b>Group photo updated!</b>")
    except TelegramError as e:
        await msg.reply_html(f"❌ Failed: {safe_html(str(e))}")


async def slowmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 <b>Groups only!</b>"); return
    if not await _is_admin_or_owner(update, context):
        await msg.reply_html("❌ <b>Admins only!</b>"); return
    if not context.args:
        cur = (chat.slow_mode_delay or 0)
        await msg.reply_html(
            f"🐢 <b>Slow Mode</b>\n\nCurrent: <b>{cur}s</b>\n"
            f"Usage: <code>/slowmode &lt;seconds&gt;</code> (0 = off, max 60)"
        ); return
    try:
        secs = int(context.args[0])
    except ValueError:
        await msg.reply_html("❌ Seconds must be a number!"); return
    secs = max(0, min(secs, 60))
    try:
        await context.bot.set_chat_slow_mode_delay(chat.id, secs)
        await msg.reply_html(
            "✅ Slow mode " + ("disabled." if secs == 0 else f"set to <b>{secs}s</b>.")
        )
    except TelegramError as e:
        await msg.reply_html(f"❌ Failed: {safe_html(str(e))}")


async def invitelink_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 <b>Groups only!</b>"); return
    if not await _is_admin_or_owner(update, context):
        await msg.reply_html("❌ <b>Admins only!</b>"); return
    try:
        link = await context.bot.export_chat_invite_link(chat.id)
        await msg.reply_html(f"🔗 <b>Invite Link:</b>\n<code>{safe_html(link)}</code>")
    except TelegramError as e:
        await msg.reply_html(f"❌ Failed: {safe_html(str(e))}")


async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 <b>Groups only!</b>"); return
    if not await _is_admin_or_owner(update, context):
        await msg.reply_html("❌ <b>Admins only!</b>"); return
    try:
        # Create a brand-new primary-style link (no join request) and export
        # it — this effectively rotates the previous primary link.
        await context.bot.create_chat_invite_link(chat.id, creates_join_request=False)
        link = await context.bot.export_chat_invite_link(chat.id)
        await msg.reply_html(
            f"🔄 <b>Invite link revoked & regenerated!</b>\n\n🔗 <code>{safe_html(link)}</code>"
        )
    except TelegramError as e:
        await msg.reply_html(f"❌ Failed: {safe_html(str(e))}")


async def del_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 <b>Groups only!</b>"); return
    if not await _is_admin_or_owner(update, context):
        await msg.reply_html("❌ <b>Admins only!</b>"); return
    target = msg.reply_to_message
    if not target:
        await msg.reply_html("🗑️ Reply to the message you want to delete."); return
    try:
        await context.bot.delete_message(chat.id, target.message_id)
    except TelegramError as e:
        await msg.reply_html(f"❌ Failed: {safe_html(str(e))}")
