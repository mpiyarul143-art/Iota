"""
╔════════════════════════════════════════════════════════════════════════╗
║  IOTA — Extended Owner Systems                                        ║
║  Group ops · bot profile · diagnostics · data tools · moderation.       ║
║  Every command is wrapped in @owner_only (owner-only + crash-proof)     ║
║  and all Telegram network calls go through utils.telegram_safe so a     ║
║  flaky send can never surface as a "crashed!" report.                   ║
╚════════════════════════════════════════════════════════════════════════╝
"""
import asyncio
import io
import logging
import os
import platform
import sys
import time
from collections import deque

from telegram import Update, InputFile, BotCommand
from telegram.ext import ContextTypes
from telegram.error import TelegramError

from utils.mongo_db import (
    get_db, get_all_groups, get_user, update_user,
    total_users, get_broadcastable_users, set_group_inactive, update_prot,
)
from utils.helpers import mention, mention_owner, fmt
from utils.safe_html import safe_html
from utils.fonts import sc
from handlers.owner_panel import owner_only
from utils.telegram_safe import safe_call

logger = logging.getLogger(__name__)

START_TIME = time.time()

# ── In-memory rolling log buffer (for /logs) ────────────────────────────────
_log_buf = deque(maxlen=800)


class _LogCapture(logging.Handler):
    def emit(self, record):
        try:
            _log_buf.append(self.format(record))
        except Exception:
            pass


_cap = _LogCapture()
_cap.setLevel(logging.WARNING)
if not any(isinstance(h, _LogCapture) for h in logging.getLogger().handlers):
    logging.getLogger().addHandler(_cap)


# ═════════════════════════════════════════════════════════════════════════
#  GROUP / NETWORK OPERATIONS
# ═════════════════════════════════════════════════════════════════════════

@owner_only
async def leavegroup_cmd(update, context):
    """Owner: make the bot leave a specific group. /leavegroup <chat_id>"""
    if not context.args:
        await safe_call(lambda: update.message.reply_html(
            "🚪 Usage: /leavegroup &lt;chat_id&gt;"))
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        await safe_call(lambda: update.message.reply_html("❌ chat_id must be a number."))
        return
    ok = await safe_call(lambda: context.bot.leave_chat(cid), label="leavegroup")
    await set_group_inactive(cid)
    if ok:
        await safe_call(lambda: update.message.reply_html(f"🚪 Left group <code>{cid}</code>."))
    else:
        await safe_call(lambda: update.message.reply_html(
            f"⚠️ Couldn't leave <code>{cid}</code> (not a member / no access)."))


@owner_only
async def leaveallgroups_cmd(update, context):
    """Owner: leave EVERY group the bot is in. /leaveallgroups confirm"""
    if not context.args or context.args[0].lower() != "confirm":
        await safe_call(lambda: update.message.reply_html(
            "⚠️ This leaves ALL groups!\nRun: <code>/leaveallgroups confirm</code>"))
        return
    groups = await get_all_groups()
    left = 0
    for g in groups:
        cid = g["_id"]
        ok = await safe_call(lambda: context.bot.leave_chat(cid), label="leaveall")
        await set_group_inactive(cid)
        if ok:
            left += 1
        await asyncio.sleep(0.3)
    await safe_call(lambda: update.message.reply_html(
        f"🚪 Left <b>{left}</b> / {len(groups)} groups."))


@owner_only
async def groupslist_cmd(update, context):
    """Owner: list tracked groups with title + member count."""
    groups = await get_all_groups()
    if not groups:
        await safe_call(lambda: update.message.reply_html("📭 No tracked groups."))
        return
    lines = []
    for g in groups[:50]:
        cid = g["_id"]
        try:
            chat = await context.bot.get_chat(cid)
            title = (chat.title or chat.username or f"chat {cid}")[:40]
            cnt = getattr(chat, "member_count", None)
            cnt_s = f" · {fmt(cnt)} 👥" if cnt else ""
            lines.append(f"• <code>{cid}</code> — {safe_html(title)}{cnt_s}")
        except Exception:
            lines.append(f"• <code>{cid}</code> — (unreachable)")
    text = f"📋 <b>Tracked groups ({len(groups)})</b>\n\n" + "\n".join(lines)
    if len(groups) > 50:
        text += f"\n\n…and {len(groups) - 50} more."
    await safe_call(lambda: update.message.reply_html(text))


@owner_only
async def groupscount_cmd(update, context):
    """Owner: how many groups / users the bot reaches."""
    groups = await get_all_groups()
    users = await total_users()
    await safe_call(lambda: update.message.reply_html(
        f"📊 <b>Reach</b>\n\n"
        f"👥 Groups: <b>{len(groups)}</b>\n"
        f"👤 Users: <b>{fmt(users)}</b>"))


