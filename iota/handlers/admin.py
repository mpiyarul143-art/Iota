"""
Iota Admin Handler
. or ! prefix commands
Baka-style promote levels with titles
"""
import re, time
from telegram import Update, ChatPermissions, ChatAdministratorRights
from telegram.ext import ContextTypes
from telegram.error import TelegramError
from utils.mongo_db import (add_warning, get_warnings, remove_last_warning,
                             count_warnings, track_promotion,
                             get_bot_promotions, remove_promotion)
from utils.helpers import ts, mention, parse_duration, is_admin
from utils.fonts import sc

PROMOTE_TITLES = {
    "0": ("🥇", "Junior Admin",  {"can_manage_chat": True}),
    "1": ("🥈", "Admin",         {"can_manage_chat": True, "can_delete_messages": True,
                                   "can_restrict_members": True, "can_invite_users": True}),
    "2": ("🥉", "Senior Admin",  {"can_manage_chat": True, "can_delete_messages": True,
                                   "can_restrict_members": True, "can_invite_users": True,
                                   "can_pin_messages": True, "can_change_info": True}),
    "3": ("🏅", "Full Admin",    {"can_manage_chat": True, "can_delete_messages": True,
                                   "can_restrict_members": True, "can_invite_users": True,
                                   "can_pin_messages": True, "can_change_info": True,
                                   "can_promote_members": True}),
}

POWER_MAP = {
    "delete": "can_delete_messages", "restrict": "can_restrict_members",
    "invite": "can_invite_users",    "pin": "can_pin_messages",
    "info": "can_change_info",       "promote": "can_promote_members",
    "manage": "can_manage_chat",     "video": "can_manage_video_chats",
}

async def dot_admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg  = update.effective_message
    text = msg.text or ""
    m = re.match(r'^[.!](\w+)\s?(.*)', text, re.DOTALL)
    if not m: return
    cmd  = m.group(1).lower()
    rest = m.group(2).strip()
    if cmd == "help": await _help(update); return
    if cmd == "imute":
        if not await is_admin(update, context):
            await msg.reply_html("❌ Admins only!"); return
        await _imute(update, context, rest); return
    if not await is_admin(update, context):
        await msg.reply_html("❌ Admins only!"); return
    dispatch = {
        "warn":      _warn,
        "unwarn":    _unwarn,
        "warns":     _warns,
        "mute":      lambda u,c,r: _mute(u,c,r,False),
        "dmute":     lambda u,c,r: _mute(u,c,r,True),
        "unmute":    _unmute,
        "ban":       lambda u,c,r: _ban(u,c,r,False),
        "dban":      lambda u,c,r: _ban(u,c,r,True),
        "unban":     _unban,
        "kick":      _kick,
        "promote":   _promote,
        "demote":    _demote,
        "demote_all":lambda u,c,r: _demote_all(u,c),
        "add":       _add_power,
        "remove":    _remove_power,
        "title":     _title,
        "pin":       lambda u,c,r: _pin(u,c),
        "unpin":     lambda u,c,r: _unpin(u,c),
        "d":         lambda u,c,r: _delete(u,c),
    }
    fn = dispatch.get(cmd)
    if fn: await fn(update, context, rest)

async def _resolve(update, context, rest: str):
    msg = update.effective_message; parts = rest.split()
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, mention(u), parts
    if not parts: return None, None, []
    t = parts[0].lstrip("@"); extra = parts[1:]
    if t.isdigit():
        uid = int(t)
        try:
            mb = await context.bot.get_chat_member(update.effective_chat.id, uid)
            return uid, mention(mb.user), extra
        except Exception:
            return uid, f"User {uid}", extra
    else:
        try:
            ch = await context.bot.get_chat(f"@{t}")
            return ch.id, f'<a href="tg://user?id={ch.id}">{ch.first_name}</a>', extra
        except Exception:
            return None, None, extra

