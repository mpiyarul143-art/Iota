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

    # Detect DB connectivity / driver failures and give a clear hint.
    # Be broad: match any pymongo/motor exception type AND a wide set of
    # message substrings, because Mongo's error text varies a lot between
    # "connection refused", "server selection timeout", "not authorized",
    # TLS/cert errors, DNS/SRV resolution failures, etc. A real outage was
    # previously being mis-classified as a generic "try again later" bug,
    # hiding the actual cause from the owner.
    db_issue = False
    try:
        import pymongo.errors as _pe
        if isinstance(err, (_pe.PyMongoError,)):
            db_issue = True
    except Exception:
        pass
    if not db_issue:
        err_str = str(err).lower()
        db_issue = any(k in err_str for k in [
            "serverselectiontimeout", "server selection", "connection refused",
            "connection error", "connection timed out", "timed out", "timeout",
            "econnrefused", "connrefused", "authentication failed",
            "not authorized", "operationfailure", "no replica set members",
            "network is unreachable", "ssl handshake", "certificate",
            "getaddrinfo", "name or service not known", "no route to host",
            "dns", "srv", "pymongo", "motor", "missing dependency",
        ])

    # On a DB issue, let the owner know once so they can fix MONGO_URI /
    # MONGO_PASS instead of thinking every command is permanently broken.
    if db_issue:
        try:
            from config import OWNER_ID
            if OWNER_ID:
                await context.bot.send_message(
                    OWNER_ID,
                    "🔌 <b>Iota DB Connection Issue!</b>\n\n"
                    f"<code>{str(err)[:500]}</code>\n\n"
                    "Check MONGO_URI / MONGO_PASS. DB-backed commands "
                    "(/bal, /daily, /rob, /pay, …) will fail until fixed.",
                    parse_mode="HTML",
                )
        except Exception:
            pass

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