@owner_only
async def chatinfo_cmd(update, context):
    """Owner: inspect any chat/group. /chatinfo <chat_id>"""
    cid = None
    if context.args:
        try:
            cid = int(context.args[0])
        except ValueError:
            pass
    if cid is None and update.effective_chat.type != "private":
        cid = update.effective_chat.id
    if cid is None:
        await safe_call(lambda: update.message.reply_html(
            "❌ Usage: /chatinfo &lt;chat_id&gt;"))
        return
    try:
        chat = await context.bot.get_chat(cid)
    except Exception as e:
        await safe_call(lambda: update.message.reply_html(
            f"❌ Couldn't fetch chat: <code>{safe_html(str(e))}</code>"))
        return
    text = (
        f"🔎 <b>Chat Info</b>\n\n"
        f"🆔 ID: <code>{chat.id}</code>\n"
        f"📛 Title: {safe_html(chat.title or chat.username or '—')}\n"
        f"🏷️ Type: {safe_html(chat.type)}\n"
        f"👥 Members: {fmt(getattr(chat, 'member_count', 0))}\n"
        f"🔗 Username: @{safe_html(chat.username or 'none')}\n"
        f"📝 Description: {safe_html((chat.description or '—')[:300])}"
    )
    await safe_call(lambda: update.message.reply_html(text))


@owner_only
async def osetrules_cmd(update, context):
    """Owner: set a group's rules. /osetrules <chat_id> <text>"""
    if len(context.args) < 2:
        await safe_call(lambda: update.message.reply_html(
            "📜 Usage: /osetrules &lt;chat_id&gt; &lt;text&gt;"))
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        await safe_call(lambda: update.message.reply_html("❌ chat_id must be a number."))
        return
    rules = " ".join(context.args[1:])
    await get_db().group_settings.update_one(
        {"_id": cid}, {"$set": {"rules": rules}}, upsert=True)
    await safe_call(lambda: update.message.reply_html(
        f"📜 Rules set for <code>{cid}</code>:\n\n{safe_html(rules)}"))


@owner_only
async def antispam_cmd(update, context):
    """Owner: toggle anti-spam for a group. /antispam <chat_id> on|off"""
    if len(context.args) < 2:
        await safe_call(lambda: update.message.reply_html(
            "🛡️ Usage: /antispam &lt;chat_id&gt; on|off"))
        return
    try:
        cid = int(context.args[0])
    except ValueError:
        await safe_call(lambda: update.message.reply_html("❌ chat_id must be a number."))
        return
    val = context.args[1].lower() in ("on", "true", "1", "yes")
    await update_prot(cid, anti_spam=val)
    await safe_call(lambda: update.message.reply_html(
        f"🛡️ Anti-spam for <code>{cid}</code>: <b>{'ON' if val else 'OFF'}</b>"))


@owner_only
async def cleandb_cmd(update, context):
    """Owner: drop groups the bot has left from the tracker."""
    res = await get_db().group_settings.delete_many({"active": False})
    await safe_call(lambda: update.message.reply_html(
        f"🧹 Removed <b>{res.deleted_count}</b> inactive groups from the tracker."))


# ═════════════════════════════════════════════════════════════════════════
#  USER / DATA TOOLS
# ═════════════════════════════════════════════════════════════════════════

@owner_only
async def userinfo_cmd(update, context):
    """Owner: detailed view of any user. /userinfo <user_id>"""
    if not context.args:
        await safe_call(lambda: update.message.reply_html(
            "👤 Usage: /userinfo &lt;user_id&gt;"))
        return
    try:
        uid = int(context.args[0])
    except ValueError:
        await safe_call(lambda: update.message.reply_html("❌ user_id must be a number."))
        return
    d = await get_user(uid)
    if not d:
        await safe_call(lambda: update.message.reply_html(f"❌ No user <code>{uid}</code>."))
        return
    text = (
        f"👤 <b>User Info — {safe_html(d.get('full_name', '?'))}</b>\n\n"
        f"🆔 ID: <code>{uid}</code>\n"
        f"🔖 Username: @{safe_html(d.get('username', 'none'))}\n"
        f"💰 Balance: {fmt(d.get('balance', 0))}\n"
        f"💎 Gems: {d.get('gems', 0)}\n"
        f"💓 Premium: {d.get('is_premium', False)}\n"
        f"🚫 Banned: {d.get('is_banned', False)}\n"
        f"💀 Kills: {d.get('kills', 0)} | 🔫 Robs: {d.get('robs', 0)}\n"
        f"⚡ XP: {d.get('xp', 0)} | 🏅 Level: {d.get('level', 1)}"
    )
    await safe_call(lambda: update.message.reply_html(text))


