"""
Iota — Join Request Manager (Admin)
────────────────────────────────────
Telegram's Bot API in this version has no "list pending join requests" call,
so we capture every incoming ChatJoinRequest update into MongoDB and let
group admins manage them with these commands:

  /joinrequests             → list pending join requests (with inline buttons)
  /acceptjoin [id|@user|N]  → accept a specific user, or N requests (default 1)
  /rejectjoin [id|@user|N]  → reject a specific user, or N requests (default 1)
  /acceptall                → accept EVERY pending request in this chat
  /rejectall                → reject EVERY pending request in this chat

Inline buttons on /joinrequests let admins accept/reject per-user or all.
Every Telegram API call is wrapped so a failure (e.g. bot lacks permission)
never crashes the command — it is reported clearly instead.
"""
import logging
import time

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from utils.mongo_db import (
    get_db, save_join_request, delete_join_request,
    get_join_requests, count_join_requests,
)
from utils.helpers import is_admin, mention_id

logger = logging.getLogger(__name__)

PAGE_LIMIT = 10


# ── Incoming join request capture ──────────────────────────────────────────────

async def chat_join_request_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jr = update.chat_join_request
    if not jr:
        return
    try:
        chat = jr.chat
        user = jr.from_user
        invite = jr.invite_link
        await save_join_request(
            chat_id=chat.id,
            user_id=user.id,
            full_name=user.full_name or user.first_name or "User",
            username=user.username or "",
            date=int(time.time()),
            invite_link=(invite.invite_link if invite else ""),
        )
        total = await count_join_requests(chat.id)
        try:
            name = user.full_name or user.first_name or "User"
            await context.bot.send_message(
                chat.id,
                f"📥 <b>New join request</b>\n"
                f"👤 {mention_id(user.id, name)}\n"
                f"📊 <b>{total}</b> pending in this chat.\n"
                f"Manage them with /joinrequests",
                parse_mode="HTML",
            )
        except Exception:
            pass
    except Exception:
        logger.debug("chat_join_request_handler error", exc_info=True)


# ── Low-level Telegram API wrappers (never raise) ──────────────────────────────

async def _do_approve(bot, chat_id: int, user_id: int) -> bool:
    try:
        await bot.approve_chat_join_request(chat_id=chat_id, user_id=user_id)
        return True
    except TelegramError:
        return False


async def _do_decline(bot, chat_id: int, user_id: int) -> bool:
    try:
        await bot.decline_chat_join_request(chat_id=chat_id, user_id=user_id)
        return True
    except TelegramError:
        return False


# ── Shared list rendering (command + callback) ─────────────────────────────────

