"""
Iota Group Protection System — MongoDB-backed
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Auto-detects and handles:
  • Spam floods (too many messages from one user)
  • Arabic/foreign script spam
  • Link spam (non-whitelisted URLs)
  • Forwarded channel spam
  • New-account spam bots
  • Bot additions
  • Profanity/bad words
  • Report system (/report or @admin)
  • Anti-raid (mass join flood)
"""

import re
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from utils.mongo_db import (
    ensure_user, get_prot, update_prot, add_report, get_reports,
    get_report_count, get_bad_words, add_bad_word, remove_bad_word
)
from utils.helpers import mention, ts, is_admin
from utils.safe_html import safe_html

# ── Runtime flood tracking (in-memory, per-process) ───────────────────────────
# {chat_id: {user_id: [timestamps]}}
_flood_data: dict = defaultdict(lambda: defaultdict(list))
_raid_data:  dict = defaultdict(list)   # {chat_id: [join_timestamps]}

LINK_PATTERN   = re.compile(r'(https?://|t\.me/|@\w{5,})', re.IGNORECASE)
ARABIC_PATTERN = re.compile(r'[\u0600-\u06FF\u0750-\u077F]{5,}')


async def _mute_user(bot, chat_id, user_id, seconds=300):
    try:
        from datetime import datetime, timezone
        until = datetime.fromtimestamp(ts() + seconds, tz=timezone.utc)
        await bot.restrict_chat_member(
            chat_id, user_id,
            ChatPermissions(can_send_messages=False),
            until_date=until
        )
    except TelegramError:
        pass


async def _ban_user(bot, chat_id, user_id):
    try:
        await bot.ban_chat_member(chat_id, user_id)
    except TelegramError:
        pass


async def _delete_msg(msg):
    try:
        await msg.delete()
    except Exception:
        pass


async def _log(bot, log_channel, text):
    if not log_channel:
        return
    try:
        await bot.send_message(log_channel, text, parse_mode="HTML")
    except Exception:
        pass


# ── Main protection message handler ──────────────────────────────────────────