@owner_only
async def exportusers_cmd(update, context):
    """Owner: export all user ids (and names) as a .txt document."""
    cursor = get_db().users.find({}, {"_id": 1, "full_name": 1, "username": 1})
    lines = []
    async for u in cursor:
        uid = u.get("_id")
        name = u.get("full_name") or u.get("username") or ""
        lines.append(f"{uid}\t{name}")
    content = ("Iota user export\n" + "\n".join(lines)).encode("utf-8")
    bio = io.BytesIO(content)
    bio.name = "iota_users.txt"
    sent = await safe_call(
        lambda: context.bot.send_document(
            update.effective_chat.id, document=bio,
            caption=f"📤 {len(lines)} users exported."),
        label="exportusers")
    if sent is None:
        await safe_call(lambda: update.message.reply_html("❌ Export failed to send."))


@owner_only
async def getfile_cmd(update, context):
    """Owner: read a file from the server (restricted to the project dir).
    /getfile <relative/path>"""
    if not context.args:
        await safe_call(lambda: update.message.reply_html(
            "📂 Usage: /getfile &lt;relative/path&gt;"))
        return
    rel = " ".join(context.args)
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    target = os.path.abspath(os.path.join(base, rel))
    # Prevent path traversal outside the project directory.
    if not target.startswith(base + os.sep) and target != base:
        await safe_call(lambda: update.message.reply_html("❌ Path not allowed."))
        return
    if not os.path.isfile(target):
        await safe_call(lambda: update.message.reply_html("❌ File not found."))
        return
    if os.path.getsize(target) > 2_000_000:
        await safe_call(lambda: update.message.reply_html("❌ File too large (>2MB)."))
        return
    try:
        with open(target, "rb") as f:
            data = f.read()
    except Exception as e:
        await safe_call(lambda: update.message.reply_html(
            f"❌ {safe_html(str(e))}"))
        return
    bio = io.BytesIO(data)
    bio.name = os.path.basename(target)
    await safe_call(
        lambda: context.bot.send_document(update.effective_chat.id, document=bio),
        label="getfile")


# ═════════════════════════════════════════════════════════════════════════
#  DIAGNOSTICS
# ═════════════════════════════════════════════════════════════════════════

@owner_only
async def botinfo_cmd(update, context):
    """Owner: bot runtime information."""
    uptime = int(time.time() - START_TIME)
    users = await total_users()
    groups = await get_all_groups()
    text = (
        f"🤖 <b>Iota Runtime</b>\n\n"
        f"⏱️ Uptime: {uptime // 86400}d {(uptime % 86400)//3600}h\n"
        f"🐍 Python: {platform.python_version()}\n"
        f"💻 System: {safe_html(platform.system())} {platform.release()}\n"
        f"👤 Users: {fmt(users)} | 👥 Groups: {len(groups)}\n"
        f"👑 Owner: {mention_owner()}"
    )
    await safe_call(lambda: update.message.reply_html(text))


@owner_only
async def sysinfo_cmd(update, context):
    """Owner: CPU / memory / disk usage."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        cpu = psutil.cpu_percent(interval=0.5)
        text = (
            f"🖥️ <b>System</b>\n\n"
            f"🔥 CPU: {cpu:.1f}%\n"
            f"🧠 RAM: {vm.percent:.1f}% ({fmt(vm.used//(1024**2))}MB / "
            f"{fmt(vm.total//(1024**2))}MB)\n"
            f"💽 Disk: {disk.percent:.1f}% ({fmt(disk.used//(1024**3))}GB / "
            f"{fmt(disk.total//(1024**3))}GB)"
        )
    except Exception as e:
        text = f"⚠️ psutil unavailable: {safe_html(str(e))}"
    await safe_call(lambda: update.message.reply_html(text))


@owner_only
async def logs_cmd(update, context):
    """Owner: tail recent warning/error logs."""
    if not _log_buf:
        await safe_call(lambda: update.message.reply_html(
            "📜 No recent warnings/errors captured."))
        return
    tail = "\n".join(list(_log_buf)[-40:])
    # logs may contain '<'/'>'; escape, then show in a code block
    await safe_call(lambda: update.message.reply_html(
        f"📜 <b>Recent logs (last {len(_log_buf)} entries)</b>\n\n"
        f"<pre>{safe_html(tail)}</pre>"))


@owner_only
async def restart_cmd(update, context):
    """Owner: gracefully restart the bot. /restart confirm"""
    if not context.args or context.args[0].lower() != "confirm":
        await safe_call(lambda: update.message.reply_html(
            "♻️ Restart the bot? Run: <code>/restart confirm</code>"))
        return
    await safe_call(lambda: update.message.reply_html("♻️ Restarting…"))
    logger.warning("Owner requested restart via /restart confirm")
    # Let the message flush, then exit; the process manager (Render/PM2/systemd)
    # will restart the process.
    await asyncio.sleep(1)
    sys.exit(0)


# ═════════════════════════════════════════════════════════════════════════
#  BOT PROFILE
# ═════════════════════════════════════════════════════════════════════════

@owner_only
async def osetbotname_cmd(update, context):
    """Owner: change the bot's display name. /osetbotname <name>"""
    name = " ".join(context.args)
    if not name:
        await safe_call(lambda: update.message.reply_html(
            "🏷️ Usage: /osetbotname &lt;name&gt;"))
        return
    ok = await safe_call(lambda: context.bot.set_my_name(name), label="osetbotname")
    await safe_call(lambda: update.message.reply_html(
        "✅ Bot name updated!" if ok else "❌ Failed to update bot name."))


