"""
Iota Bot — /whisper command
Send a PRIVATE message to a user from inside a group. The group only sees a
card + a "Read whisper" button; the actual text is delivered privately (a DM
plus the button's alert popup) and a small-caps read receipt is posted back
to the group when the target opens it.

Privacy model (why it works this way)
─────────────────────────────────────
A message you TYPE in a group is, by Telegram's design, visible to every group
member (and pushed to their notifications) until it is deleted — there is no
way for a bot to hide text you literally sent to the group. So:

  • If you send `.whisper @user <text>`, the command message is deleted as soon
    as the whisper is created (minimising the exposure window).
  • For FULL privacy, send `.whisper @user` with NO text. The bot then opens a
    private compose session: it DMs *you* and you type the secret there, so the
    secret never appears in the group at all. (While composing, the AI
    auto-reply is suppressed so the secret is never sent to the model.)
"""
import logging
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.error import Forbidden, BadRequest

from utils.mongo_db import (
    ensure_user, get_whisper, create_whisper, mark_whisper_read,
)
from utils.helpers import mention, resolve_target
from utils.safe_html import safe_html
from utils.fonts import sc, sc_all
from utils.callback_codec import encode_callback, decode_callback
from utils.ratelimit import ratelimit

logger = logging.getLogger(__name__)

# Per-user compose session, kept in context.user_data (survives across
# updates for that user). Holds the resolved target until the secret is
# collected privately via DM.
_COMPOSE_KEY = "wsp_draft"


def _mention_id(uid: int) -> str:
    return f'<a href="tg://user?id={uid}">this user</a>'


async def _delete_cmd(msg):
    """Best-effort: remove the user's command message so the secret text
    doesn't linger in the group. Failures are silent (e.g. message already
    gone, or the bot lacks delete permission)."""
    try:
        await msg.delete()
    except Exception:
        logger.debug("whisper: command message delete failed (ignored)")


@ratelimit("whisper", limit=12, window=20)
async def whisper_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    msg = update.effective_message
    chat = update.effective_chat
    if chat.type == "private":
        await msg.reply_html("❌ Whisper only works inside a group or supergroup."); return

    # Best-effort: keep our user records fresh. A DB hiccup here must
    # never block a whisper, so failures are swallowed.
    try:
        await ensure_user(u.id, u.username or "", u.full_name)
    except Exception:
        logger.debug("ensure_user failed in whisper", exc_info=True)

    # Resolve the target + the message text. Supports either:
    #   .whisper @user <message>      (named target)
    #   reply to a user + .whisper <message>   (replied target)
    if msg.reply_to_message and msg.reply_to_message.from_user:
        tgt = msg.reply_to_message.from_user
        target_id = tgt.id
        target_mention = mention(tgt)
        text = " ".join(context.args or [])
    else:
        try:
            target_id, target_mention, rest = await resolve_target(
                update, context, list(context.args or []))
        except Exception:
            logger.debug("resolve_target failed in whisper", exc_info=True)
            target_id, target_mention, rest = None, None, []
        text = " ".join(rest)

    if not target_id:
        await msg.reply_html(
            "❌ Mention a user or reply to them:\n"
            "<code>.whisper @user &lt;message&gt;</code>"); return
    if target_id == u.id:
        await msg.reply_html("❌ You can't whisper to yourself!"); return

    # Don't whisper to bots.
    try:
        tu = await context.bot.get_chat(target_id)
        if tu.is_bot:
            await msg.reply_html("❌ You can't whisper to a bot!"); return
    except Exception:
        pass

    text = (text or "").strip()

    # ── Full-privacy path: no text typed in the group at all ───────────────
    # The bot DMs the sender to collect the secret privately.
    if not text:
        context.user_data.setdefault(u.id, {})[_COMPOSE_KEY] = {
            "tid": target_id, "tmention": target_mention, "cid": chat.id,
        }
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✍️ " + sc("Write privately"),
                                 callback_data="wspc")
        ]])
        await msg.reply_html(
            sc_all(f"💬 {mention(u)} is writing a private whisper to "
                   f"{target_mention} 🤫"),
            reply_markup=kb,
        )
        await _delete_cmd(msg)
        return

    try:
        wid = await create_whisper(u.id, target_id, chat.id, text)
    except Exception:
        logger.exception("create_whisper failed in whisper")
        await msg.reply_html(
            "❌ " + sc("Couldn't save your whisper — try again in a bit."))
        return

    # Best-effort private delivery. If the target hasn't started the bot the
    # DM fails — that's fine, they still get the text via the "Read whisper"
    # button's alert popup, so a failed DM never blocks the whisper.
    try:
        await context.bot.send_message(
            target_id,
            f"🔥 {mention(u)} <b>{sc('whispered')}</b>:\n\n{safe_html(text)}",
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        pass

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✉️ " + sc("Read whisper"),
                             callback_data=encode_callback("wsp", {"w": wid}))
    ]])
    await msg.reply_html(
        sc_all(f"💬 {mention(u)} whispered to {target_mention} 🤫"),
        reply_markup=kb,
    )
    # Privacy: the command message contained the secret — delete it now.
    await _delete_cmd(msg)