async def protection_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    chat = update.effective_chat
    u    = update.effective_user

    if not msg or not u or chat.type == "private":
        return

    if u.is_bot:
        return
    if await is_admin(update, context, u.id):
        return

    prot = await get_prot(chat.id)
    if not prot.get("enabled", True):
        return

    text = msg.text or msg.caption or ""
    now  = ts()

    # ── Anti-flood ────────────────────────────────────────────────────────────
    if prot.get("anti_flood", True):
        window = prot.get("flood_window", 5)
        limit  = prot.get("flood_limit", 5)
        times  = _flood_data[chat.id][u.id]
        times  = [t for t in times if now - t < window]
        times.append(now)
        _flood_data[chat.id][u.id] = times

        if len(times) > limit:
            await _delete_msg(msg)
            block_seconds = 900  # 15 minutes, matching Baka
            await _mute_user(context.bot, chat.id, u.id, block_seconds)
            try:
                from utils.fonts import sc as _sc
                warn = await context.bot.send_message(
                    chat.id,
                    f"⛔ {_sc('Spam Detected!')} {mention(u)} "
                    f"{_sc('You Are Blocked For 15 Minutes.')}",
                    parse_mode="HTML"
                )
                # DM the spammer — exact Baka-style message
                try:
                    import time as _time
                    from utils.mongo_db import set_spam_block
                    await set_spam_block(u.id, _time.time() + block_seconds)
                    await context.bot.send_message(
                        u.id,
                        "⛔ Yᴏᴜ ʜᴀᴠᴇ ʙᴇᴇɴ ʙʟᴏᴄᴋᴇᴅ ꜰʀᴏᴍ ᴜsɪɴɢ Iᴏᴛᴀ ꜰᴏʀ "
                        "15 ᴍɪɴᴜᴛᴇs ᴅᴜᴇ ᴛᴏ sᴘᴀᴍᴍɪɴɢ. Pʟᴇᴀsᴇ sʟᴏᴡ ᴅᴏᴡɴ."
                    )
                except Exception:
                    pass  # user may have blocked the bot — that's fine
                if context.job_queue:
                    context.job_queue.run_once(
                        lambda c: c.bot.delete_message(chat.id, warn.message_id),
                        10
                    )
            except Exception:
                pass
            await _log(context.bot, prot.get("log_channel", 0),
                       f"⛔ Spam | {u.id} | {chat.title}")
            return

    # ── Anti-link ─────────────────────────────────────────────────────────────
    if prot.get("anti_link", True) and text:
        if LINK_PATTERN.search(text):
            await _delete_msg(msg)
            await _mute_user(context.bot, chat.id, u.id, 180)
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🔗 {mention(u)} — Links are not allowed! Muted 3 min.",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            await _log(context.bot, prot.get("log_channel", 0),
                       f"🔗 Link spam | {u.id} | {chat.title}")
            return

    # ── Anti-Arabic/foreign ───────────────────────────────────────────────────
    if prot.get("anti_arabic", False) and text:
        if ARABIC_PATTERN.search(text):
            await _delete_msg(msg)
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🌐 {mention(u)} — Foreign script spam removed!",
                    parse_mode="HTML"
                )
            except Exception:
                pass
            return

    # ── Anti-forward ──────────────────────────────────────────────────────────
    if prot.get("anti_forward", False) and msg.forward_origin:
        await _delete_msg(msg)
        try:
            await context.bot.send_message(
                chat.id,
                f"📤 {mention(u)} — Forwarded messages are not allowed here!",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return

    # ── Profanity filter ──────────────────────────────────────────────────────
    if prot.get("profanity_filter", False) and text:
        bad_words = await get_bad_words(chat.id)
        for bw in bad_words:
            if bw in text.lower():
                await _delete_msg(msg)
                await _mute_user(context.bot, chat.id, u.id, 120)
                try:
                    await context.bot.send_message(
                        chat.id,
                        f"🤬 {mention(u)} — Bad word detected! Muted 2 min.",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
                return


# ── Anti-raid (new member flood) ─────────────────────────────────────────────

async def anti_raid_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    chat = update.effective_chat
    if not msg or not msg.new_chat_members:
        return

    prot = await get_prot(chat.id)
    if not prot.get("enabled", True) or not prot.get("anti_raid", True):
        return

    now    = ts()
    window = prot.get("raid_window", 30)
    thresh = prot.get("raid_threshold", 10)

    joins = _raid_data[chat.id]
    joins = [t for t in joins if now - t < window]
    joins.extend([now] * len(msg.new_chat_members))
    _raid_data[chat.id] = joins

    if len(joins) >= thresh:
        try:
            await context.bot.set_chat_slow_mode_delay(chat.id, 60)
            await context.bot.send_message(
                chat.id,
                f"🚨 <b>RAID DETECTED!</b>\n\n"
                f"{len(joins)} users joined in {window}s.\n"
                f"Slow mode enabled (60s) for protection!\n"
                f"Admins can disable with /prot raid off",
                parse_mode="HTML"
            )
        except Exception:
            pass
        await _log(context.bot, prot.get("log_channel", 0),
                   f"🚨 Raid detected | {chat.title} | {len(joins)} joins in {window}s")


# ── Anti-bot ──────────────────────────────────────────────────────────────────

async def anti_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    chat = update.effective_chat
    if not msg or not msg.new_chat_members:
        return

    prot = await get_prot(chat.id)
    if not prot.get("enabled", True) or not prot.get("anti_bot", True):
        return

    for member in msg.new_chat_members:
        if member.is_bot and member.id != context.bot.id:
            try:
                await context.bot.ban_chat_member(chat.id, member.id)
                await context.bot.send_message(
                    chat.id,
                    f"🤖 Bot <b>{member.first_name}</b> was auto-removed! (Anti-bot protection)",
                    parse_mode="HTML"
                )
            except Exception:
                pass


# ── /report command ───────────────────────────────────────────────────────────

async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    chat = update.effective_chat
    u    = update.effective_user

    if chat.type == "private":
        await msg.reply_html("🚫 Use in a group!"); return

    await ensure_user(u.id, u.username or "", u.full_name)

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(
            "❌ Reply to a message to report it!\n"
            "Usage: /report [reason]"
        ); return

    reported = msg.reply_to_message.from_user
    if reported.is_bot:
        await msg.reply_html("❌ Can't report a bot!"); return
    if reported.id == u.id:
        await msg.reply_html("❌ Can't report yourself!"); return

    reason   = " ".join(context.args) if context.args else "No reason provided"
    msg_text = msg.reply_to_message.text or ""

    await add_report(chat.id, u.id, reported.id, reason, msg_text[:200])

    report_count = await get_report_count(chat.id)

    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        admin_mentions = " ".join(
            mention(a.user) for a in admins if not a.user.is_bot
        )

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔨 Mute",  callback_data=f"rep_mute_{reported.id}_{chat.id}"),
            InlineKeyboardButton("⛔ Ban",   callback_data=f"rep_ban_{reported.id}_{chat.id}"),
            InlineKeyboardButton("✅ Ignore", callback_data=f"rep_ignore_{reported.id}_{chat.id}"),
        ]])

        await msg.reply_html(
            f"🚨 <b>User Reported!</b>\n\n"
            f"👤 Reported: {mention(reported)}\n"
            f"📝 By: {mention(u)}\n"
            f"💬 Reason: {reason}\n"
            f"📊 Pending reports: <b>{report_count}</b>\n\n"
            f"👮 Admins: {admin_mentions}",
            reply_markup=kb
        )
    except Exception:
        await msg.reply_html(f"✅ Report submitted! Pending reports: {report_count}")


