"""
Iota Bot — /connect command handlers
See utils/connect.py for the full design/data-model documentation.
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from utils.mongo_db import ensure_user, get_user, get_db
from utils.helpers import mention, resolve_target
from utils.safe_html import safe_html
from utils.connect import (
    create_request, respond_to_request, disconnect, get_active_connection,
    request_keyboard, CONNECT_DURATION_SECONDS,
)

logger = logging.getLogger(__name__)


def _mention_id(uid: int) -> str:
    return f'<a href="tg://user?id={uid}">this user</a>'


async def connect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/connect (reply to a user, or /connect @username) — send a memory-sync request."""
    u = update.effective_user
    msg = update.effective_message
    await ensure_user(u.id, u.username or "", u.full_name)

    target_id, target_mention, _ = await resolve_target(update, context, context.args)
    if not target_id:
        await msg.reply_html(
            "🔗 <b>Connect</b>\n\n"
            "Share memory with a friend so Iota remembers your chats "
            "consistently for both of you!\n\n"
            "Usage: reply to their message with /connect, or "
            "<code>/connect @username</code>"
        ); return

    target_user = None
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target_user = msg.reply_to_message.from_user
    if target_user and target_user.is_bot:
        await msg.reply_html("❌ You can't connect with a bot!"); return

    ok, result = await create_request(u.id, target_id)
    if not ok:
        await msg.reply_html(f"❌ {result}"); return

    cid = result
    hours = CONNECT_DURATION_SECONDS // 3600
    try:
        await context.bot.send_message(
            target_id,
            f"🔗 <b>Connection Request!</b>\n\n"
            f"{mention(u)} wants to connect with you — if you accept, Iota "
            f"will remember your conversations with her as SHARED for the "
            f"next {hours} hours, so you'll both get consistent answers "
            f"when you talk to her together or separately.\n\n"
            f"Accept?",
            parse_mode="HTML",
            reply_markup=request_keyboard(cid)
        )
        await msg.reply_html(
            f"📨 Connection request sent! Waiting for "
            f"{target_mention or 'them'} to respond in their DM."
        )
    except (Forbidden, BadRequest):
        # Clean up the pending request since it can never be answered.
        await get_db().connections.delete_one({"_id": cid})
        await msg.reply_html(
            f"❌ I couldn't DM {target_mention or 'that user'} — they need "
            f"to start a chat with me first (send /start in my DM), then "
            f"you can try /connect again!"
        )


async def connect_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = q.from_user
    parts = q.data.split("_")
    action, cid = parts[1], "_".join(parts[2:])

    conn = await respond_to_request(cid, accept=(action == "accept"))
    if not conn:
        await q.answer("This request is no longer valid.", show_alert=True); return

    # Only the invited user (user_b) should be able to respond.
    if u.id != conn["user_b"]:
        await q.answer("This request isn't for you!", show_alert=True); return

    await q.answer()
    inviter_id = conn["user_a"]

    if conn["status"] == "active":
        hours = CONNECT_DURATION_SECONDS // 3600
        await q.edit_message_text(
            f"✅ <b>Connected!</b>\n\nYou're now synced with {_mention_id(inviter_id)} "
            f"for the next {hours} hours. Iota will remember your chats consistently "
            f"for both of you!\n\n🆔 Connection ID: <code>{cid}</code>\n\n"
            f"Use /disconnect anytime to end this early.",
            parse_mode="HTML"
        )
        try:
            await context.bot.send_message(
                inviter_id,
                f"✅ <b>{mention(u)} accepted your connection request!</b>\n\n"
                f"🆔 Connection ID: <code>{cid}</code>\n"
                f"⏱️ Active for the next {hours} hours.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"connect_callback: notify inviter failed: {e}")
    else:
        await q.edit_message_text("❌ Request declined.")
        try:
            await context.bot.send_message(
                inviter_id,
                f"❌ <b>{mention(u)} declined your connection request.</b>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.debug(f"connect_callback: notify inviter of denial failed: {e}")


async def disconnect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    conn = await disconnect(u.id)
    if not conn:
        await update.message.reply_html("❌ You're not connected with anyone right now."); return

    partner_id = conn["user_b"] if conn["user_a"] == u.id else conn["user_a"]
    await update.message.reply_html("🔌 Connection ended. Memories are separate again.")
    try:
        await context.bot.send_message(
            partner_id,
            f"🔌 <b>{mention(u)} ended your connection.</b>\n"
            f"Memories are separate again — reconnect anytime with /connect!",
            parse_mode="HTML"
        )
    except Exception as e:
        logger.debug(f"disconnect_cmd: notify partner failed: {e}")


async def connect_id_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    conn = await get_active_connection(u.id)
    if not conn:
        await update.message.reply_html(
            "🔗 You're not connected with anyone right now.\nUse /connect to start!"
        ); return
    import time as _time
    remaining = conn["expires_at"] - int(_time.time())
    h, m = divmod(max(0, remaining) // 60, 60)
    partner_id = conn["user_b"] if conn["user_a"] == u.id else conn["user_a"]
    await update.message.reply_html(
        f"🔗 <b>Active Connection</b>\n\n"
        f"🆔 ID: <code>{conn['_id']}</code>\n"
        f"👤 Connected with: {_mention_id(partner_id)}\n"
        f"⏳ Time left: {h}h {m}m"
    )