@owner_only
async def setbotdesc_cmd(update, context):
    """Owner: change the bot's description. /setbotdesc <text>"""
    desc = " ".join(context.args)
    if not desc:
        await safe_call(lambda: update.message.reply_html(
            "📝 Usage: /setbotdesc &lt;text&gt;"))
        return
    ok = await safe_call(lambda: context.bot.set_my_description(desc), label="setbotdesc")
    await safe_call(lambda: update.message.reply_html(
        "✅ Bot description updated!" if ok else "❌ Failed."))


@owner_only
async def setbotpic_cmd(update, context):
    """Owner: set the bot's profile photo (reply to a photo)."""
    msg = update.message
    if not (msg.reply_to_message and msg.reply_to_message.photo):
        await safe_call(lambda: update.message.reply_html(
            "🖼️ Reply to a photo: /setbotpic"))
        return
    try:
        photo = msg.reply_to_message.photo[-1]
        f = await context.bot.get_file(photo.file_id)
        bio = io.BytesIO()
        await f.download_to_memory(bio)
        bio.seek(0)
        ok = await safe_call(
            lambda: context.bot.set_profile_photo(photo=InputFile(bio, filename="pic.png")),
            label="setbotpic")
    except Exception as e:
        ok = None
        logger.warning(f"setbotpic failed: {e}")
    await safe_call(lambda: update.message.reply_html(
        "✅ Profile photo set!" if ok else "❌ Failed to set photo."))


@owner_only
async def setbotcommands_cmd(update, context):
    """Owner: reset the bot's command menu (the / list Telegram shows)."""
    cmds = [
        BotCommand("start", "Start the bot"),
        BotCommand("help", "Show help"),
        BotCommand("voice", "Text to speech"),
        BotCommand("ttssettings", "Voice settings"),
        BotCommand("whisper", "Private whisper"),
        BotCommand("setwelcome", "Welcome settings"),
        BotCommand("ping", "Bot latency"),
        BotCommand("owner", "Contact owner"),
    ]
    ok = await safe_call(
        lambda: context.bot.set_my_commands(cmds), label="setbotcommands")
    await safe_call(lambda: update.message.reply_html(
        "✅ Command menu reset!" if ok else "❌ Failed to set commands."))


# ═════════════════════════════════════════════════════════════════════════
#  MODERATION (in any group)
# ═════════════════════════════════════════════════════════════════════════

@owner_only
async def opurge_cmd(update, context):
    """Owner: delete the last N messages in the current group. /opurge <n>"""
    if not context.args:
        await safe_call(lambda: update.message.reply_html(
            "🧹 Usage: /opurge &lt;n&gt;  (in a group)"))
        return
    try:
        n = int(context.args[0])
    except ValueError:
        await safe_call(lambda: update.message.reply_html("❌ n must be a number."))
        return
    n = max(1, min(n, 100))
    chat = update.effective_chat
    if chat.type == "private":
        await safe_call(lambda: update.message.reply_html("❌ Use in a group."))
        return
    deleted = 0
    try:
        async for msg in context.bot.get_chat_history(chat.id, limit=n + 2):
            if msg.message_id == update.message.message_id:
                continue
            ok = await safe_call(
                lambda: context.bot.delete_message(chat.id, msg.message_id),
                label="opurge.del")
            if ok:
                deleted += 1
            await asyncio.sleep(0.2)
    except Exception as e:
        logger.warning(f"opurge error: {e}")
    await safe_call(lambda: update.message.reply_html(
        f"🧹 Purged <b>{deleted}</b> messages."))
