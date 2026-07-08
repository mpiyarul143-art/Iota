"""
Iota Bot — Unified Permission System

WHY THIS FILE EXISTS
─────────────────────
Before this, permission checks were done ad-hoc and inconsistently:
  - Owner-only commands had their own decorator, only in owner_panel.py.
  - Admin-only commands manually called `is_admin()` and branched by hand
    in ~15+ places, each with a slightly different error message, and
    each one easy to forget when adding a new command.
  - There was no reusable way to say "this command is group-only" or
    "this command is DM-only" — every command that needed that wrote its
    own ad-hoc check (or didn't check at all).

This module gives every command file ONE consistent, well-tested way to
declare who's allowed to run it and where:

    @owner_only          # only YOUR (the bot owner's) Telegram account
    @admin_only           # only group admins/creator (in that group)
    @group_only            # command only works inside groups
    @dm_only                # command only works in private chat
    @requires_not_banned      # blocks users the owner has banned

Decorators can be stacked, e.g.:

    @group_only
    @admin_only
    async def mute_cmd(update, context): ...

Every decorator sends ONE clear, consistent error message on failure and
never raises — so a permission check can never itself crash a command.
"""
import functools
import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID

logger = logging.getLogger(__name__)


def owner_only(func):
    """
    Restricts a command to ONLY the bot's owner (config.OWNER_ID) —
    regardless of the chat type (works identically in DMs and groups).
    Use for: bot-wide administration (/panel, /broadcast, /setmodel, etc.)
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        u = update.effective_user
        if not u or u.id != OWNER_ID:
            # Silent no-op for non-owners — deliberately does NOT reveal
            # that this is an owner-only command, so hidden/secret owner
            # commands (like /scan) stay undiscoverable to regular users.
            return
        return await func(update, context, *a, **kw)
    return wrapper


def admin_only(func):
    """
    Restricts a command to group admins/creator (checked live via
    get_chat_member, so it always reflects current admin status — no
    stale cached permissions). In DMs, "admin" has no meaning, so this
    allows the command through freely in private chats (pair with
    @group_only if the command should ALSO be restricted to groups).
    Use for: /mute, /ban, /warn, /close, /setwelcome, etc.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        chat = update.effective_chat
        u = update.effective_user
        if chat.type == "private":
            return await func(update, context, *a, **kw)
        if u.id == OWNER_ID:
            return await func(update, context, *a, **kw)  # owner bypasses admin checks everywhere
        try:
            member = await context.bot.get_chat_member(chat.id, u.id)
            is_admin = member.status in ("administrator", "creator")
        except Exception as e:
            logger.debug(f"admin_only: get_chat_member failed: {e}")
            is_admin = False
        if not is_admin:
            await update.effective_message.reply_html(
                "🚫 <b>Admins only!</b>\nYou need to be a group admin to use this command."
            )
            return
        return await func(update, context, *a, **kw)
    return wrapper


def group_only(func):
    """Restricts a command to group/supergroup chats only."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if update.effective_chat.type == "private":
            await update.effective_message.reply_html(
                "👥 <b>Groups only!</b>\nThis command only works inside a group."
            )
            return
        return await func(update, context, *a, **kw)
    return wrapper


def dm_only(func):
    """Restricts a command to private chats (DMs) only."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        if update.effective_chat.type != "private":
            await update.effective_message.reply_html(
                "📩 <b>DM only!</b>\nMessage me privately to use this command: "
                f"@{context.bot.username}"
            )
            return
        return await func(update, context, *a, **kw)
    return wrapper


def requires_not_banned(func):
    """
    Blocks users the owner has banned (is_banned=True in their user doc)
    from using economy/game commands. Owner is always exempt.
    Use for: /rob, /kill, /card, /ludo, /village, etc. — anything that
    touches the coin economy or games.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        u = update.effective_user
        if not u or u.id == OWNER_ID:
            return await func(update, context, *a, **kw)
        from utils.mongo_db import get_user
        d = await get_user(u.id)
        if d and d.get("is_banned"):
            await update.effective_message.reply_html(
                "🚫 <b>You are banned from using Iota.</b>\n"
                "Contact the bot owner if you believe this is a mistake."
            )
            return
        return await func(update, context, *a, **kw)
    return wrapper