async def _warn(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    reason = " ".join(extra) or "No reason"
    await add_warning(uid, chat.id, reason, update.effective_user.id)
    count = await count_warnings(uid, chat.id)
    if count >= 3:
        try:
            await context.bot.ban_chat_member(chat.id, uid)
            await msg.reply_html(f"⛔ {uname} <b>{sc('Banned')}!</b> (3 {sc('warnings reached')})")
        except TelegramError as e:
            await msg.reply_html(f"❌ {e}")
    else:
        await msg.reply_html(f"⚠️ {uname} {sc('Warned!')} (<b>{count}/3</b>)\n{sc('Reason')}: {reason}")

async def _unwarn(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, _ = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    if await remove_last_warning(uid, chat.id):
        c = await count_warnings(uid, chat.id)
        await msg.reply_html(f"✅ {sc('Warning Removed From')} {uname}. {sc('Now')}: <b>{c}/3</b>")
    else:
        await msg.reply_html(f"❓ {uname} {sc('has no warnings!')}")

async def _warns(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, _ = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    rows = await get_warnings(uid, chat.id)
    if not rows: await msg.reply_html(f"✅ {uname} {sc('has no warnings!')}"); return
    text = f"⚠️ <b>{sc('Warnings for')} {uname}:</b>\n\n"
    for i, w in enumerate(rows, 1):
        t = time.strftime("%d/%m/%Y", time.localtime(w.get("warned_at",0)))
        text += f"{i}. {w.get('reason','?')} ({t})\n"
    await msg.reply_html(text)

async def _mute(update, context, rest, delete=False):
    msg = update.effective_message; chat = update.effective_chat
    if delete and msg.reply_to_message:
        try: await msg.reply_to_message.delete()
        except Exception: pass
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    dur_str = extra[0] if extra else ""
    secs = parse_duration(dur_str)
    perms = ChatPermissions(can_send_messages=False)
    try:
        if secs:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts()+secs, tz=timezone.utc)
            await context.bot.restrict_chat_member(chat.id, uid, perms, until_date=dt)
            await msg.reply_html(f"🔇 {uname} {sc('Muted For')} <b>{dur_str}</b>!")
        else:
            await context.bot.restrict_chat_member(chat.id, uid, perms)
            await msg.reply_html(f"🔇 {uname} {sc('Muted Permanently')}!")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _imute(update, context, rest):
    """Mute media only (images, stickers, GIFs)."""
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    dur_str = extra[0] if extra else ""
    secs = parse_duration(dur_str)
    perms = ChatPermissions(
        can_send_messages=True,
        can_send_media_messages=False,
        can_send_polls=False,
        can_send_other_messages=False,
        can_add_web_page_previews=False,
    )
    try:
        if secs:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(ts()+secs, tz=timezone.utc)
            await context.bot.restrict_chat_member(chat.id, uid, perms, until_date=dt)
            await msg.reply_html(f"🖼️ {uname} {sc('Media Muted For')} <b>{dur_str}</b>!")
        else:
            await context.bot.restrict_chat_member(chat.id, uid, perms)
            await msg.reply_html(f"🖼️ {uname} {sc('Media Muted Permanently')}!")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _unmute(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, _ = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    perms = ChatPermissions(
        can_send_messages=True, can_send_media_messages=True,
        can_send_polls=True, can_send_other_messages=True,
        can_add_web_page_previews=True, can_invite_users=True
    )
    try:
        await context.bot.restrict_chat_member(chat.id, uid, perms)
        await msg.reply_html(f"🔊 {uname} {sc('Unmuted')}!")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _ban(update, context, rest, delete=False):
    msg = update.effective_message; chat = update.effective_chat
    if delete and msg.reply_to_message:
        try: await msg.reply_to_message.delete()
        except Exception: pass
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    reason = " ".join(extra) or "No reason"
    try:
        await context.bot.ban_chat_member(chat.id, uid)
        await msg.reply_html(f"⛔ {uname} <b>{sc('Banned')}!</b>\n{sc('Reason')}: {reason}")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _unban(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, _ = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    try:
        await context.bot.unban_chat_member(chat.id, uid, only_if_banned=True)
        await msg.reply_html(f"✅ {uname} <b>{sc('Unbanned')}!</b>")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _kick(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, _ = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    try:
        await context.bot.ban_chat_member(chat.id, uid)
        await context.bot.unban_chat_member(chat.id, uid)
        await msg.reply_html(f"👢 {uname} <b>{sc('Kicked')}!</b>")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _promote(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    level = extra[0] if extra else "1"
    info  = PROMOTE_TITLES.get(level, PROMOTE_TITLES["1"])
    medal, title_name, rights_kw = info
    try:
        rights = ChatAdministratorRights(**rights_kw)
        await context.bot.promote_chat_member(chat.id, uid, rights=rights)
        try:
            await context.bot.set_chat_administrator_custom_title(chat.id, uid, title_name)
        except Exception: pass
        await track_promotion(uid, chat.id, update.effective_user.id)
        await msg.reply_html(
            f"{uname} {sc('Promoted To')} {medal} {sc(title_name)}."
        )
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _demote(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, _ = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    rights = ChatAdministratorRights(
        can_manage_chat=False, can_delete_messages=False,
        can_restrict_members=False, can_invite_users=False,
        can_pin_messages=False, can_change_info=False, can_promote_members=False
    )
    try:
        await context.bot.promote_chat_member(chat.id, uid, rights=rights)
        await remove_promotion(uid, chat.id)
        await msg.reply_html(f"⬇️ {uname} <b>{sc('Demoted')}!</b>")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _demote_all(update, context):
    msg = update.effective_message; chat = update.effective_chat
    rows = await get_bot_promotions(chat.id)
    if not rows: await msg.reply_html(f"❓ {sc('No tracked promotions!')}"); return
    rights = ChatAdministratorRights(
        can_manage_chat=False, can_delete_messages=False,
        can_restrict_members=False, can_invite_users=False,
        can_pin_messages=False, can_change_info=False, can_promote_members=False
    )
    done = 0
    for r in rows:
        try:
            await context.bot.promote_chat_member(chat.id, r["user_id"], rights=rights)
            await remove_promotion(r["user_id"], chat.id); done += 1
        except Exception: pass
    await msg.reply_html(f"✅ {sc('Demoted')} <b>{done}</b> {sc('admins')}.")

async def _add_power(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid or not extra:
        await msg.reply_html(f"❌ {sc('Usage')}: .add [user] <power>\n{sc('Powers')}: {' | '.join(POWER_MAP.keys())}"); return
    perm = POWER_MAP.get(extra[0].lower())
    if not perm: await msg.reply_html(f"❌ {sc('Unknown power!')}"); return
    try:
        rights = ChatAdministratorRights(**{perm: True, "can_manage_chat": True})
        await context.bot.promote_chat_member(chat.id, uid, rights=rights)
        await msg.reply_html(f"✅ {sc('Added')} <b>{extra[0]}</b> {sc('power to')} {uname}!")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _remove_power(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid or not extra:
        await msg.reply_html(f"❌ {sc('Usage')}: .remove [user] <power>"); return
    perm = POWER_MAP.get(extra[0].lower())
    if not perm: await msg.reply_html(f"❌ {sc('Unknown power!')}"); return
    try:
        rights = ChatAdministratorRights(**{perm: False, "can_manage_chat": True})
        await context.bot.promote_chat_member(chat.id, uid, rights=rights)
        await msg.reply_html(f"✅ {sc('Removed')} <b>{extra[0]}</b> {sc('from')} {uname}!")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _title(update, context, rest):
    msg = update.effective_message; chat = update.effective_chat
    uid, uname, extra = await _resolve(update, context, rest)
    if not uid: await msg.reply_html("❌ Specify a user!"); return
    title = " ".join(extra)
    try:
        await context.bot.set_chat_administrator_custom_title(chat.id, uid, title)
        await msg.reply_html(f"🏷️ {uname}'s {sc('title')}: <b>{title or '(none)'}</b>")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _pin(update, context):
    msg = update.effective_message
    if not msg.reply_to_message:
        await msg.reply_html(f"❌ {sc('Reply to a message!')}"); return
    try:
        await msg.reply_to_message.pin()
        await msg.reply_html(f"📌 {sc('Pinned!')}") 
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _unpin(update, context):
    msg = update.effective_message
    try:
        if msg.reply_to_message:
            await context.bot.unpin_chat_message(
                update.effective_chat.id, msg.reply_to_message.message_id)
        else:
            await context.bot.unpin_chat_message(update.effective_chat.id)
        await msg.reply_html(f"📌 {sc('Unpinned!')}")
    except TelegramError as e:
        await msg.reply_html(f"❌ {e}")

async def _delete(update, context):
    msg = update.effective_message
    try:
        await msg.delete()
        if msg.reply_to_message:
            await msg.reply_to_message.delete()
    except Exception: pass

async def _help(update):
    await update.effective_message.reply_html(
        f"🛡️ <b>{sc('Admin Commands')} (. or !)</b>\n\n"
        f"<code>.warns</code> [user] — {sc('All warnings')}\n"
        f"<code>.warn</code> [user] [reason] — {sc('Warn')} (3={sc('ban')})\n"
        f"<code>.unwarn</code> [user] — {sc('Remove 1 warning')}\n"
        f"<code>.mute</code> [user] [30m/2h/1d] — {sc('Mute')}\n"
        f"<code>.imute</code> [user] [time] — {sc('Mute Media Only')}\n"
        f"<code>.dmute</code> [reply] [time] — {sc('Delete + Mute')}\n"
        f"<code>.unmute</code> [user] — {sc('Unmute')}\n"
        f"<code>.ban</code> [user] [reason] — {sc('Ban')}\n"
        f"<code>.dban</code> [reply] — {sc('Delete + Ban')}\n"
        f"<code>.unban</code> [user] — {sc('Unban')}\n"
        f"<code>.kick</code> [user] — {sc('Kick')}\n"
        f"<code>.promote</code> [user] 0/1/2/3\n"
        f"  0={sc('Junior')} 1={sc('Admin')} 2={sc('Senior')} 3={sc('Full')}\n"
        f"<code>.demote</code> [user]\n"
        f"<code>.demote_all</code>\n"
        f"<code>.add</code> [user] power\n"
        f"<code>.remove</code> [user] power\n"
        f"<code>.title</code> [user] title\n"
        f"<code>.pin</code> [reply] — {sc('Pin')}\n"
        f"<code>.unpin</code> — {sc('Unpin')}\n"
        f"<code>.d</code> — {sc('Delete')}\n\n"
        f"{sc('Powers')}: manage|delete|restrict|invite|pin|info|promote|video"
    )