# ── Report callback ────────────────────────────────────────────────────────────

async def report_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = q.from_user
    if not await is_admin(update, context, u.id):
        await q.answer("Admins only!", show_alert=True); return

    parts = q.data.split("_")
    action    = parts[1]
    target_id = int(parts[2])
    chat_id   = int(parts[3])

    await q.answer()

    if action == "mute":
        await _mute_user(context.bot, chat_id, target_id, 3600)
        await q.edit_message_text(
            q.message.text + f"\n\n✅ Muted by {mention(u)} for 1 hour.",
            parse_mode="HTML"
        )
    elif action == "ban":
        await _ban_user(context.bot, chat_id, target_id)
        await q.edit_message_text(
            q.message.text + f"\n\n⛔ Banned by {mention(u)}.",
            parse_mode="HTML"
        )
    elif action == "ignore":
        await q.edit_message_text(
            q.message.text + f"\n\n✅ Ignored by {mention(u)}.",
            parse_mode="HTML"
        )


# ── /reports command ──────────────────────────────────────────────────────────

async def reports_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    u    = update.effective_user

    if chat.type == "private":
        await update.message.reply_html("🚫 Use in a group!"); return
    if not await is_admin(update, context):
        await update.message.reply_html("❌ Admins only!"); return

    pending  = await get_reports(chat.id, "pending")
    resolved = await get_reports(chat.id, "resolved")

    if not pending:
        await update.message.reply_html(
            f"📊 <b>Reports — {safe_html(chat.title)}</b>\n\n"
            f"✅ No pending reports!\n"
            f"Total resolved: {len(resolved)}"
        ); return

    text = f"📊 <b>Pending Reports — {safe_html(chat.title)}</b>\n\n"
    for i, r in enumerate(pending[:10], 1):
        try:
            rep_user = await context.bot.get_chat(r["reporter_id"])
            tgt_user = await context.bot.get_chat(r["reported_id"])
            rep_name = rep_user.first_name
            tgt_name = tgt_user.first_name
        except Exception:
            rep_name = str(r["reporter_id"])
            tgt_name = str(r["reported_id"])

        import time as _time
        t = _time.strftime("%d/%m %H:%M", _time.localtime(r["created_at"]))
        text += (
            f"{i}. 👤 <b>{tgt_name}</b>\n"
            f"   Reason: {r['reason']}\n"
            f"   By: {rep_name} | {t}\n\n"
        )

    text += f"📌 Showing {min(10, len(pending))}/{len(pending)} pending"
    await update.message.reply_html(text)


# ── /prot command — protection settings ──────────────────────────────────────

