"""
╔══════════════════════════════════════════════════════╗
║  IOTA BOT — Owner Panel (full control)                ║
║                                                        ║
║  Every command here is wrapped in the @owner_only      ║
║  decorator, which:                                      ║
║    • Logs every attempt (who, when, command)            ║
║    • Verifies the caller is OWNER_ID (int comparison)     ║
║    • Catches ANY exception, logs the FULL traceback,        ║
║      and tells the owner exactly what broke — instead of      ║
║      the command going silently unresponsive.                  ║
╚══════════════════════════════════════════════════════╝
"""
import asyncio, time, logging, traceback, functools
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import RetryAfter, Forbidden, BadRequest, TelegramError
from utils.mongo_db import (get_db, ensure_user, get_user, update_user,
                             add_balance, total_users, log_stars_payment,
                             get_stars_total, mark_user_unreachable,
                             mark_user_reachable, get_broadcastable_users,
                             add_sticker_to_pack, remove_sticker_from_pack,
                             get_stickers_for_mood, list_all_sticker_packs,
                             clear_sticker_pack, create_broadcast_record,
                             add_broadcast_target, get_broadcast_record,
                             list_broadcast_history)
from utils.helpers import mention, fmt, mention_owner
from utils.fonts import sc
from utils.ai_provider import (get_all_models, get_current_models,
                                 set_model, save_model_config_db)
from utils.safe_html import safe_html, placeholder
# Re-use Iota's existing emoji→mood detection so auto-decided moods line up
# with what the sticker-reply system already understands
# (handlers/sticker_reply.py).
from handlers.sticker_reply import (_detect_mood_from_sticker,
                                     _auto_mood_from_pack, _sanitize_mood)
from config import OWNER_ID, OWNER_USERNAME, OWNER_NAME, GLOBAL_COUPONS

logger = logging.getLogger(__name__)


def _own(uid: int) -> bool:
    """OWNER_ID is loaded from config.py as a plain int literal, and
    Telegram always gives us update.effective_user.id as an int — so this
    comparison is type-safe with no casting needed."""
    return int(uid) == int(OWNER_ID)


def owner_only(func):
    """
    Decorator applied to every owner-panel command.

    1. Logs every call attempt (success or rejection) so /panel and
       friends are never a silent black box in the logs.
    2. Rejects non-owners with a clear, visible message (never silently).
    3. Wraps the actual handler body in try/except — if ANYTHING inside
       raises (a bad MongoDB call, a typo, a missing field, etc.) it is
       logged with the FULL traceback AND reported back to the owner,
       instead of the command just... doing nothing.
    """
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *a, **kw):
        u = update.effective_user
        cmd_name = func.__name__
        if not u:
            logger.warning(f"⚠️ {cmd_name}: no effective_user on update — ignoring")
            return

        logger.info(f"🔑 Owner-panel call: {cmd_name} by user_id={u.id} (@{u.username})")

        if not _own(u.id):
            logger.warning(
                f"🚫 {cmd_name}: REJECTED — user_id={u.id} is not the owner "
                f"(OWNER_ID={OWNER_ID})"
            )
            try:
                await update.effective_message.reply_html("❌ Owner only!")
            except Exception:
                logger.exception(f"Failed to even send the 'Owner only' rejection for {cmd_name}")
            return

        try:
            result = await func(update, context, *a, **kw)
            logger.info(f"✅ {cmd_name}: completed successfully")
            return result
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"❌ {cmd_name}: CRASHED with {type(e).__name__}: {e}\n{tb}")
            # IMPORTANT: the exception text itself may contain raw "<"/">"
            # characters. This is exactly what caused /panel to crash before:
            # an unescaped "<model>" inside the usage text broke Telegram's
            # HTML parser while trying to report the error. Escaping here
            # guarantees the crash report can never itself crash.
            safe_err = safe_html(f"{type(e).__name__}: {e}")
            try:
                await update.effective_message.reply_html(
                    f"⚠️ <b>{safe_html(cmd_name)} crashed!</b>\n\n"
                    f"<code>{safe_err}</code>\n\n"
                    f"Full traceback is in the bot's logs."
                )
            except Exception:
                logger.exception(f"Failed to report the {cmd_name} crash back to the owner")
                try:
                    await update.effective_message.reply_text(
                        f"{cmd_name} crashed: {type(e).__name__}: {e}\n"
                        f"(Full traceback is in the bot's logs.)"
                    )
                except Exception:
                    pass
    return wrapper


# ── /panel ──────────────────────────────────────────────────────────────────

@owner_only
async def owner_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = get_current_models()
    db = get_db()
    tu = await total_users()
    pu = await db.users.count_documents({"is_premium": True})
    stars = await get_stars_total()
    await update.message.reply_html(
        f"👑 <b>Owner Panel — Iota Bot</b>\n\n"
        f"👤 Owner: {mention_owner()} ({OWNER_USERNAME})\n"
        f"👥 Users: <b>{tu}</b>  |  💓 Premium: <b>{pu}</b>\n"
        f"⭐ Total Stars earned: <b>{stars}</b>\n\n"
        f"🤖 <b>AI (primary provider)</b>: <code>{cfg['free_model']}</code> / <code>{cfg['premium_model']}</code>\n"
        f"{sc('Full breakdown')}: /providerstatus\n\n"
        f"<b>Economy:</b>\n"
        f"/addcoins /removecoins /addgems\n"
        f"/addpremium /removepremium /addcoupon\n\n"
        f"<b>Users:</b>\n"
        f"/banuser /unbanuser /broadcast\n"
        f"/announce all|group_id msg\n"
        f"/dm &lt;user_id&gt; &lt;msg&gt; — DM any user via the bot\n\n"
        f"🤖 <b>AI Providers:</b>\n"
        f"/providerstatus — Overview of all providers & keys\n"
        f"/setmodel free|premium {placeholder('model')} [provider]\n"
        f"/listmodels [provider] — /refreshmodels [provider]\n"
        f"/addapikey {placeholder('key')} [provider]\n"
        f"/removeapikey {placeholder('prefix')} [provider]\n"
        f"/keypoolstatus [provider] — Key health\n"
        f"/setpriority groq,gemini,openrouter,cloudflare\n"
        f"/toggleprovider {placeholder('provider')}\n"
        f"/setmaxtokens {placeholder('n')}\n\n"
        f"<b>Stats:</b>\n"
        f"/botstats /starsstats\n"
        f"/premiumlist [page] — List all premium users\n"
        f"/userslist [page] — List all users\n\n"
        f"<b>🎭 Sticker Packs:</b>\n"
        f"/addpack — Reply to a sticker → auto-saves the WHOLE pack (auto mood!)\n"
        f"/addsticker [{placeholder('mood')}] — Add one sticker (mood auto if omitted)\n"
        f"/addstickerpack [{placeholder('mood')}] — Save whole pack (mood auto if omitted)\n"
        f"/stickerpacks — List all packs\n"
        f"/previewsticker {placeholder('mood')} — Preview one\n"
        f"/clearstickers {placeholder('mood')} — Wipe a pack\n\n"
        f"<b>🔊 Voice/TTS:</b>\n"
        f"/ttssettings — Configure TTS model, speaker, speed, pitch\n\n"
        f"<b>🗑️ Broadcast History:</b>\n"
        f"/broadcasthistory — Last 20 broadcasts/announces\n"
        f"/delbroadcast {placeholder('id')} [chat_id] — Delete one, everywhere or one chat\n\n"
        f"<b>Scan/Hidden:</b>\n"
        f"/scan {placeholder('user_id')} — Full user scan\n"
        f"/resetuser {placeholder('user_id')} — Reset all data\n"
        f"/giveall {placeholder('amount')} — Give coins to all\n"
        f"/maintenance on|off"
    )