async def _build_list(chat_id: int):
    """Return (text, reply_markup) for the pending-requests panel."""
    pending = await get_join_requests(chat_id, limit=PAGE_LIMIT)
    total = await count_join_requests(chat_id)
    if not pending:
        return (
            "📭 <b>No pending join requests</b> in this chat.",
            None,
        )
    lines = [f"📋 <b>Pending Join Requests</b> ({total} total)\n"]
    buttons = []
    for p in pending:
        name = p.get("full_name") or f"User {p['user_id']}"
        uname = p.get("username")
        label = f"@{uname}" if uname else name
        lines.append(f"• {mention_id(p['user_id'], name)}  <code>({label})</code>")
        buttons.append([
            InlineKeyboardButton("✅ Accept", callback_data=f"jr_accept:{p['user_id']}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"jr_reject:{p['user_id']}"),
        ])
    buttons.append([
        InlineKeyboardButton("✅ Accept All", callback_data="jr_acceptall"),
        InlineKeyboardButton("❌ Reject All", callback_data="jr_rejectall"),
    ])
    if total > len(pending):
        lines.append(f"\n… and <b>{total - len(pending)}</b> more. Use /acceptall or /rejectall.")
    return "\n".join(lines), InlineKeyboardMarkup(buttons)


# ── Commands ───────────────────────────────────────────────────────────────────

async def joinrequests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type == "private":
        await msg.reply_html("👥 This command only works inside groups.")
        return
    if not await is_admin(update, context):
        await msg.reply_html("🚫 <b>Admins only!</b>")
        return
    text, markup = await _build_list(chat.id)
    await msg.reply_html(text, reply_markup=markup)


async def acceptjoin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type == "private":
        await msg.reply_html("👥 This command only works inside groups.")
        return
    if not await is_admin(update, context):
        await msg.reply_html("🚫 <b>Admins only!</b>")
        return

    args = context.args or []
    chat_id = chat.id
    pending = await get_join_requests(chat_id, limit=100000)
    known_ids = {p["user_id"] for p in pending}

    if not args:
        await _accept_many(update, context, count=1)
        return

    arg = args[0].lstrip("@")
    if arg.isdigit():
        uid = int(arg)
        if uid in known_ids:
            await _accept_single(update, context, uid)
        else:
            # Treat as a count of requests to accept.
            await _accept_many(update, context, count=uid)
        return

    # Username form: find a matching pending request.
    target = next(
        (p for p in pending if (p.get("username") or "").lower() == arg.lower()),
        None,
    )
    if target:
        await _accept_single(update, context, target["user_id"])
    else:
        await msg.reply_html(
            f"🔍 No pending join request from <b>@{arg}</b> in this chat."
        )


async def rejectjoin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type == "private":
        await msg.reply_html("👥 This command only works inside groups.")
        return
    if not await is_admin(update, context):
        await msg.reply_html("🚫 <b>Admins only!</b>")
        return

    args = context.args or []
    chat_id = chat.id
    pending = await get_join_requests(chat_id, limit=100000)
    known_ids = {p["user_id"] for p in pending}

    if not args:
        await _reject_many(update, context, count=1)
        return

    arg = args[0].lstrip("@")
    if arg.isdigit():
        uid = int(arg)
        if uid in known_ids:
            await _reject_single(update, context, uid)
        else:
            await _reject_many(update, context, count=uid)
        return

    target = next(
        (p for p in pending if (p.get("username") or "").lower() == arg.lower()),
        None,
    )
    if target:
        await _reject_single(update, context, target["user_id"])
    else:
        await msg.reply_html(
            f"🔍 No pending join request from <b>@{arg}</b> in this chat."
        )


async def acceptall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type == "private":
        await msg.reply_html("👥 This command only works inside groups.")
        return
    if not await is_admin(update, context):
        await msg.reply_html("🚫 <b>Admins only!</b>")
        return
    await _accept_many(update, context, count=None)


async def rejectall_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    if not chat or chat.type == "private":
        await msg.reply_html("👥 This command only works inside groups.")
        return
    if not await is_admin(update, context):
        await msg.reply_html("🚫 <b>Admins only!</b>")
        return
    await _reject_many(update, context, count=None)


# ── Internal processing ────────────────────────────────────────────────────────

async def _accept_single(update, context, user_id: int):
    chat_id = update.effective_chat.id
    ok = await _do_approve(context.bot, chat_id, user_id)
    if ok:
        await delete_join_request(chat_id, user_id)
        await update.effective_message.reply_html(
            f"✅ Accepted join request from {mention_id(user_id, str(user_id))}."
        )
    else:
        await update.effective_message.reply_html(
            f"❌ Could not accept request for <code>{user_id}</code>.\n"
            "The bot may lack <b>Invite Users</b> admin rights, or the request "
            "is no longer pending."
        )


async def _reject_single(update, context, user_id: int):
    chat_id = update.effective_chat.id
    ok = await _do_decline(context.bot, chat_id, user_id)
    if ok:
        await delete_join_request(chat_id, user_id)
        await update.effective_message.reply_html(
            f"❌ Rejected join request from {mention_id(user_id, str(user_id))}."
        )
    else:
        await update.effective_message.reply_html(
            f"❌ Could not reject request for <code>{user_id}</code>.\n"
            "The bot may lack <b>Invite Users</b> admin rights, or the request "
            "is no longer pending."
        )


async def _accept_many(update, context, count):
    """Accept `count` oldest requests (count=None → all)."""
    chat_id = update.effective_chat.id
    pending = await get_join_requests(chat_id, limit=100000)
    if not pending:
        await update.effective_message.reply_html("✅ No pending join requests!")
        return
    pending.sort(key=lambda p: p.get("date", 0))
    to_process = pending if count is None else pending[: max(1, count)]
    done = 0
    for p in to_process:
        if await _do_approve(context.bot, chat_id, p["user_id"]):
            await delete_join_request(chat_id, p["user_id"])
            done += 1
    remaining = await count_join_requests(chat_id)
    await update.effective_message.reply_html(
        f"✅ Accepted <b>{done}</b> join request(s).\n"
        f"📊 <b>{remaining}</b> still pending."
    )


async def _reject_many(update, context, count):
    """Reject `count` oldest requests (count=None → all)."""
    chat_id = update.effective_chat.id
    pending = await get_join_requests(chat_id, limit=100000)
    if not pending:
        await update.effective_message.reply_html("✅ No pending join requests!")
        return
    pending.sort(key=lambda p: p.get("date", 0))
    to_process = pending if count is None else pending[: max(1, count)]
    done = 0
    for p in to_process:
        if await _do_decline(context.bot, chat_id, p["user_id"]):
            await delete_join_request(chat_id, p["user_id"])
            done += 1
    remaining = await count_join_requests(chat_id)
    await update.effective_message.reply_html(
        f"❌ Rejected <b>{done}</b> join request(s).\n"
        f"📊 <b>{remaining}</b> still pending."
    )


# ── Inline button callback ─────────────────────────────────────────────────────

async def join_request_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    msg = query.message
    chat = update.effective_chat
    if not chat or chat.type == "private":
        await msg.edit_text("👥 This only works inside groups.")
        return
    if not await is_admin(update, context):
        await msg.edit_text("🚫 Admins only!")
        return

    data = query.data or ""
    chat_id = chat.id
    parts = data.split(":", 1)

    if data == "jr_acceptall":
        pending = await get_join_requests(chat_id, limit=100000)
        done = 0
        for p in pending:
            if await _do_approve(context.bot, chat_id, p["user_id"]):
                await delete_join_request(chat_id, p["user_id"])
                done += 1
        await msg.edit_text(f"✅ Accepted <b>{done}</b> join request(s).", parse_mode="HTML")
        return

    if data == "jr_rejectall":
        pending = await get_join_requests(chat_id, limit=100000)
        done = 0
        for p in pending:
            if await _do_decline(context.bot, chat_id, p["user_id"]):
                await delete_join_request(chat_id, p["user_id"])
                done += 1
        await msg.edit_text(f"❌ Rejected <b>{done}</b> join request(s).", parse_mode="HTML")
        return

    if len(parts) == 2 and parts[0] in ("jr_accept", "jr_reject"):
        try:
            uid = int(parts[1])
        except ValueError:
            await msg.edit_text("❌ Invalid request.")
            return
        if parts[0] == "jr_accept":
            ok = await _do_approve(context.bot, chat_id, uid)
        else:
            ok = await _do_decline(context.bot, chat_id, uid)
        if ok:
            await delete_join_request(chat_id, uid)
        # Refresh the list panel (or show a single-result message).
        text, markup = await _build_list(chat_id)
        if markup is None:
            await msg.edit_text(text, parse_mode="HTML")
        else:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=markup)
        return

    await msg.edit_text("❌ Unknown action.")
