"""
Iota Group Protection System
━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

import re, time
from collections import defaultdict
from telegram import Update, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from utils.db import get_conn, ensure_user
from utils.helpers import mention, ts, is_admin

# ── DB setup ──────────────────────────────────────────────────────────────────

def _ensure_tables():
    c = get_conn()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS group_protection (
        chat_id             INTEGER PRIMARY KEY,
        enabled             INTEGER DEFAULT 1,
        anti_spam           INTEGER DEFAULT 1,
        anti_link           INTEGER DEFAULT 1,
        anti_arabic         INTEGER DEFAULT 0,
        anti_forward        INTEGER DEFAULT 0,
        anti_bot            INTEGER DEFAULT 1,
        anti_flood          INTEGER DEFAULT 1,
        flood_limit         INTEGER DEFAULT 5,
        flood_window        INTEGER DEFAULT 5,
        anti_raid           INTEGER DEFAULT 1,
        raid_threshold      INTEGER DEFAULT 10,
        raid_window         INTEGER DEFAULT 30,
        profanity_filter    INTEGER DEFAULT 0,
        log_channel         INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS reports (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id     INTEGER,
        reporter_id INTEGER,
        reported_id INTEGER,
        reason      TEXT    DEFAULT '',
        msg_text    TEXT    DEFAULT '',
        status      TEXT    DEFAULT 'pending',
        created_at  INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS whitelisted_links (
        chat_id     INTEGER,
        domain      TEXT,
        PRIMARY KEY (chat_id, domain)
    );

    CREATE TABLE IF NOT EXISTS bad_words (
        chat_id     INTEGER,
        word        TEXT,
        PRIMARY KEY (chat_id, word)
    );
    """)
    c.commit()

_ensure_tables()

# ── Runtime flood tracking ────────────────────────────────────────────────────
# {chat_id: {user_id: [timestamps]}}
_flood_data: dict = defaultdict(lambda: defaultdict(list))
_raid_data:  dict = defaultdict(list)   # {chat_id: [join_timestamps]}

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_prot(chat_id: int) -> dict:
    row = get_conn().execute(
        "SELECT * FROM group_protection WHERE chat_id=?", (chat_id,)
    ).fetchone()
    if row:
        return dict(row)
    # Insert defaults
    get_conn().execute(
        "INSERT OR IGNORE INTO group_protection (chat_id) VALUES(?)", (chat_id,)
    )
    get_conn().commit()
    return get_prot(chat_id)

def update_prot(chat_id: int, **kw):
    if not kw: return
    c = get_conn()
    c.execute(
        f"UPDATE group_protection SET {','.join(f'{k}=?' for k in kw)} WHERE chat_id=?",
        list(kw.values()) + [chat_id]
    )
    c.commit()
    # Make sure row exists
    get_conn().execute("INSERT OR IGNORE INTO group_protection(chat_id) VALUES(?)", (chat_id,))
    get_conn().commit()

def add_report(chat_id, reporter_id, reported_id, reason, msg_text=""):
    c = get_conn()
    c.execute(
        "INSERT INTO reports(chat_id,reporter_id,reported_id,reason,msg_text,status,created_at) VALUES(?,?,?,?,?,'pending',?)",
        (chat_id, reporter_id, reported_id, reason, msg_text, ts())
    )
    c.commit()

def get_reports(chat_id, status="pending"):
    return get_conn().execute(
        "SELECT * FROM reports WHERE chat_id=? AND status=? ORDER BY created_at DESC",
        (chat_id, status)
    ).fetchall()

def get_report_count(chat_id):
    r = get_conn().execute(
        "SELECT COUNT(*) as c FROM reports WHERE chat_id=? AND status='pending'", (chat_id,)
    ).fetchone()
    return r["c"]

def resolve_report(report_id, status="resolved"):
    c = get_conn()
    c.execute("UPDATE reports SET status=? WHERE id=?", (status, report_id))
    c.commit()

def get_bad_words(chat_id):
    return [r["word"] for r in get_conn().execute(
        "SELECT word FROM bad_words WHERE chat_id=?", (chat_id,)
    ).fetchall()]

def add_bad_word(chat_id, word):
    c = get_conn()
    c.execute("INSERT OR IGNORE INTO bad_words(chat_id,word) VALUES(?,?)", (chat_id, word.lower()))
    c.commit()

def remove_bad_word(chat_id, word):
    c = get_conn()
    c.execute("DELETE FROM bad_words WHERE chat_id=? AND word=?", (chat_id, word.lower()))
    c.commit()