async def prot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; u = update.effective_user
    if chat.type == "private":
        await update.message.reply_html("🚫 Use in a group!"); return
    if not await is_admin(update, context):
        await update.message.reply_html("❌ Admins only!"); return

    args = context.args
    prot = await get_prot(chat.id)

    if not args:
        def _s(v): return "✅" if v else "❌"
        await update.message.reply_html(
            f"🛡️ <b>Protection Settings — {safe_html(chat.title)}</b>\n\n"
            f"{_s(prot['enabled'])} Overall: <b>{'ON' if prot['enabled'] else 'OFF'}</b>\n"
            f"{_s(prot['anti_flood'])} Anti-Flood (limit: {prot['flood_limit']}/{prot['flood_window']}s)\n"
            f"{_s(prot['anti_spam'])} Anti-Spam\n"
            f"{_s(prot['anti_link'])} Anti-Link\n"
            f"{_s(prot['anti_arabic'])} Anti-Arabic/Foreign\n"
            f"{_s(prot['anti_forward'])} Anti-Forward\n"
            f"{_s(prot['anti_bot'])} Anti-Bot\n"
            f"{_s(prot['anti_raid'])} Anti-Raid (threshold: {prot['raid_threshold']}/{prot['raid_window']}s)\n"
            f"{_s(prot['profanity_filter'])} Profanity Filter\n\n"
            "Usage:\n"
            "/prot on/off — Enable/disable all\n"
            "/prot flood on/off\n"
            "/prot link on/off\n"
            "/prot arabic on/off\n"
            "/prot forward on/off\n"
            "/prot bot on/off\n"
            "/prot raid on/off\n"
            "/prot profanity on/off\n"
            "/prot flood limit &lt;number&gt;\n"
            "/prot setlog &lt;channel_id&gt;"
        ); return

    cmd     = args[0].lower()
    val_str = args[1].lower() if len(args) > 1 else "on"
    val     = val_str == "on"

    mapping = {
        "on":        {"enabled": True},
        "off":       {"enabled": False},
        "flood":     {"anti_flood": val},
        "spam":      {"anti_spam": val},
        "link":      {"anti_link": val},
        "arabic":    {"anti_arabic": val},
        "foreign":   {"anti_arabic": val},
        "forward":   {"anti_forward": val},
        "bot":       {"anti_bot": val},
        "raid":      {"anti_raid": val},
        "profanity": {"profanity_filter": val},
    }

    if cmd == "flood" and val_str == "limit" and len(args) > 2:
        try:
            limit = int(args[2])
            await update_prot(chat.id, flood_limit=limit)
            await update.message.reply_html(
                f"✅ Flood limit set to <b>{limit} msgs/{prot['flood_window']}s</b>"
            )
        except ValueError:
            await update.message.reply_html("❌ Invalid limit number!")
    elif cmd == "setlog":
        try:
            log_id = int(args[1])
            await update_prot(chat.id, log_channel=log_id)
            await update.message.reply_html(f"✅ Log channel set to <code>{log_id}</code>")
        except (ValueError, IndexError):
            await update.message.reply_html("❌ Provide channel ID: /prot setlog -1001234567890")
    elif cmd in mapping:
        await update_prot(chat.id, **mapping[cmd])
        await update.message.reply_html(
            f"✅ Protection <b>{cmd}</b> → <b>{'ON' if val else 'OFF'}</b>"
        )
    else:
        await update.message.reply_html("❌ Unknown option. Use /prot for help.")


# ── /addword / /removeword / /badwords ────────────────────────────────────────

async def addword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private": await update.message.reply_html("🚫 Group only!"); return
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    if not context.args: await update.message.reply_html("Usage: /addword &lt;word&gt;"); return
    word = " ".join(context.args).lower()
    await add_bad_word(chat.id, word)
    await update.message.reply_html(f"✅ Bad word added: <b>{word}</b>")


async def removeword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private": await update.message.reply_html("🚫 Group only!"); return
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    if not context.args: await update.message.reply_html("Usage: /removeword &lt;word&gt;"); return
    word = " ".join(context.args).lower()
    await remove_bad_word(chat.id, word)
    await update.message.reply_html(f"✅ Removed: <b>{word}</b>")


async def badwords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private": await update.message.reply_html("🚫 Group only!"); return
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    words = await get_bad_words(chat.id)
    if not words: await update.message.reply_html("📋 No bad words set!"); return
    await update.message.reply_html(
        f"🤬 <b>Bad Words List</b>\n\n" + "\n".join(f"• {w}" for w in words)
    )
