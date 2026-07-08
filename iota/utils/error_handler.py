"""
╔══════════════════════════════════════════════════════╗
║  IOTA BOT — Global Error Handler                     ║
║                                                        ║
║  Catches unhandled exceptions in ANY command/handler  ║
║  so a single bug never silently breaks a command —    ║
║  the user always sees a friendly message instead of   ║
║  the bot just not responding at all.                  ║
╚══════════════════════════════════════════════════════╝
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Registered via app.add_error_handler() in bot.py"""
    err = context.error
    logger.error(f"⚠️ Unhandled exception: {err}", exc_info=err)

    # Detect common DB connectivity failures and give a clear hint
    err_str = str(err).lower()
    db_issue = any(k in err_str for k in [
        "serverselectiontimeout", "connection refused", "authentication failed",
        "no replica set members", "network is unreachable", "ssl handshake",
    ])

    if not isinstance(update, Update):
        return

    try:
        if update.callback_query:
            await update.callback_query.answer(
                "⚠️ Kuch gadbad ho gayi! Thodi der mein try karo." if not db_issue
                else "⚠️ Database connect nahi ho pa raha. Owner ko batao!",
                show_alert=True
            )
            return
        if update.effective_message:
            if db_issue:
                await update.effective_message.reply_html(
                    "🔌 <b>Database Connection Issue!</b>\n\n"
                    "Iota abhi database se connect nahi ho pa rahi.\n"
                    "Owner ko bot ki MongoDB settings check karne ko bolo. 🙏"
                )
            else:
                await update.effective_message.reply_html(
                    "⚠️ Kuch gadbad ho gayi! Thodi der mein try karo 🙄"
                )
    except Exception:
        pass