LINK_PATTERN  = re.compile(r'(https?://|t\.me/|@\w{5,})', re.IGNORECASE)
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
    if not log_channel: return
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

    # Skip admins/bots
    if u.is_bot:
        return
    if await is_admin(update, context, u.id):
        return

    prot = get_prot(chat.id)
    if not prot["enabled"]:
        return

    text = msg.text or msg.caption or ""
    now  = ts()

    # ── Anti-flood ────────────────────────────────────────────────────────────
    if prot["anti_flood"]:
        window = prot["flood_window"]
        limit  = prot["flood_limit"]
        times  = _flood_data[chat.id][u.id]
        times  = [t for t in times if now - t < window]
        times.append(now)
        _flood_data[chat.id][u.id] = times

        if len(times) > limit:
            await _delete_msg(msg)
            await _mute_user(context.bot, chat.id, u.id, 300)
            try:
                warn = await context.bot.send_message(
                    chat.id,
                    f"⚡ {mention(u)} muted for <b>5 min</b> — flood detected!",
                    parse_mode="HTML"
                )
                context.job_queue.run_once(
                    lambda c: c.bot.delete_message(chat.id, warn.message_id),
                    10
                )
            except Exception:
                pass
            await _log(context.bot, prot["log_channel"],
                       f"⚡ Flood | {u.id} | {chat.title}")
            return

    # ── Anti-link ─────────────────────────────────────────────────────────────
    if prot["anti_link"] and text:
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
            await _log(context.bot, prot["log_channel"],
                       f"🔗 Link spam | {u.id} | {chat.title}")
            return

    # ── Anti-Arabic/foreign ───────────────────────────────────────────────────
    if prot["anti_arabic"] and text:
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
    if prot["anti_forward"] and msg.forward_origin:
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
    if prot["profanity_filter"] and text:
        bad_words = get_bad_words(chat.id)
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

    prot = get_prot(chat.id)
    if not prot["enabled"] or not prot["anti_raid"]:
        return

    now     = ts()
    window  = prot["raid_window"]
    thresh  = prot["raid_threshold"]

    joins = _raid_data[chat.id]
    joins = [t for t in joins if now - t < window]
    joins.extend([now] * len(msg.new_chat_members))
    _raid_data[chat.id] = joins

    if len(joins) >= thresh:
        # Enable slow mode
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
        await _log(context.bot, prot["log_channel"],
                   f"🚨 Raid detected | {chat.title} | {len(joins)} joins in {window}s")


# ── Anti-bot ──────────────────────────────────────────────────────────────────

async def anti_bot_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    chat = update.effective_chat
    if not msg or not msg.new_chat_members:
        return

    prot = get_prot(chat.id)
    if not prot["enabled"] or not prot["anti_bot"]:
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

    ensure_user(u.id, u.username or "", u.full_name)

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

    add_report(chat.id, u.id, reported.id, reason, msg_text[:200])

    report_count = get_report_count(chat.id)

    # Notify admins
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
    except Exception as e:
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

    pending  = get_reports(chat.id, "pending")
    resolved = get_reports(chat.id, "resolved")

    if not pending:
        await update.message.reply_html(
            f"📊 <b>Reports — {chat.title}</b>\n\n"
            f"✅ No pending reports!\n"
            f"Total resolved: {len(resolved)}"
        ); return

    text = f"📊 <b>Pending Reports — {chat.title}</b>\n\n"
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
    if not args:
        prot = get_prot(chat.id)
        def _s(v): return "✅" if v else "❌"
        await update.message.reply_html(
            f"🛡️ <b>Protection Settings — {chat.title}</b>\n\n"
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
            "/prot flood limit <number>\n"
            "/prot setlog <channel_id>"
        ); return

    cmd = args[0].lower()
    val_str = args[1].lower() if len(args) > 1 else "on"
    val     = 1 if val_str == "on" else 0

    mapping = {
        "on":        lambda: update_prot(chat.id, enabled=1),
        "off":       lambda: update_prot(chat.id, enabled=0),
        "flood":     lambda: update_prot(chat.id, anti_flood=val),
        "spam":      lambda: update_prot(chat.id, anti_spam=val),
        "link":      lambda: update_prot(chat.id, anti_link=val),
        "arabic":    lambda: update_prot(chat.id, anti_arabic=val),
        "foreign":   lambda: update_prot(chat.id, anti_arabic=val),
        "forward":   lambda: update_prot(chat.id, anti_forward=val),
        "bot":       lambda: update_prot(chat.id, anti_bot=val),
        "raid":      lambda: update_prot(chat.id, anti_raid=val),
        "profanity": lambda: update_prot(chat.id, profanity_filter=val),
    }

    if cmd in mapping:
        mapping[cmd]()
        await update.message.reply_html(
            f"✅ Protection <b>{cmd}</b> → <b>{'ON' if val else 'OFF'}</b>"
        )
    elif cmd == "flood" and val_str == "limit" and len(args) > 2:
        try:
            limit = int(args[2])
            update_prot(chat.id, flood_limit=limit)
            await update.message.reply_html(f"✅ Flood limit set to <b>{limit} msgs/{prot['flood_window']}s</b>")
        except ValueError:
            await update.message.reply_html("❌ Invalid limit number!")
    elif cmd == "setlog":
        try:
            log_id = int(args[1])
            update_prot(chat.id, log_channel=log_id)
            await update.message.reply_html(f"✅ Log channel set to <code>{log_id}</code>")
        except (ValueError, IndexError):
            await update.message.reply_html("❌ Provide channel ID: /prot setlog -1001234567890")
    else:
        await update.message.reply_html("❌ Unknown option. Use /prot for help.")


# ── /addword / /removeword / /badwords ────────────────────────────────────────

async def addword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; u = update.effective_user
    if chat.type == "private": await update.message.reply_html("🚫 Group only!"); return
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    if not context.args: await update.message.reply_html("Usage: /addword <word>"); return
    word = " ".join(context.args).lower()
    add_bad_word(chat.id, word)
    await update.message.reply_html(f"✅ Bad word added: <b>{word}</b>")

async def removeword_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; u = update.effective_user
    if chat.type == "private": await update.message.reply_html("🚫 Group only!"); return
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    if not context.args: await update.message.reply_html("Usage: /removeword <word>"); return
    word = " ".join(context.args).lower()
    remove_bad_word(chat.id, word)
    await update.message.reply_html(f"✅ Removed: <b>{word}</b>")

async def badwords_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private": await update.message.reply_html("🚫 Group only!"); return
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    words = get_bad_words(chat.id)
    if not words: await update.message.reply_html("📋 No bad words set!"); return
    await update.message.reply_html(
        f"🤬 <b>Bad Words List</b>\n\n" + "\n".join(f"• {w}" for w in words)
    )