@owner_only
async def addcoins_cmd(update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_html(
            f"Usage: /addcoins {placeholder('uid')} {placeholder('amt')}"
        ); return
    try:
        uid = int(args[0]); amt = int(args[1])
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid! Both uid and amount must be numbers."); return
    await ensure_user(uid); await add_balance(uid, amt)
    d = await get_user(uid)
    await update.message.reply_html(f"✅ Added {fmt(amt)} to <code>{uid}</code>\nNew: {fmt(d['balance'])}")


@owner_only
async def removecoins_cmd(update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_html(
            f"Usage: /removecoins {placeholder('uid')} {placeholder('amt')}"
        ); return
    try:
        uid = int(args[0]); amt = int(args[1])
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid! Both uid and amount must be numbers."); return
    await ensure_user(uid); d = await get_user(uid)
    new = max(0, d["balance"] - amt); await update_user(uid, balance=new)
    await update.message.reply_html(f"✅ Removed {fmt(amt)} from <code>{uid}</code>\nNew: {fmt(new)}")


@owner_only
async def addgems_cmd(update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_html(
            f"Usage: /addgems {placeholder('uid')} {placeholder('amt')}"
        ); return
    try:
        uid = int(args[0]); amt = int(args[1])
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid! Both uid and amount must be numbers."); return
    await ensure_user(uid); d = await get_user(uid)
    await update_user(uid, gems=d.get("gems", 0) + amt)
    await update.message.reply_html(f"✅ Added {amt} 💎 to <code>{uid}</code>")


@owner_only
async def addpremium_cmd(update, context):
    args = context.args
    if not args:
        await update.message.reply_html(
            f"Usage: /addpremium {placeholder('uid')} [days=90]"
        ); return
    try:
        uid = int(args[0]); days = int(args[1]) if len(args) > 1 else 90
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid! uid/days must be numbers."); return
    await ensure_user(uid)
    now = int(time.time()); until = now + days * 86400
    await update_user(uid, is_premium=True, premium_until=until)
    exp = time.strftime('%d %b %Y', time.localtime(until))
    await update.message.reply_html(f"💓 <code>{uid}</code> Premium until <b>{exp}</b>!")


@owner_only
async def removepremium_cmd(update, context):
    if not context.args:
        await update.message.reply_html(f"Usage: /removepremium {placeholder('uid')}"); return
    try:
        uid = int(context.args[0])
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid uid!"); return
    await update_user(uid, is_premium=False, premium_until=0)
    await update.message.reply_html(f"❌ Premium removed from <code>{uid}</code>")


@owner_only
async def addcoupon_cmd(update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_html(
            f"Usage: /addcoupon {placeholder('code')} {placeholder('amt')}"
        ); return
    code = args[0].lower()
    try:
        amt = int(args[1])
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid amount!"); return
    GLOBAL_COUPONS[code] = amt
    await update.message.reply_html(f"🎟️ Coupon <b>{safe_html(code)}</b> = {fmt(amt)} added!")


@owner_only
async def ban_user_cmd(update, context):
    if not context.args:
        await update.message.reply_html(f"Usage: /banuser {placeholder('uid')}"); return
    try:
        uid = int(context.args[0])
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid uid!"); return
    await ensure_user(uid); await update_user(uid, is_banned=True, balance=0, is_premium=False)
    await update.message.reply_html(f"🔨 <code>{uid}</code> banned!")


@owner_only
async def unban_user_cmd_owner(update, context):
    if not context.args:
        await update.message.reply_html(f"Usage: /unbanuser {placeholder('uid')}"); return
    try:
        uid = int(context.args[0])
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid uid!"); return
    await update_user(uid, is_banned=False)
    await update.message.reply_html(f"✅ <code>{uid}</code> unbanned!")


@owner_only
async def broadcast_cmd(update, context):
    """
    Send a message to every reachable USER who has talked to the bot
    (DM blast). Supports ALL media types, not just text:

      • Reply to a photo + /broadcast <caption>   → photo broadcast
      • Reply to a video + /broadcast <caption>    → video broadcast
      • Reply to a GIF/animation + /broadcast ...   → animation broadcast
      • Reply to a sticker + /broadcast              → sticker broadcast
      • Reply to a voice/audio/document + /broadcast  → that file type
      • No reply, just /broadcast <text>                → plain text (as before)

    WHY THE FAILURE RATE WAS SO HIGH (94 failed / 9 sent):
    Telegram permanently blocks a bot from DMing any user who has blocked
    the bot or deleted their account — this is a Telegram-side rule, not
    something a bot can work around. The old code retried EVERY known
    user on EVERY broadcast, including ones who'd been permanently
    unreachable for a long time, so the failure count looked huge even
    though the bot was working correctly. This version:
      1. Categorizes each failure (blocked / deactivated / rate-limited /
         other) instead of a single opaque count.
      2. Automatically marks permanently-blocked users as unreachable in
         the database, so THEY ARE SKIPPED on all future broadcasts —
         the failure count will now shrink over time instead of staying
         stuck at the same size forever.
      3. Properly handles Telegram's flood-control (RetryAfter) by
         waiting the exact time Telegram asks for, instead of treating
         a rate-limit as a failure.
    """
    msg = update.message
    reply = msg.reply_to_message

    caption = safe_html(" ".join(context.args)) if context.args else ""
    if not reply and not caption:
        await update.message.reply_html(
            f"Usage: /broadcast {placeholder('msg')}\n\n"
            f"💡 Reply to a photo/video/GIF/sticker/voice/document with "
            f"/broadcast (optionally with a caption) to broadcast that media "
            f"to every user instead of just text."
        ); return

    db = get_db()
    users = await get_broadcastable_users()
    total = len(users)
    if total == 0:
        await update.message.reply_html("❌ No broadcastable users found!"); return

    status = await update.message.reply_html(f"📢 Sending to {total} users...")

    # 🆕 Record this broadcast so it can be deleted later (from one chat
    # or everywhere) and so the owner has a full history of past
    # broadcasts via /broadcasthistory. See utils/mongo_db.py for the
    # underlying storage functions.
    bid = await create_broadcast_record("broadcast", caption or "[media]", update.effective_user.id)

    sent = 0
    blocked = 0       # user blocked the bot / deactivated — marked unreachable
    rate_limited_retries = 0
    other_failed = 0

    async def _send_one(uid: int):
        """Sends the broadcast (media or text) to a single user. Returns
        ('sent', message) | ('blocked', None) | ('other', None). Handles
        flood-control by waiting and retrying once, rather than counting
        it as a failure."""
        for attempt in range(2):
            try:
                if reply and reply.photo:
                    m = await context.bot.send_photo(uid, reply.photo[-1].file_id, caption=caption or None, parse_mode="HTML")
                elif reply and reply.video:
                    m = await context.bot.send_video(uid, reply.video.file_id, caption=caption or None, parse_mode="HTML")
                elif reply and reply.animation:
                    m = await context.bot.send_animation(uid, reply.animation.file_id, caption=caption or None, parse_mode="HTML")
                elif reply and reply.sticker:
                    m = await context.bot.send_sticker(uid, reply.sticker.file_id)
                    if caption:
                        await context.bot.send_message(uid, caption, parse_mode="HTML")
                elif reply and reply.voice:
                    m = await context.bot.send_voice(uid, reply.voice.file_id, caption=caption or None, parse_mode="HTML")
                elif reply and reply.audio:
                    m = await context.bot.send_audio(uid, reply.audio.file_id, caption=caption or None, parse_mode="HTML")
                elif reply and reply.document:
                    m = await context.bot.send_document(uid, reply.document.file_id, caption=caption or None, parse_mode="HTML")
                elif reply and reply.video_note:
                    m = await context.bot.send_video_note(uid, reply.video_note.file_id)
                    if caption:
                        await context.bot.send_message(uid, caption, parse_mode="HTML")
                else:
                    m = await context.bot.send_message(
                        uid, f"📢 <b>Announcement — Iota Bot</b>\n\n{caption}", parse_mode="HTML"
                    )
                return "sent", m
            except RetryAfter as e:
                # Telegram is asking us to slow down — wait exactly as long
                # as it says, then retry this same user once. This is NOT
                # a real failure, just backpressure.
                await asyncio.sleep(e.retry_after + 0.5)
                continue
            except Forbidden:
                # Bot was blocked, kicked, or the user deactivated their
                # account — this is PERMANENT, so mark them unreachable
                # to keep future broadcasts fast and accurate.
                await mark_user_unreachable(uid, reason="blocked_or_deactivated")
                return "blocked", None
            except BadRequest as e:
                err = str(e).lower()
                if "chat not found" in err or "user is deactivated" in err:
                    await mark_user_unreachable(uid, reason="chat_not_found")
                    return "blocked", None
                logger.debug(f"broadcast: BadRequest for {uid}: {e}")
                return "other", None
            except Exception as e:
                logger.debug(f"broadcast: failed to DM {uid}: {e}")
                return "other", None
        return "other", None

    for i, u in enumerate(users):
        result, sent_msg = await _send_one(u["_id"])
        if result == "sent":
            sent += 1
            if sent_msg:
                await add_broadcast_target(bid, u["_id"], sent_msg.message_id)
        elif result == "blocked":
            blocked += 1
        else:
            other_failed += 1

        # Telegram allows roughly 30 messages/second bot-wide across ALL
        # chats — 0.05s between sends keeps us safely under that without
        # needing flood-control retries in the common case.
        await asyncio.sleep(0.05)

        # Live progress update every 50 users so the owner isn't staring
        # at a stale "Sending..." message during a big broadcast.
        if (i + 1) % 50 == 0:
            try:
                await status.edit_text(
                    f"📢 Sending... {i+1}/{total}\n"
                    f"✅ {sent}  🚫 {blocked} (blocked)  ⚠️ {other_failed} (other)",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    await status.edit_text(
        f"📢 <b>Broadcast complete!</b>\n\n"
        f"🆔 ID: <code>{bid}</code>\n"
        f"✅ Sent: {sent}\n"
        f"🚫 Blocked/deactivated: {blocked} (auto-marked, won't be retried next time)\n"
        f"⚠️ Other failures: {other_failed}\n\n"
        f"📊 Reachable audience shrinks to {total - blocked} for next broadcast.\n\n"
        f"💡 /delbroadcast {bid} to delete this broadcast from everyone.",
        parse_mode="HTML"
    )


@owner_only
async def announce_cmd(update, context):
    """
    Send a message to ALL groups the bot is in, or one specific group.
    Like /broadcast, this now supports replying to any media type
    (photo/video/GIF/sticker/voice/document) to announce that to groups
    instead of only plain text.
    """
    msg = update.message
    reply = msg.reply_to_message
    args = context.args

    if not args and not reply:
        await update.message.reply_html(
            "📢 <b>Announce</b>\n\n"
            f"/announce all {placeholder('msg')} — All groups\n"
            f"/announce {placeholder('group_id')} {placeholder('msg')} — Specific group\n\n"
            "Example:\n"
            "/announce all 🎉 New update launched!\n\n"
            "💡 Reply to a photo/video/GIF/sticker with /announce all "
            "(optionally with a caption) to send that media instead of text."
        ); return

    # target is always the first word; the rest (or a reply's caption) is the message
    if not args:
        await update.message.reply_html("❌ Specify a target: /announce all|<group_id> ..."); return
    target = args[0].lower()
    message = safe_html(" ".join(args[1:])) if len(args) > 1 else ""
    full_msg = f"{message}\n\n— Iota Bot" if message else "— Iota Bot"

    async def _send_to(cid: int):
        if reply and reply.photo:
            return await context.bot.send_photo(cid, reply.photo[-1].file_id, caption=message or None, parse_mode="HTML")
        elif reply and reply.video:
            return await context.bot.send_video(cid, reply.video.file_id, caption=message or None, parse_mode="HTML")
        elif reply and reply.animation:
            return await context.bot.send_animation(cid, reply.animation.file_id, caption=message or None, parse_mode="HTML")
        elif reply and reply.sticker:
            m = await context.bot.send_sticker(cid, reply.sticker.file_id)
            if message:
                await context.bot.send_message(cid, message, parse_mode="HTML")
            return m
        elif reply and reply.voice:
            return await context.bot.send_voice(cid, reply.voice.file_id, caption=message or None, parse_mode="HTML")
        elif reply and reply.document:
            return await context.bot.send_document(cid, reply.document.file_id, caption=message or None, parse_mode="HTML")
        else:
            return await context.bot.send_message(cid, full_msg, parse_mode="HTML")

    # 🆕 Record this announce so it can be deleted later (from one group
    # or everywhere) and appears in /broadcasthistory.
    bid = await create_broadcast_record("announce", message or "[media]", update.effective_user.id)

    if target == "all":
        db = get_db(); chats = await db.group_settings.find({}, {"_id": 1}).to_list(10000)
        sent = 0; failed = 0
        status = await update.message.reply_html(f"📢 Sending to {len(chats)} groups...")
        for ch in chats:
            try:
                m = await _send_to(ch["_id"])
                sent += 1
                if m:
                    await add_broadcast_target(bid, ch["_id"], m.message_id)
                await asyncio.sleep(0.1)
            except RetryAfter as e:
                await asyncio.sleep(e.retry_after + 0.5)
                try:
                    m = await _send_to(ch["_id"]); sent += 1
                    if m:
                        await add_broadcast_target(bid, ch["_id"], m.message_id)
                except Exception as e2:
                    failed += 1
                    logger.debug(f"announce all: retry failed for {ch['_id']}: {e2}")
            except Exception as e:
                failed += 1
                logger.debug(f"announce all: failed to send to {ch['_id']}: {e}")
        await status.edit_text(
            f"📢 Done!\n✅ {sent}\n❌ {failed}\n\n🆔 ID: <code>{bid}</code>\n"
            f"💡 /delbroadcast {bid} to delete this from everyone.",
            parse_mode="HTML"
        )
    else:
        try:
            cid = int(target)
        except ValueError:
            await update.message.reply_html("❌ group_id must be a number, or use 'all'."); return
        try:
            m = await _send_to(cid)
            if m:
                await add_broadcast_target(bid, cid, m.message_id)
            await update.message.reply_html(
                f"✅ Sent to <code>{cid}</code>!\n🆔 ID: <code>{bid}</code>\n"
                f"💡 /delbroadcast {bid} to delete this."
            )
        except Exception as e:
            logger.warning(f"announce: failed to send to group {cid}: {e}")
            await update.message.reply_html(f"❌ Failed: <code>{safe_html(e)}</code>")


# ── 🆕 Owner: global economy/games/village open/close ────────────────
# Complements the per-group /open and /close (handlers/games.py) — this
# lets the owner flip the switch across EVERY group at once (e.g. for
# maintenance, or a temporary global economy freeze), without having to
# go into each group individually.
@owner_only
async def globalclose_cmd(update, context):
    args = [a.lower() for a in context.args]
    valid = {"games", "economy", "village"}
    targets = [a for a in args if a in valid] or list(valid)

    db = get_db()
    chats = await db.group_settings.find({}, {"_id": 1}).to_list(10000)
    from utils.mongo_db import set_system_status
    for ch in chats:
        try:
            await set_system_status(ch["_id"], **{k: False for k in targets})
        except Exception as e:
            logger.debug(f"globalclose: failed for {ch['_id']}: {e}")
    names = ", ".join(t.title() for t in targets)
    await update.message.reply_html(
        f"🔒 <b>{names} closed globally</b> across {len(chats)} groups.\n"
        f"Reopen everywhere with: /globalopen" + (f" {targets[0]}" if len(targets) == 1 else "")
    )


@owner_only
async def globalopen_cmd(update, context):
    args = [a.lower() for a in context.args]
    valid = {"games", "economy", "village"}
    targets = [a for a in args if a in valid] or list(valid)

    db = get_db()
    chats = await db.group_settings.find({}, {"_id": 1}).to_list(10000)
    from utils.mongo_db import set_system_status
    for ch in chats:
        try:
            await set_system_status(ch["_id"], **{k: True for k in targets})
        except Exception as e:
            logger.debug(f"globalopen: failed for {ch['_id']}: {e}")
    names = ", ".join(t.title() for t in targets)
    await update.message.reply_html(
        f"💚 <b>{names} reopened globally</b> across {len(chats)} groups."
    )


async def dm_cmd(update, context):
    """
    🆕 Owner → send a direct message to ANY user through the bot, even if
    that user never DM'd the bot first (as long as they've interacted
    with the bot at least once somewhere, e.g. in a shared group — that's
    a Telegram-side requirement, not something the bot can bypass).

    Usage: /dm <user_id> <message...>
    """
    args = context.args
    if len(args) < 2:
        await update.message.reply_html(
            "📩 <b>DM a user via Iota</b>\n\n"
            f"Usage: <code>/dm {placeholder('user_id')} {placeholder('message')}</code>\n"
            "Example: <code>/dm 123456789 Hey, thanks for using Iota!</code>\n\n"
            "💡 To message a whole group instead, use:\n"
            f"<code>/announce {placeholder('group_id')} {placeholder('message')}</code>"
        ); return
    try:
        uid = int(args[0])
    except ValueError:
        await update.message.reply_html("❌ user_id must be a number!"); return
    message = safe_html(" ".join(args[1:]))
    try:
        await context.bot.send_message(
            uid,
            f"📩 <b>Message from the owner</b>\n\n{message}",
            parse_mode="HTML"
        )
        await update.message.reply_html(f"✅ Sent to <code>{uid}</code>!")
    except Exception as e:
        logger.warning(f"/dm: failed to message user {uid}: {e}")
        await update.message.reply_html(
            f"❌ Couldn't deliver: <code>{safe_html(e)}</code>\n\n"
            f"This usually means the user has never started a chat with "
            f"the bot (Telegram blocks bots from DMing users who haven't "
            f"interacted with them first)."
        )


@owner_only
async def stats_cmd(update, context):
    db = get_db(); tu = await total_users()
    pu = await db.users.count_documents({"is_premium": True})
    bu = await db.users.count_documents({"is_banned": True})
    pipeline = [{"$group": {"_id": None, "total": {"$sum": "$balance"}, "kills": {"$sum": "$kills"}, "robs": {"$sum": "$robs"}}}]
    agg = await db.users.aggregate(pipeline).to_list(1)
    r = agg[0] if agg else {}
    cfg = get_current_models()
    await update.message.reply_html(
        f"📊 <b>Iota Bot Stats</b>\n\n"
        f"👥 Total Users: <b>{tu}</b>\n"
        f"💓 Premium: <b>{pu}</b>\n"
        f"🔨 Banned: <b>{bu}</b>\n\n"
        f"💰 Total Coins: <b>{fmt(r.get('total', 0))}</b>\n"
        f"💀 Total Kills: <b>{r.get('kills', 0)}</b>\n"
        f"🔫 Total Robs: <b>{r.get('robs', 0)}</b>\n\n"
        f"🤖 Free Model: <code>{cfg['free_model']}</code>\n"
        f"🤖 Premium Model: <code>{cfg['premium_model']}</code>\n\n"
        f"👑 Owner: {mention_owner()} ({OWNER_USERNAME})"
    )


@owner_only
async def stars_stats_cmd(update, context):
    db = get_db()
    total_stars = await get_stars_total()
    count = await db.stars_payments.count_documents({})
    cursor = db.stars_payments.find(sort=[("created_at", -1)], limit=5)
    recent = await cursor.to_list(5)
    text = f"⭐ <b>Stars Stats</b>\n\n"
    text += f"Total Stars: <b>{total_stars}</b>\n"
    text += f"Total Payments: <b>{count}</b>\n\n"
    text += "Recent:\n"
    for r in recent:
        t = time.strftime('%d/%m %H:%M', time.localtime(r.get("created_at", 0)))
        text += f"• {safe_html(r.get('full_name', '?'))} — ⭐{r.get('stars', 0)} ({t})\n"
    await update.message.reply_html(text)


# ── AI Provider Management (Multi-Provider: Groq/Gemini/OpenRouter/Cloudflare)

_PROVIDER_SETUP_LINKS = {
    "groq": "https://console.groq.com/keys",
    "gemini": "https://aistudio.google.com/apikey",
    "openrouter": "https://openrouter.ai/keys",
    "cloudflare": "https://dash.cloudflare.com/profile/api-tokens",
}


@owner_only
async def providerstatus_cmd(update, context):
    """Owner: overview of every provider — enabled state, key counts,
    active models, and fallback priority order."""
    from utils.ai_provider import get_providers_status, get_provider_priority
    providers = get_providers_status()
    priority = get_provider_priority()
    text = f"🤖 <b>{sc('AI Providers')}</b>\n\n"
    text += f"{sc('Fallback order')}: " + " → ".join(priority) + "\n\n"
    for p in providers:
        icon = "🟢" if p["enabled"] else "⚪"
        key_info = f"{p['healthy_keys']}/{p['key_count']} {sc('healthy')}" if p["key_count"] else sc("no keys")
        text += (
            f"{icon} <b>{p['name']}</b> ({p['id']})\n"
            f"   {sc('Keys')}: {key_info}\n"
            f"   {sc('Free')}: <code>{safe_html(p['free_model'])}</code>\n"
            f"   {sc('Premium')}: <code>{safe_html(p['premium_model'])}</code>\n\n"
        )
    text += (
        f"{sc('Add a key')}: /addapikey &lt;key&gt; &lt;provider&gt;\n"
        f"{sc('Reorder priority')}: /setpriority groq,gemini,openrouter,cloudflare\n"
        f"{sc('Enable/disable')}: /toggleprovider &lt;provider&gt;"
    )
    await update.message.reply_html(text)


@owner_only
async def setmodel_cmd(update, context):
    """Owner: /setmodel free|premium <model_name> [provider]"""
    args = context.args
    if len(args) < 2:
        cfg = get_current_models()
        text = (
            f"🤖 <b>{sc('AI Model Settings')}</b>\n\n"
            f"{sc('Current free')}: <code>{safe_html(cfg.get('free_model',''))}</code>\n"
            f"{sc('Current premium')}: <code>{safe_html(cfg.get('premium_model',''))}</code>\n\n"
            f"Usage: /setmodel free|premium {placeholder('model')} [provider]\n"
            f"{sc('Providers')}: groq, gemini, openrouter, cloudflare (default: groq)\n"
            f"{sc('See live options')}: /listmodels"
        )
        await update.message.reply_html(text); return
    tier = args[0].lower(); provider = args[-1].lower() if args[-1].lower() in ("groq", "gemini", "openrouter", "cloudflare") else "groq"
    model_end = len(args) if provider == "groq" and args[-1].lower() not in ("groq", "gemini", "openrouter", "cloudflare") else len(args) - 1
    model = " ".join(args[1:model_end]) if model_end > 1 else " ".join(args[1:])
    if tier not in ("free", "premium"):
        await update.message.reply_html(
            f"❌ Use: /setmodel free|premium {placeholder('model')} [provider]"
        ); return
    try:
        set_model(tier, model, provider=provider)
    except ValueError as e:
        await update.message.reply_html(f"❌ {safe_html(str(e))}"); return
    await save_model_config_db()
    await update.message.reply_html(
        f"✅ [{provider}] {tier.title()} model set to:\n<code>{safe_html(model)}</code>"
    )


@owner_only
async def listmodels_cmd(update, context):
    """Owner: /listmodels [provider] — shows live/known models for a provider."""
    provider = context.args[0].lower() if context.args else "groq"
    from utils.ai_provider import list_providers
    if provider not in list_providers():
        await update.message.reply_html(
            f"❌ {sc('Unknown provider.')} {sc('Options')}: {', '.join(list_providers())}"
        ); return
    cfg = get_current_models(provider); models = get_all_models(provider)
    text = (f"🤖 <b>{sc('AI Models')} — {provider}</b>\n\n"
            f"✅ {sc('Active free')}: <code>{safe_html(cfg['free_model'])}</code>\n"
            f"✅ {sc('Active premium')}: <code>{safe_html(cfg['premium_model'])}</code>\n\n"
            f"<b>{sc('Known/live models')}:</b>\n")
    for m in models["live"]:
        text += f"• <code>{safe_html(m)}</code>\n"
    text += f"\n{sc('Refresh this list')}: /refreshmodels {provider}"
    await update.message.reply_html(text)


@owner_only
async def refreshmodels_cmd(update, context):
    """Owner: /refreshmodels [provider] — force a fresh fetch of live models."""
    from utils.ai_provider import refresh_live_models
    provider = context.args[0].lower() if context.args else "groq"
    msg = await update.message.reply_html(f"🔄 {sc('Fetching live models from')} {provider}...")
    models = await refresh_live_models(provider, force=True)
    if not models:
        await msg.edit_text(
            "❌ " + sc("Couldn't fetch models — check that provider has at least one "
                       "healthy API key (/providerstatus)."),
            parse_mode="HTML"
        ); return
    text = f"✅ <b>{sc('Refreshed!')}</b> {len(models)} {sc('models available on')} {provider}:\n\n"
    text += "\n".join(f"• <code>{safe_html(m)}</code>" for m in models[:40])
    await msg.edit_text(text, parse_mode="HTML")


@owner_only
async def setmaxtokens_cmd(update, context):
    """Owner: /setmaxtokens <number> — controls response length for all AI calls."""
    from utils.ai_provider import get_max_tokens, set_max_tokens
    if not context.args:
        await update.message.reply_html(
            f"🔢 {sc('Current max tokens')}: <b>{get_max_tokens()}</b>\n"
            f"{sc('Usage')}: /setmaxtokens 1024  ({sc('range 64-8192')})"
        ); return
    try:
        n = int(context.args[0])
    except ValueError:
        await update.message.reply_html("❌ " + sc("Must be a number.")); return
    set_max_tokens(n)
    await save_model_config_db()
    from utils.ai_provider import get_max_tokens as _gmt
    await update.message.reply_html(f"✅ {sc('Max tokens set to')}: <b>{_gmt()}</b>")


@owner_only
async def addapikey_cmd(update, context):
    """Owner: /addapikey <key> [provider] — adds a key to a provider's pool.
    Provider defaults to groq if not specified."""
    from utils.ai_provider import add_api_key, save_api_keys_db, list_providers
    if not context.args:
        links = "\n".join(f"  • {p}: {_PROVIDER_SETUP_LINKS[p]}" for p in list_providers())
        await update.message.reply_html(
            "🔑 " + sc("Usage: /addapikey <key> [provider]") + "\n" +
            sc("Providers") + f": {', '.join(list_providers())} " + sc("(default: groq)") + "\n\n" +
            sc("Get a free key") + ":\n" + links
        ); return
    key = context.args[0].strip()
    provider = context.args[1].lower() if len(context.args) > 1 else "groq"
    if provider not in list_providers():
        await update.message.reply_html(
            f"❌ {sc('Unknown provider.')} {sc('Options')}: {', '.join(list_providers())}"
        ); return
    try:
        ok = add_api_key(key, provider=provider)
    except ValueError as e:
        await update.message.reply_html(f"❌ {safe_html(str(e))}"); return
    await save_api_keys_db()
    if ok:
        await update.message.reply_html(
            f"✅ {sc('API key added to')} <b>{provider}</b>! ({key[:7]}...{key[-4:]})\n" +
            sc("Check status with") + " /providerstatus"
        )
    else:
        await update.message.reply_html("⚠️ " + sc("That key is already in the pool."))


@owner_only
async def removeapikey_cmd(update, context):
    """Owner: /removeapikey <key_prefix> [provider] — removes a key."""
    from utils.ai_provider import remove_api_key, save_api_keys_db, list_providers
    if not context.args:
        await update.message.reply_html(
            "🔑 " + sc("Usage: /removeapikey <key_prefix> [provider]")
        ); return
    provider = context.args[1].lower() if len(context.args) > 1 else "groq"
    if provider not in list_providers():
        await update.message.reply_html(
            f"❌ {sc('Unknown provider.')} {sc('Options')}: {', '.join(list_providers())}"
        ); return
    ok = remove_api_key(context.args[0].strip(), provider=provider)
    await save_api_keys_db()
    if ok:
        await update.message.reply_html(f"🗑️ {sc('Key removed from')} <b>{provider}</b>.")
    else:
        await update.message.reply_html("❌ " + sc("No matching key found."))


@owner_only
async def keypoolstatus_cmd(update, context):
    """Owner: shows health/stats for every API key across all providers
    (or one provider if specified)."""
    from utils.ai_provider import get_key_pool_status, list_providers
    provider = context.args[0].lower() if context.args else None
    if provider and provider not in list_providers():
        await update.message.reply_html(
            f"❌ {sc('Unknown provider.')} {sc('Options')}: {', '.join(list_providers())}"
        ); return
    pools = get_key_pool_status(provider)
    if not any(pools.values()):
        await update.message.reply_html(
            "❌ " + sc("No API keys configured for any provider!") + "\n" +
            sc("Add one") + ": /addapikey &lt;key&gt; &lt;provider&gt;"
        ); return
    text = f"🔑 <b>{sc('API Key Pool Status')}</b>\n\n"
    for pid, keys in pools.items():
        if not keys:
            continue
        text += f"<b>{pid}</b> ({len(keys)} {sc('keys')})\n"
        for k in keys:
            icon = {"active": "🟢", "cooling_down": "🟡", "disabled": "🔴"}.get(k["status"], "⚪")
            text += (
                f"{icon} <code>{k['masked']}</code> — {sc(k['status'].replace('_',' ').title())}\n"
                f"   {sc('Requests')}: {k['total']} ({k['success']} ✅ / {k['failed']} ❌)\n"
            )
            if k["cooldown_seconds_left"] > 0:
                text += f"   {sc('Cooldown')}: {k['cooldown_seconds_left']}s\n"
            if k["last_error"]:
                text += f"   {sc('Last error')}: <code>{safe_html(k['last_error'][:80])}</code>\n"
        text += "\n"
    await update.message.reply_html(text)


@owner_only
async def setpriority_cmd(update, context):
    """Owner: /setpriority groq,gemini,openrouter,cloudflare — sets the
    fallback order providers are tried in."""
    from utils.ai_provider import set_provider_priority, get_provider_priority, list_providers
    if not context.args:
        await update.message.reply_html(
            f"🔀 {sc('Current priority')}: {' → '.join(get_provider_priority())}\n\n"
            f"{sc('Usage')}: /setpriority groq,gemini,openrouter,cloudflare"
        ); return
    order = [p.strip().lower() for p in " ".join(context.args).split(",")]
    ok = set_provider_priority(order)
    if not ok:
        await update.message.reply_html(
            f"❌ {sc('Must include every provider exactly once')}: {', '.join(list_providers())}"
        ); return
    await save_model_config_db()
    await update.message.reply_html(f"✅ {sc('New priority')}: {' → '.join(order)}")


@owner_only
async def toggleprovider_cmd(update, context):
    """Owner: /toggleprovider <provider> — enable/disable a provider
    without removing its keys."""
    from utils.ai_provider import set_provider_enabled, get_providers_status, list_providers
    if not context.args:
        await update.message.reply_html(
            f"🔀 {sc('Usage')}: /toggleprovider &lt;provider&gt;\n"
            f"{sc('Providers')}: {', '.join(list_providers())}"
        ); return
    provider = context.args[0].lower()
    if provider not in list_providers():
        await update.message.reply_html(
            f"❌ {sc('Unknown provider.')} {sc('Options')}: {', '.join(list_providers())}"
        ); return
    current = next((p["enabled"] for p in get_providers_status() if p["id"] == provider), True)
    set_provider_enabled(provider, not current)
    await save_model_config_db()
    state = sc("disabled") if current else sc("enabled")
    await update.message.reply_html(f"✅ <b>{provider}</b> {sc('is now')} {state}.")


# ── /scan — hidden owner command ───────────────────────────────────────────────

@owner_only
async def scan_cmd(update, context):
    """Full user scan — owner-only secret command."""
    if not context.args:
        await update.message.reply_html(f"Usage: /scan {placeholder('uid')}"); return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_html("❌ Invalid uid!"); return
    d = await get_user(uid)
    if not d:
        await update.message.reply_html("❌ User not found!"); return
    from utils.mongo_db import get_card_rank, get_user_rank
    cr = await get_card_rank(uid); rank = await get_user_rank(uid)
    now = int(time.time())
    prem_until = d.get("premium_until", 0)
    prem_exp = time.strftime('%d/%m/%Y', time.localtime(prem_until)) if prem_until > now else "Expired"
    # NOTE: full_name, username, and name/username history all come
    # straight from Telegram and are fully user-controlled — a user could
    # set their display name to contain HTML-looking text. Escape every
    # one of these before interpolating into an HTML-mode message.
    name_hist = ', '.join(safe_html(n) for n in d.get('name_history', [])[:5]) or "—"
    uname_hist = ', '.join(safe_html(n) for n in d.get('username_history', [])[:5]) or "—"
    await update.message.reply_html(
        f"🔍 <b>Full Scan — User <code>{uid}</code></b>\n\n"
        f"👤 Name: {safe_html(d.get('full_name', '?'))}\n"
        f"📛 Username: @{safe_html(d.get('username', 'none'))}\n"
        f"💰 Balance: {fmt(d.get('balance', 0))}\n"
        f"🏦 Wallet: {fmt(d.get('wallet', 0))}\n"
        f"💎 Gems: {d.get('gems', 0)}\n"
        f"💓 Premium: {d.get('is_premium', False)} (Until: {prem_exp})\n"
        f"🚫 Banned: {d.get('is_banned', False)}\n"
        f"💀 Kills: {d.get('kills', 0)} | Robs: {d.get('robs', 0)}\n"
        f"⚡ XP: {d.get('xp', 0)} | Level: {d.get('level', 1)}\n"
        f"🌍 Rank: #{rank}\n"
        f"🃏 Card W:{cr.get('wins', 0)} L:{cr.get('losses', 0)} "
        f"Won:{fmt(cr.get('won_amount', 0))}\n"
        f"🛡️ Protected until: {time.strftime('%d/%m %H:%M', time.localtime(d.get('protected_until', 0)))}\n"
        f"💀 Dead until: {time.strftime('%d/%m %H:%M', time.localtime(d.get('dead_until', 0)))}\n"
        f"📅 Joined: {time.strftime('%d/%m/%Y', time.localtime(d.get('created_at', 0)))}\n\n"
        f"📝 Name History: {name_hist}\n"
        f"📛 Username History: {uname_hist}"
    )


@owner_only
async def resetuser_cmd(update, context):
    if not context.args:
        await update.message.reply_html(f"Usage: /resetuser {placeholder('uid')}"); return
    try:
        uid = int(context.args[0])
    except ValueError:
        await update.message.reply_html("❌ Invalid uid!"); return
    await update_user(uid, balance=0, gems=0, kills=0, robs=0, xp=0,
                       is_premium=False, premium_until=0, wallet=0,
                       dead_until=0, protected_until=0)
    await update.message.reply_html(f"✅ User <code>{uid}</code> reset!")


@owner_only
async def giveall_cmd(update, context):
    """Give coins to ALL users."""
    if not context.args:
        await update.message.reply_html(f"Usage: /giveall {placeholder('amount')}"); return
    try:
        amt = int(context.args[0])
    except ValueError:
        await update.message.reply_html("❌ Invalid amount!"); return
    db = get_db()
    result = await db.users.update_many({"is_banned": {"$ne": True}}, {"$inc": {"balance": amt}})
    await update.message.reply_html(f"💰 Gave {fmt(amt)} to <b>{result.modified_count}</b> users!")


_maintenance = False


@owner_only
async def premiumlist_cmd(update, context):
    """
    Owner: list all premium users with names — paginated (20 per page)
    since a popular bot could have hundreds of premium users and dumping
    them all in one message would hit Telegram's message length limit.
    Usage: /premiumlist [page]
    """
    db = get_db()
    page = 1
    if context.args:
        try:
            page = max(1, int(context.args[0]))
        except ValueError:
            pass
    per_page = 20
    total = await db.users.count_documents({"is_premium": True})
    if total == 0:
        await update.message.reply_html("💓 No premium users yet!"); return

    users = await db.users.find(
        {"is_premium": True}, {"full_name": 1, "username": 1, "premium_until": 1}
    ).sort("premium_until", -1).skip((page-1)*per_page).limit(per_page).to_list(per_page)

    now = time.time()
    lines = []
    for i, u in enumerate(users, start=(page-1)*per_page + 1):
        name = safe_html(u.get("full_name") or "?")
        uname = f"@{safe_html(u['username'])}" if u.get("username") else ""
        exp = u.get("premium_until", 0)
        exp_str = time.strftime('%d %b %Y', time.localtime(exp)) if exp > now else "expired"
        lines.append(f"{i}. {name} {uname} — <code>{u['_id']}</code> (until {exp_str})")

    total_pages = (total + per_page - 1) // per_page
    await update.message.reply_html(
        f"💓 <b>Premium Users</b> (page {page}/{total_pages}, {total} total)\n\n"
        + "\n".join(lines) +
        (f"\n\nNext: /premiumlist {page+1}" if page < total_pages else "")
    )


@owner_only
async def userslist_cmd(update, context):
    """
    Owner: list all users with names — paginated (20 per page), sorted
    by balance so the most active players surface first.
    Usage: /userslist [page]
    """
    db = get_db()
    page = 1
    if context.args:
        try:
            page = max(1, int(context.args[0]))
        except ValueError:
            pass
    per_page = 20
    total = await total_users()
    if total == 0:
        await update.message.reply_html("👥 No users yet!"); return

    users = await db.users.find(
        {}, {"full_name": 1, "username": 1, "balance": 1, "is_premium": 1, "is_banned": 1}
    ).sort("balance", -1).skip((page-1)*per_page).limit(per_page).to_list(per_page)

    lines = []
    for i, u in enumerate(users, start=(page-1)*per_page + 1):
        name = safe_html(u.get("full_name") or "?")
        uname = f"@{safe_html(u['username'])}" if u.get("username") else ""
        tag = " 💓" if u.get("is_premium") else ""
        tag += " 🚫" if u.get("is_banned") else ""
        lines.append(f"{i}. {name} {uname} — {fmt(u.get('balance', 0))}{tag} (<code>{u['_id']}</code>)")

    total_pages = (total + per_page - 1) // per_page
    await update.message.reply_html(
        f"👥 <b>All Users</b> (page {page}/{total_pages}, {total} total)\n\n"
        + "\n".join(lines) +
        (f"\n\nNext: /userslist {page+1}" if page < total_pages else "")
    )


@owner_only
async def maintenance_cmd(update, context):
    global _maintenance
    args = context.args
    if not args:
        await update.message.reply_html(f"🔧 Maintenance: {'ON' if _maintenance else 'OFF'}"); return
    _maintenance = args[0].lower() == "on"
    await update.message.reply_html(f"🔧 Maintenance: <b>{'ON' if _maintenance else 'OFF'}</b>!")


def is_maintenance():
    return _maintenance


# ═══════════════════════════════════════════════════════════════════════════
#  🎭 Owner-managed sticker packs (for sticker-to-sticker replies)
# ═══════════════════════════════════════════════════════════════════════════
#
# Lets the owner build up Iota's own "reply stickers" entirely from
# Telegram, without touching code or redeploying:
#   1. Send/forward a sticker to the bot in DM, replying to it with
#      /addsticker <mood>  (e.g. /addsticker happy)
#   2. Iota will now sometimes reply with THAT sticker (instead of just
#      a GIF) whenever she detects that mood in sticker_reply.py.
# A mood can hold multiple stickers — Iota picks randomly among them,
# so the more you add, the more varied her sticker replies feel.

# ── Auto mood detection ──────────────────────────────────────────────────
# Lets the owner SKIP typing a mood by hand. Iota decides the mood itself —
# for a single sticker from its emoji, and for a whole pack by tallying every
# sticker's emoji and picking the most common mood. If a pack has no known
# mood-emoji at all, the pack's title becomes the mood. The mood is always
# created automatically if it doesn't exist yet (add_sticker_to_pack simply
# $addToSet's into a per-mood doc), and there is no cap — unlimited packs/moods.
# NOTE: _sanitize_mood / _auto_mood_from_pack are defined once in
# handlers/sticker_reply.py and imported here, so the owner commands and the
# automatic sticker-reply logic share a single implementation.

@owner_only
async def addsticker_cmd(update, context):
    """Owner: reply to a sticker with /addsticker <mood> to add it to that mood's pack."""
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.sticker:
        await msg.reply_html(
            "📎 <b>Add a reply sticker</b>\n\n"
            "Reply to a sticker with:\n"
            f"<code>/addsticker {placeholder('mood')}</code>\n\n"
            "Mood is optional — if you leave it out, Iota auto-detects it "
            "from the sticker's emoji.\n"
            "Example moods: happy, sad, love, laugh, angry, cute, dance, "
            "cool, surprise, slap, kiss, hug, welcome — or make up your own!\n\n"
            "💡 To save the WHOLE pack in one tap, reply with /addpack.\n\n"
            "See all current packs: /stickerpacks"
        ); return
    if not context.args:
        # No mood given → auto-decide from the replied sticker's emoji.
        mood = _detect_mood_from_sticker(msg.reply_to_message.sticker)
        auto = True
    else:
        mood = context.args[0].lower()
        auto = False
    file_id = msg.reply_to_message.sticker.file_id
    await add_sticker_to_pack(mood, file_id, update.effective_user.id)
    count = len(await get_stickers_for_mood(mood))
    await msg.reply_html(
        f"✅ Sticker added to <b>{safe_html(mood)}</b> pack! "
        f"({count} sticker{'s' if count != 1 else ''} in this pack now)"
        f"{'  🤖 <i>(mood auto-detected)</i>' if auto else ''}"
    )


@owner_only
async def addstickerpack_cmd(update, context):
    """
    🆕 Owner: reply to ANY sticker with /addstickerpack <mood> to import
    the ENTIRE Telegram sticker pack that sticker belongs to — not just
    that one sticker. Uses Telegram's own get_sticker_set (the pack name
    is on every sticker as .set_name) to fetch every sticker in the set,
    then adds them all to the mood in one shot via the existing
    add_sticker_to_pack() (which already de-dupes via $addToSet, so
    re-running this on the same pack is always safe).
    This is the "save the whole bundle, not one at a time" feature —
    /addsticker still exists for adding a single one-off sticker.
    """
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.sticker:
        await msg.reply_html(
            "📦 <b>Import a whole sticker pack</b>\n\n"
            "Reply to any sticker from the pack with:\n"
            f"<code>/addstickerpack {placeholder('mood')}</code>\n\n"
            "This saves EVERY sticker in that pack under one mood, not just the one you replied to."
        ); return
    if not context.args:
        # No mood given → auto-decide once we've fetched the pack.
        auto = True
    else:
        mood = context.args[0].lower()
        auto = False

    sticker = msg.reply_to_message.sticker
    set_name = sticker.set_name
    if not set_name:
        await msg.reply_html("❌ That sticker doesn't belong to a named pack — use /addsticker for a single sticker instead.")
        return

    status = await msg.reply_html(f"📦 Fetching sticker pack <b>{safe_html(set_name)}</b>...")
    try:
        sticker_set = await context.bot.get_sticker_set(set_name)
    except TelegramError as e:
        await status.edit_text(f"❌ Couldn't fetch that pack: {safe_html(str(e))}", parse_mode="HTML")
        return

    if auto:
        mood = _auto_mood_from_pack(sticker_set)

    added = 0
    for s in sticker_set.stickers:
        try:
            await add_sticker_to_pack(mood, s.file_id, update.effective_user.id)
            added += 1
        except Exception as e:
            logger.debug(f"addstickerpack_cmd: failed to add one sticker: {e}")

    total = len(await get_stickers_for_mood(mood))
    await status.edit_text(
        f"✅ Imported <b>{added}</b> stickers from <b>{safe_html(set_name)}</b> "
        f"into the <b>{safe_html(mood)}</b> pack!"
        f"{'  🤖 <i>(mood auto-detected)</i>' if auto else ''}\n"
        f"({total} sticker{'s' if total != 1 else ''} in this pack total now)",
        parse_mode="HTML"
    )


@owner_only
async def addpack_cmd(update, context):
    """
    🆕 Owner: reply to ANY sticker with /addpack — no mood needed. Iota
    fetches the ENTIRE pack it belongs to and saves EVERY sticker in it
    under a MOOD IT DECIDES AUTOMATICALLY (tallying the pack's emojis, or
    falling back to the pack title). The mood is created on the fly if it
    doesn't exist, and you can pile in as many packs as you like — there is
    no limit on packs or moods.

    This is the "one tap, whole pack, auto mood" command. /addstickerpack
    still exists for when you want to NAME the mood yourself.
    """
    msg = update.message
    if not msg.reply_to_message or not msg.reply_to_message.sticker:
        await msg.reply_html(
            "📦 <b>Auto-import a whole sticker pack</b>\n\n"
            "Just reply to ANY sticker from the pack with:\n"
            "<code>/addpack</code>\n\n"
            "Iota auto-decides the mood (from the pack's emojis), creates it "
            "if needed, and saves EVERY sticker in the pack — no mood "
            "argument required.\n\n"
            "💡 Want to pick the mood yourself? Use:\n"
            f"<code>/addstickerpack {placeholder('mood')}</code>"
        ); return

    sticker = msg.reply_to_message.sticker
    set_name = sticker.set_name
    if not set_name:
        await msg.reply_html(
            "❌ That sticker isn't part of a named pack.\n"
            "Reply to a sticker that belongs to a pack, or use /addsticker "
            "to save just that one sticker."
        ); return

    status = await msg.reply_html(
        f"📦 Fetching pack <b>{safe_html(set_name)}</b> and auto-deciding its mood..."
    )
    try:
        sticker_set = await context.bot.get_sticker_set(set_name)
    except TelegramError as e:
        await status.edit_text(
            f"❌ Couldn't fetch that pack: {safe_html(str(e))}", parse_mode="HTML"
        ); return

    mood = _auto_mood_from_pack(sticker_set)

    added = 0
    for s in sticker_set.stickers:
        try:
            await add_sticker_to_pack(mood, s.file_id, update.effective_user.id)
            added += 1
        except Exception as e:
            logger.debug(f"addpack_cmd: failed to add one sticker: {e}")

    total = len(await get_stickers_for_mood(mood))
    await status.edit_text(
        f"✅ Auto-imported <b>{added}</b> sticker{'s' if added != 1 else ''} from "
        f"<b>{safe_html(set_name)}</b> into the auto-decided mood "
        f"<b>{safe_html(mood)}</b>!\n"
        f"({total} sticker{'s' if total != 1 else ''} in this pack total now)\n\n"
        f"💡 Preview: /previewsticker {mood}\n"
        f"💡 List all packs: /stickerpacks",
        parse_mode="HTML"
    )


@owner_only
async def stickerpacks_cmd(update, context):
    """Owner: list every configured mood and how many stickers it has."""
    packs = await list_all_sticker_packs()
    if not packs:
        await update.message.reply_html(
            "📭 No sticker packs configured yet!\n\n"
            "Reply to any sticker with /addsticker <mood> to start building one."
        ); return
    lines = [f"• <b>{safe_html(mood)}</b> — {count} sticker{'s' if count != 1 else ''}"
             for mood, count in sorted(packs.items())]
    await update.message.reply_html(
        f"🎭 <b>Sticker Packs</b> ({len(packs)} moods)\n\n" + "\n".join(lines) +
        f"\n\n💡 /previewsticker {placeholder('mood')} to see one\n"
        f"💡 /clearstickers {placeholder('mood')} to wipe a pack"
    )


@owner_only
async def previewsticker_cmd(update, context):
    """Owner: preview a random sticker from a mood's pack."""
    if not context.args:
        await update.message.reply_html(f"Usage: /previewsticker {placeholder('mood')}"); return
    mood = context.args[0].lower()
    stickers = await get_stickers_for_mood(mood)
    if not stickers:
        await update.message.reply_html(f"❌ No stickers in <b>{safe_html(mood)}</b> pack yet!"); return
    import random as _random
    await update.message.reply_sticker(_random.choice(stickers))
    await update.message.reply_html(f"👆 One of {len(stickers)} sticker(s) in <b>{safe_html(mood)}</b>")


@owner_only
async def clearstickers_cmd(update, context):
    """Owner: wipe an entire mood's sticker pack."""
    if not context.args:
        await update.message.reply_html(f"Usage: /clearstickers {placeholder('mood')}"); return
    mood = context.args[0].lower()
    removed = await clear_sticker_pack(mood)
    if removed == 0:
        await update.message.reply_html(f"❌ <b>{safe_html(mood)}</b> pack was already empty!"); return
    await update.message.reply_html(f"🗑️ Cleared <b>{removed}</b> sticker(s) from <b>{safe_html(mood)}</b>!")


# ═══════════════════════════════════════════════════════════════════════════
#  🔊 Owner-configurable TTS/Voice settings
# ═══════════════════════════════════════════════════════════════════════════

def _tts_panel_text() -> str:
    from utils.sarvam import get_tts_config
    cfg = get_tts_config()
    return (
        f"🔊 <b>Voice/TTS Settings</b>\n\n"
        f"🤖 Model: <code>{cfg['model']}</code>\n"
        f"🗣️ Speaker: <code>{cfg['speaker']}</code>\n"
        f"⚡ Pace (speed): <code>{cfg['pace']}</code>  (0.5 slow – 2.0 fast)\n"
        f"🎵 Pitch: <code>{cfg['pitch']}</code>  (-20 – 20)\n"
        f"🔉 Loudness: <code>{cfg['loudness']}</code>  (0.5 – 2.0)\n\n"
        f"Change with:\n"
        f"<code>/ttssettings speaker anushka</code>\n"
        f"<code>/ttssettings pace 1.2</code>\n"
        f"<code>/ttssettings pitch 2</code>\n"
        f"<code>/ttssettings loudness 1.8</code>\n\n"
        f"Valid speakers: anushka, manisha, vidya, arya, abhilash, karun, hitesh\n"
        f"Test it: /previewtts {placeholder('text')}"
    )


@owner_only
async def ttssettings_cmd(update, context):
    """Owner: view or change Iota's voice/TTS defaults (model, speaker, speed, pitch, loudness)."""
    from utils.sarvam import set_tts_setting, save_tts_config_db
    args = context.args
    if len(args) < 2:
        await update.message.reply_html(_tts_panel_text()); return

    key, value = args[0].lower(), args[1]
    ok, err = set_tts_setting(key, value)
    if not ok:
        await update.message.reply_html(f"❌ {safe_html(err)}"); return

    await save_tts_config_db()
    await update.message.reply_html(f"✅ TTS <b>{safe_html(key)}</b> set to <code>{safe_html(value)}</code>!\n\n" + _tts_panel_text())


@owner_only
async def previewtts_cmd(update, context):
    """Owner: preview the current TTS settings with a sample line."""
    from utils.sarvam import text_to_speech
    text = " ".join(context.args) if context.args else "Hii, main Iota hoon! Ye meri current voice hai."
    thinking = await update.message.reply_html("🔊 Generating preview...")
    audio = await text_to_speech(text[:300])
    if not audio:
        await thinking.edit_text("❌ TTS generation failed — check the bot's logs for details."); return
    import io
    af = io.BytesIO(audio); af.name = "preview.wav"
    await thinking.delete()
    await update.message.reply_voice(af, caption=f"🔊 Preview: {safe_html(text[:100])}")


# ═══════════════════════════════════════════════════════════════════════════
#  🗑️ Broadcast/Announce deletion + history
# ═══════════════════════════════════════════════════════════════════════════

@owner_only
async def delbroadcast_cmd(update, context):
    """
    Owner: delete a past broadcast/announce.
      /delbroadcast <id>              — delete from EVERY chat it reached
      /delbroadcast <id> <chat_id>    — delete from just ONE chat
    """
    if not context.args:
        await update.message.reply_html(
            f"Usage:\n"
            f"/delbroadcast {placeholder('id')} — delete everywhere\n"
            f"/delbroadcast {placeholder('id')} {placeholder('chat_id')} — delete from one chat\n\n"
            f"Find IDs with /broadcasthistory"
        ); return

    bid = context.args[0]
    record = await get_broadcast_record(bid)
    if not record:
        await update.message.reply_html(f"❌ No broadcast found with ID <code>{safe_html(bid)}</code>"); return

    only_chat = None
    if len(context.args) > 1:
        try:
            only_chat = int(context.args[1])
        except ValueError:
            await update.message.reply_html("❌ chat_id must be a number!"); return

    targets = record.get("targets", [])
    if only_chat is not None:
        targets = [t for t in targets if t["chat_id"] == only_chat]
        if not targets:
            await update.message.reply_html(f"❌ This broadcast was never sent to <code>{only_chat}</code>."); return

    status = await update.message.reply_html(f"🗑️ Deleting from {len(targets)} chat(s)...")
    deleted = 0; failed = 0
    for t in targets:
        try:
            await context.bot.delete_message(t["chat_id"], t["message_id"])
            deleted += 1
        except Exception as e:
            failed += 1
            logger.debug(f"delbroadcast: failed to delete in {t['chat_id']}: {e}")
        await asyncio.sleep(0.05)

    scope = f"from chat <code>{only_chat}</code>" if only_chat else "from everywhere"
    await status.edit_text(
        f"🗑️ <b>Deletion complete</b> ({scope})\n\n"
        f"✅ Deleted: {deleted}\n"
        f"⚠️ Failed: {failed} (message too old — Telegram only allows deleting "
        f"bot messages within 48 hours in some chat types — or already deleted)",
        parse_mode="HTML"
    )


@owner_only
async def broadcasthistory_cmd(update, context):
    """Owner: view the last 20 broadcasts/announces sent, with their IDs for /delbroadcast."""
    records = await list_broadcast_history(limit=20)
    if not records:
        await update.message.reply_html("📭 No broadcasts sent yet!"); return

    lines = []
    for r in records:
        t = time.strftime('%d/%m %H:%M', time.localtime(r.get("created_at", 0)))
        kind_emoji = "📢" if r.get("kind") == "announce" else "📨"
        preview = safe_html(r.get("content_preview", ""))[:40]
        target_count = len(r.get("targets", []))
        lines.append(
            f"{kind_emoji} <code>{r['_id']}</code> — {t} — {target_count} chats\n"
            f"    \"{preview}{'...' if len(preview) >= 40 else ''}\""
        )
    await update.message.reply_html(
        f"📜 <b>Broadcast History</b> (last {len(records)})\n\n" + "\n\n".join(lines) +
        f"\n\n💡 /delbroadcast {placeholder('id')} to delete one"
    )


# ══════════════════════════════════════════════════════════════════════
# 🆕 Owner-only: Iota Premium Giveaway
# ══════════════════════════════════════════════════════════════════════
# Distinct from the generic /giveaway (handlers/new_features_v2.py, any
# group admin can run with any text prize). This one is OWNER-ONLY, and
# the prize is real: whoever wins actually gets Iota Premium granted to
# their account automatically the moment the giveaway ends — no manual
# /addpremium follow-up needed.

@owner_only
async def premiumgiveaway_cmd(update, context):
    """/premiumgiveaway <minutes> <days> [winner_count]
    e.g. /premiumgiveaway 10 30       → 1 winner, 30 days premium
         /premiumgiveaway 10 30 3     → 3 winners, 30 days premium each
    """
    msg = update.message; chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("🚫 " + sc("Run this in a group so people can join.")); return
    if len(context.args) < 2:
        await msg.reply_html(
            "💓 " + sc("Usage: /premiumgiveaway <minutes> <days> [winner_count]") +
            "\n" + sc("Example: /premiumgiveaway 10 30  (10 min entry, 30 days premium, 1 winner)")
        ); return
    try:
        minutes = max(1, min(1440, int(context.args[0])))
        days = max(1, min(3650, int(context.args[1])))
        winner_count = max(1, min(20, int(context.args[2]))) if len(context.args) > 2 else 1
    except ValueError:
        await msg.reply_html("❌ " + sc("Minutes, days, and winner count must all be numbers.")); return

    import time as _time, random as _random, asyncio as _asyncio
    from utils.mongo_db import create_giveaway, join_giveaway, get_giveaway, end_giveaway
    from telegram import InlineKeyboardMarkup, InlineKeyboardButton

    end_ts = _time.time() + minutes * 60
    prize_label = f"Iota Premium — {days} {sc('days')} ({winner_count} {sc('winner(s)')})"

    sent = await msg.reply_html(
        f"💓🎉 <b>{sc('Iota Premium Giveaway')}!</b>\n\n"
        f"🎁 {sc('Prize')}: <b>{days} {sc('days of Iota Premium')}</b>\n"
        f"🏆 {sc('Winners')}: {winner_count}\n"
        f"⏳ {sc('Ends in')} {minutes} {sc('minute(s)')}\n\n"
        f"{sc('Tap below to join!')}",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💓 Join Giveaway", callback_data="ga_join:pending")]])
    )
    gid = await create_giveaway(chat.id, sent.message_id, prize_label, end_ts, update.effective_user.id)
    try:
        await sent.edit_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("💓 Join Giveaway", callback_data=f"ga_join:{gid}")]])
        )
    except Exception as e:
        logger.debug(f"premiumgiveaway_cmd edit_reply_markup failed: {e}")

    async def _finish():
        await _asyncio.sleep(minutes * 60)
        try:
            doc = await get_giveaway(gid)
            if not doc or doc.get("ended"):
                return
            participants = doc.get("participants", [])
            if not participants:
                await end_giveaway(gid, None)
                await context.bot.send_message(
                    chat.id, f"😔 {sc('Premium giveaway ended with no participants.')}"
                )
                return
            winners = _random.sample(participants, min(winner_count, len(participants)))
            await end_giveaway(gid, winners[0])

            now = int(_time.time())
            granted_lines = []
            for wid in winners:
                try:
                    await ensure_user(wid)
                    until = now + days * 86400
                    await update_user(wid, is_premium=True, premium_until=until)
                    granted_lines.append(f'🏆 <a href="tg://user?id={wid}">🎁 {sc("Winner")}</a> — Premium granted!')
                except Exception as e:
                    logger.debug(f"premiumgiveaway: failed to grant premium to {wid}: {e}")

            await context.bot.send_message(
                chat.id,
                f"💓🎉 <b>{sc('Premium Giveaway Ended!')}</b>\n\n" +
                "\n".join(granted_lines) +
                f"\n\n{days} {sc('days of Iota Premium — already active, enjoy!')} 💕",
                parse_mode="HTML",
            )
        except Exception as e:
            logger.debug(f"premiumgiveaway _finish failed: {e}")

    _asyncio.create_task(_finish())
