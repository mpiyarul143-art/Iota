"""
Iota Bot — System Gate Decorators (/close, /open)

See utils/mongo_db.py's get_system_status/set_system_status for the
underlying storage. This module provides the actual per-command
enforcement as simple decorators, so every game/economy/village command
gets the SAME consistent "is this system closed right now?" check
without repeating it by hand in 30+ places.

USAGE
──────
    @games_gate
    async def card_cmd(update, context): ...

    @economy_gate
    async def daily_cmd(update, context): ...

    @village_gate
    async def collect_cmd(update, context): ...

Each decorator:
  - Only applies in groups (DMs are never gated — /close is a group-
    admin tool, and per-user DM economy access was never in scope for
    it in the reference behaviour either).
  - Shows one consistent, clear message when the relevant system is
    closed, telling the user which system is closed and how an admin
    reopens it.
  - Never blocks silently — the user always knows why nothing happened.
"""
import functools
from utils.mongo_db import get_system_status


def _make_gate(system_key: str, label: str, emoji: str):
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(update, context, *a, **kw):
            chat = update.effective_chat
            if chat.type == "private":
                return await func(update, context, *a, **kw)
            status = await get_system_status(chat.id)
            if not status.get(system_key, True):
                await update.effective_message.reply_html(
                    f"{emoji} <b>{label} System Closed</b>\n\n"
                    f"An admin has disabled {label.lower()} in this group.\n"
                    f"Reopen with: /open"
                )
                return
            return await func(update, context, *a, **kw)
        return wrapper
    return decorator


games_gate   = _make_gate("games",   "Games",   "🎮")
economy_gate = _make_gate("economy", "Economy", "💰")
village_gate = _make_gate("village", "Village",  "🏰")
