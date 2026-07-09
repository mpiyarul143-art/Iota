"""
Iota Global Ban (GBAN) — owner-only network-wide ban system
- /gban <user> [reason]   → globally ban a user across every group Iota is in
- /ungban <user>          → remove a global ban
- /gbanlist               → list currently GBANNED users
Enforcement: gban_join_handler() bans any GBANNED user the moment they
join a group (registered in bot.py on NEW_CHAT_MEMBERS, before the
welcome handler runs).
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from utils.mongo_db import add_gban, remove_gban, is_gbanned, list_gban
from utils.helpers import mention, resolve_target
from utils.safe_html import safe_html
from config import OWNER_ID

logger = logging.getLogger(__name__)


def _own(uid: int) -> bool:
    return int(uid) == int(OWNER_ID)


async def gban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not _own(update.effective_user.id):
        await msg.reply_html("🔒 <b>Owner only command!</b>"); return
    if not context.args and not msg.reply_to_message:
        await msg.reply_html(
            "🌐 <b>Global Ban</b>\n\n"
            "Usage: <code>/gban &lt;@username|id|reply&gt; [reason]</code>"
        ); return
    uid, name, rest = await resolve_target(update, context, context.args or [])
    if not uid:
        await msg.reply_html("❌ Could not resolve that user."); return
    if uid == OWNER_ID:
        await msg.reply_html("😂 You can't GBAN yourself!"); return
    reason = " ".join(rest) or "No reason given."
    await add_gban(uid, reason, update.effective_user.id)
    await msg.reply_html(
        f"🌐 <b>User GBANNED!</b>\n\n"
        f"👤 {name}\n📝 {safe_html(reason)}\n\n"
        f"They will be auto-banned from any group Iota is in."
    )


async def ungban_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not _own(update.effective_user.id):
        await msg.reply_html("🔒 <b>Owner only command!</b>"); return
    if not context.args and not msg.reply_to_message:
        await msg.reply_html("Usage: <code>/ungban &lt;@username|id|reply&gt;</code>"); return
    uid, name, _ = await resolve_target(update, context, context.args or [])
    if not uid:
        await msg.reply_html("❌ Could not resolve that user."); return
    if await remove_gban(uid):
        await msg.reply_html(f"✅ <b>GBAN removed for</b> {name}")
    else:
        await msg.reply_html(f"❌ {name} was not GBANNED.")


async def gbanlist_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not _own(update.effective_user.id):
        await msg.reply_html("🔒 <b>Owner only command!</b>"); return
    rows = await list_gban(50)
    if not rows:
        await msg.reply_html("📭 <b>No users are currently GBANNED.</b>"); return
    text = f"🌐 <b>GBAN List ({len(rows)})</b>\n\n"
    for r in rows:
        uid = r["_id"]
        name = r.get("reason", "No reason")
        text += f"🔹 <code>{uid}</code> — {safe_html(str(name))[:60]}\n"
    await msg.reply_html(text)


async def gban_join_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-ban GBANNED users on join. Runs at a low group number so it
    fires before the welcome handler welcomes them."""
    msg = update.effective_message
    if not msg or not msg.new_chat_members:
        return
    chat = update.effective_chat
    for member in msg.new_chat_members:
        if member.is_bot:
            continue
        try:
            g = await is_gbanned(member.id)
        except Exception:
            continue
        if not g:
            continue
        try:
            await context.bot.ban_chat_member(chat.id, member.id)
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🌐 <b>{mention(member)} was auto-banned — GBANNED by owner.</b>\n"
                    f"📝 {safe_html(str(g.get('reason','')))}",
                    parse_mode="HTML",
                )
            except Exception:
                pass
        except TelegramError:
            # Bot may lack ban rights; just log.
            logger.warning(f"GBAN enforcement failed in chat {chat.id} for {member.id}")
