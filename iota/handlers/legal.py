"""
╔══════════════════════════════════════════════════════╗
║  IOTA BOT — Terms of Service & Refund Policy         ║
╚══════════════════════════════════════════════════════╝
"""
from telegram import Update
from telegram.ext import ContextTypes

TERMS_TEXT = (
    "📜 <b>Iota Bot — Terms & Refund Policy</b>\n\n"
    "Welcome to Iota Bot! By purchasing our premium services or virtual "
    "currency (Gems), you agree to follow the terms below:\n\n"

    "1️⃣ <b>Virtual Goods &amp; Gems</b>\n"
    "• 'Gems' are purely in-game virtual items with <b>zero real-world cash "
    "value</b>.\n"
    "• Gems can never be transferred, exchanged, or withdrawn for real "
    "money.\n\n"

    "2️⃣ <b>Premium Membership</b>\n"
    "• Premium status grants instant access to exclusive features inside "
    "the bot for the duration paid.\n"
    "• Perks and features can be updated or changed with prior notice in "
    "our official community channel.\n\n"

    "3️⃣ <b>Strict Refund Policy</b>\n"
    "• Since all assets (Gems/Premium Access) are digital goods delivered "
    "instantly to your account upon a successful payment, we enforce a "
    "<b>strict NO-REFUND POLICY</b>. All sales are final.\n"
    "• <i>Exception:</i> if money is deducted from your account/card but "
    "your Iota Bot items were not credited due to an unexpected technical "
    "lag, we will provide the purchased service after verification.\n\n"

    "4️⃣ <b>Fair Play &amp; Immediate Bans</b>\n"
    "• Exploiting bot vulnerabilities, bugs, running scripts/cheats, or "
    "trying to trick the automated payment gateway will lead to a "
    "<b>permanent ban</b> from Iota Bot.\n"
    "• Users banned for violating fair play policies forfeit any remaining "
    "premium days or gems with no eligibility for refund.\n\n"

    "5️⃣ <b>Bot Glitches &amp; In-Game Coins Disclaimer</b>\n"
    "• Iota Bot runs on automated server infrastructure. If you experience "
    "lag, slow responses, unexpected crashes, or glitches during mini-games "
    "due to Telegram API limits or server load, management is "
    "<b>not responsible</b> for any loss of virtual coins/credits.\n"
    "• We do not offer compensation or free Iota Coins for issues caused "
    "by technical lag or network delays. Play at your own risk.\n\n"

    "📩 Questions? Contact the owner via /owner in your group, or DM "
    "support directly."
)


async def terms_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(TERMS_TEXT, disable_web_page_preview=True)


# Alias so both /terms and /refund work and show the same policy doc
async def refund_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(TERMS_TEXT, disable_web_page_preview=True)


async def rules_legal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias: /policy"""
    await update.message.reply_html(TERMS_TEXT, disable_web_page_preview=True)
