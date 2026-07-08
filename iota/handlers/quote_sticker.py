"""
Iota Bot — /q (Quote Sticker Command)

Reply to any text message with /q and Iota turns it into a styled quote
sticker — sender's name, avatar, and the message text, rendered as a
proper 512x512 Telegram sticker. See utils/quote_render.py for the
actual rendering engine and utils/font_manager.py for font handling.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from utils.helpers import get_profile_photo_id
from utils.quote_render import render_quote_sticker, QuoteRenderError
from utils.safe_html import safe_html

logger = logging.getLogger(__name__)

MAX_QUOTE_LENGTH = 400  # beyond this, even the smallest font can't stay readable


async def quote_sticker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    reply = msg.reply_to_message

    if not reply:
        await msg.reply_html(
            "❌ Reply to a message with /q to turn it into a quote sticker!"
        ); return

    # Only text (or captioned media, using the caption) can become a
    # readable quote card. Give a specific reason rather than a generic
    # failure for the common "replied to a sticker/photo with no text" case.
    text = reply.text or reply.caption
    if not text or not text.strip():
        if reply.sticker:
            await msg.reply_html("❌ Can't quote a sticker — reply to a text message instead."); return
        if reply.photo or reply.video or reply.animation:
            await msg.reply_html(
                "❌ This message type isn't supported — reply to a text message "
                "(a caption works too) instead."
            ); return
        if reply.voice or reply.audio:
            await msg.reply_html("❌ Can't quote a voice/audio message — reply to a text message instead."); return
        await msg.reply_html("❌ This message type isn't supported."); return

    if len(text) > MAX_QUOTE_LENGTH:
        await msg.reply_html(
            f"❌ That message is too long to fit on a sticker "
            f"({len(text)}/{MAX_QUOTE_LENGTH} characters max)."
        ); return

    sender = reply.from_user
    if not sender:
        await msg.reply_html("❌ Can't identify who sent that message."); return

    display_name = sender.full_name or sender.first_name or "Someone"

    # Fetch the sender's real profile photo if they have one — falls
    # back to a colored initial-letter avatar inside render_quote_sticker
    # if this returns None for any reason (no PFP set, privacy, etc.).
    avatar_bytes = None
    try:
        file_id = await get_profile_photo_id(context, sender.id)
        if file_id:
            tg_file = await context.bot.get_file(file_id)
            avatar_bytes = bytes(await tg_file.download_as_bytearray())
    except Exception as e:
        logger.debug(f"quote_sticker_cmd: avatar fetch failed for {sender.id}: {e}")
        avatar_bytes = None

    try:
        sticker_bytes = render_quote_sticker(display_name, text, avatar_bytes, sender.id)
    except QuoteRenderError as e:
        await msg.reply_html(safe_html(str(e))); return
    except Exception as e:
        logger.exception(f"quote_sticker_cmd: unexpected render failure: {e}")
        await msg.reply_html("❌ Couldn't generate that sticker — please try again."); return

    import io
    sticker_file = io.BytesIO(sticker_bytes)
    sticker_file.name = "quote.webp"
    try:
        await msg.reply_sticker(sticker_file)
    except Exception as e:
        logger.warning(f"quote_sticker_cmd: send_sticker failed: {e}")
        await msg.reply_html("❌ Couldn't send that sticker — please try again.")