async def whisper_compose_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Button tapped by the sender to open the private compose session."""
    q = update.callback_query
    u = q.from_user
    await q.answer()
    draft = (context.user_data.get(u.id) or {}).get(_COMPOSE_KEY)
    if not draft:
        try:
            await q.edit_message_text(
                "⌛ Whisper session expired — send <code>.whisper @user</code> "
                "again to start a new one.",
                parse_mode="HTML",
            )
        except Exception:
            pass
        return
    try:
        await context.bot.send_message(
            u.id,
            f"✍️ <b>Write your secret now</b> — it'll be delivered privately to "
            f"{draft['tmention']} 🤫\n\nJust send your message here. Only Iota "
            f"sees it; it never appears in the group.",
            parse_mode="HTML",
        )
        # Flag that the sender's NEXT private text is the whisper body.
        context.user_data.setdefault(u.id, {})["wsp_compose"] = True
        await q.edit_message_text(
            sc_all(f"💬 Check your DMs to write your private whisper 🤫"),
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        await q.edit_message_text(
            "❌ I couldn't DM you — please /start me in DMs first, then "
            "tap the button again.",
            parse_mode="HTML",
        )


async def whisper_dm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Captures the secret the sender types in DM during a compose session.

    Returns immediately (doing nothing) when the user is NOT composing, so it
    never interferes with normal DMs (/ai, etc.)."""
    u = update.effective_user
    msg = update.effective_message
    state = context.user_data.get(u.id) if context.user_data else None
    if not state or not state.get("wsp_compose"):
        return
    draft = state.get(_COMPOSE_KEY)
    if not draft:
        state.pop("wsp_compose", None)
        return

    text = (msg.text or "").strip()
    # Clear compose state first so a follow-up message is treated normally.
    state.pop("wsp_compose", None)
    state.pop(_COMPOSE_KEY, None)

    if not text:
        await msg.reply_html("❌ Whisper was empty — nothing sent. You can "
                             "retry in the group with <code>.whisper @user</code>.")
        return

    try:
        wid = await create_whisper(u.id, draft["tid"], draft["cid"], text)
    except Exception:
        logger.exception("create_whisper failed in whisper_dm_handler")
        await msg.reply_html("❌ Couldn't save your whisper — try again later.")
        return

    # Deliver privately to the target (best-effort).
    try:
        await context.bot.send_message(
            draft["tid"],
            f"🔥 {mention(u)} <b>{sc('whispered')}</b>:\n\n{safe_html(text)}",
            parse_mode="HTML",
        )
    except (Forbidden, BadRequest):
        pass

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✉️ " + sc("Read whisper"),
                             callback_data=encode_callback("wsp", {"w": wid}))
    ]])
    try:
        await context.bot.send_message(
            draft["cid"],
            sc_all(f"💬 {mention(u)} whispered to {draft['tmention']} 🤫"),
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        logger.debug("whisper_dm_handler: group card post failed")
    await msg.reply_html("✅ Whisper sent privately 🤫")


async def whisper_read_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    payload = decode_callback(q.data, "wsp")
    if not payload or "w" not in payload:
        try:
            await q.answer("❌ Invalid whisper button.", show_alert=True)
        except Exception:
            pass
        return
    wid = payload["w"]
    w = await get_whisper(wid)
    if not w:
        try:
            await q.answer("❌ Whisper not found.", show_alert=True)
        except Exception:
            pass
        return

    reader = q.from_user
    if reader.id != w["target_id"]:
        try:
            await q.answer("🔒 This whisper isn't for you.", show_alert=True)
        except Exception:
            pass
        return

    # Reveal the private text to the target via the alert popup. The callback
    # query can expire (Telegram only keeps it valid for a short window), so
    # a failed answer must NEVER crash the handler.
    try:
        await q.answer(f"🔥 {w['text']}", show_alert=True)
    except (BadRequest, Forbidden) as e:
        logger.debug(f"whisper read answer failed (query likely expired): {e}")
    except Exception as e:
        logger.debug(f"whisper read answer unexpected error: {e}")

    await mark_whisper_read(wid)

    # Post the small-caps read receipt back into the group.
    try:
        await context.bot.send_message(
            w["chat_id"],
            sc_all(f"✅ This whisper has been read by {mention(reader)}"),
            parse_mode="HTML",
        )
    except Exception:
        pass

    # Drop the button so it can't be opened again.
    try:
        await q.edit_message_reply_markup(reply_markup=None)
    except Exception:
        pass
