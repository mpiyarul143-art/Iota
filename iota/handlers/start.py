"""Iota Bot - /start with Baka-style text + Menu button"""
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, MenuButtonCommands
from telegram.ext import ContextTypes
from utils.mongo_db import ensure_user, get_user
from utils.helpers import mention, fmt, xp_level, rank_title
from utils.fonts import sc, bold_sc

# ── Baka-style start text (unicode smallcaps) ─────────────────────────────────
def _start_text(name_mention: str) -> str:
    return (
        f"💕 ʜɪᴇᴇᴇᴇᴇ {name_mention}\n"
        f"ʏᴏᴜ ᴀʀᴇ ᴛᴀʟᴋɪɴɢ ᴛᴏ ɪᴏᴛᴀ, ᴀ ɢᴀᴍɪɴɢ ᴀɴᴅ ᴄʜᴀᴛᴛɪɴɢ ɢɪʀʟ ʜᴀᴠɪɴɢ ʟᴏᴛs ᴏꜰ ꜰᴇᴀᴛᴜʀᴇs.\n\n"
        f"👇 ᴄʜᴏᴏsᴇ ᴀɴ ᴏᴘᴛɪᴏɴ ʙᴇʟᴏᴡ :"
    )

def _start_kb(bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ɢʀᴏᴜᴘs",    callback_data="menu_groups"),
         InlineKeyboardButton("🤝 ᴘʀᴏᴍᴏᴛᴇʀ",  callback_data="menu_promoter")],
        [InlineKeyboardButton("🧸 ꜰʀɪᴇɴᴅs",   callback_data="menu_friends"),
         InlineKeyboardButton("🎮 ɢᴀᴍᴇs",     callback_data="menu_games")],
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ 👥",
                              url=f"https://t.me/{bot_username}?startgroup=start")],
    ])

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    me = await context.bot.get_me()

    # Try to send with image first
    castle_url = "https://i.imgur.com/wJuQEbG.jpeg"
    village_caption = (
        f"🏰 ʜᴇʟʟᴏ {mention(u)}! ᴡᴇʟᴄᴏᴍᴇ ᴛᴏ ɪᴏᴛᴀ!\n\n"
        f"ʙᴜɪʟᴅ ʏᴏᴜʀ ᴏᴡɴ ᴠɪʟʟᴀɢᴇ ᴀɴᴅ ʙᴇᴄᴏᴍᴇ ᴛʜᴇ sᴛʀᴏɴɢᴇsᴛ ᴇᴍᴘᴇʀᴏʀ.\n"
        f"ᴜᴘɢʀᴀᴅᴇ ʙᴜɪʟᴅɪɴɢs ᴛᴏ ᴄᴏʟʟᴇᴄᴛ ᴡᴏᴏᴅ, sᴛᴏɴᴇ & ɪʀᴏɴ ᴇᴠᴇʀʏ ᴅᴀʏ.\n"
        f"ᴛʀᴀɪɴ ᴀʀᴍʏ • ᴀᴛᴛᴀᴄᴋ ᴘʟᴀʏᴇʀs • ᴄʟɪᴍʙ ʟᴇᴀᴅᴇʀʙᴏᴀʀᴅ 👑"
    )

    kb2 = InlineKeyboardMarkup([
        [InlineKeyboardButton("👥 ɢʀᴏᴜᴘs",    callback_data="menu_groups"),
         InlineKeyboardButton("🤝 ᴘʀᴏᴍᴏᴛᴇʀ",  callback_data="menu_promoter")],
        [InlineKeyboardButton("🧸 ꜰʀɪᴇɴᴅs",   callback_data="menu_friends"),
         InlineKeyboardButton("🎮 ɢᴀᴍᴇs",     callback_data="menu_games")],
        [InlineKeyboardButton("➕ ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘ 👥",
                              url=f"https://t.me/{me.username}?startgroup=start")],
    ])

    try:
        await update.message.reply_photo(
            photo=castle_url, caption=village_caption,
            parse_mode="HTML", reply_markup=kb2
        )
    except Exception:
        pass

    # Always also send the main start message
    await update.message.reply_html(
        _start_text(mention(u)),
        reply_markup=_start_kb(me.username)
    )


async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    d = q.data
    back = [[InlineKeyboardButton("« ʙᴀᴄᴋ", callback_data="menu_back")]]

    content = {
        "menu_groups": (
            "👥 <b>ɢʀᴏᴜᴘs</b>\n\n"
            "Add Iota to your group and get:\n"
            "• Auto welcome messages\n"
            "• Group economy (/gbal /gkill /grob)\n"
            "• Admin tools (.warn .ban .mute)\n"
            "• Group protection (anti-spam, flood)\n"
            "• Card tournaments & games\n\n"
            "➕ Add Iota → t.me/IotaBot?startgroup=start\n"
            "/claim — Claim group reward ($10k+)"
        ),
        "menu_promoter": (
            "🤝 <b>ᴘʀᴏᴍᴏᴛᴇʀ ꜱʏꜱᴛᴇᴍ</b>\n\n"
            "Earn coins by referring friends!\n\n"
            "💰 Per referral: +500 coins\n"
            "💎 Premium referral: +2000 coins\n\n"
            "Commands:\n"
            "/promoter — Get your referral link\n"
            "/ref_stats — Check your earnings\n"
            "/refer_top — Top promoters"
        ),
        "menu_friends": (
            "🧸 <b>ꜰʀɪᴇɴᴅꜱ & ꜱᴏᴄɪᴀʟ</b>\n\n"
            "/slap /punch /kiss /hug /bite\n"
            "/murder /couples /crush /love /ship\n"
            "/compliment /roast /truth /dare\n"
            "/puzzle /shayari /meme\n\n"
            "/valentine — Valentine event\n"
            "/last_seen <user_id> — Check last active"
        ),
        "menu_games": (
            "🎮 <b>ɢᴀᴍᴇꜱ</b>\n\n"
            "🃏 /card — Card Game\n"
            "💣 /bomb — Bomb Passing\n"
            "🎭 /bluff — Bluff Game\n"
            "💻 /hack — Password Hacking\n"
            "📝 /wordgame — Word Guess\n"
            "🧩 /hangman — Hangman\n"
            "❓ /quiz — AI Quiz\n"
            "⭕ /tictactoe — Tic Tac Toe\n"
            "✊ /rps — Rock Paper Scissors\n"
            "🎲 /ludo — Ludo Game\n"
            "🏆 /leaders — Leaderboard"
        ),
        "menu_back": None
    }

    if d == "menu_back":
        me = await context.bot.get_me()
        await q.edit_message_text(
            _start_text(""),
            parse_mode="HTML",
            reply_markup=_start_kb(me.username)
        ); return

    if d in content and content[d]:
        await q.edit_message_text(
            content[d], parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(back)
        )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    me = await context.bot.get_me()
    await update.message.reply_html(
        f"✨ <b>ʜᴇʟʟᴏ {mention(u)}! ɪ'ᴍ ɪᴏᴛᴀ!</b> ✨\n"
        f"ɪ'ᴍ ʏᴏᴜʀ ᴘᴇʀsᴏɴᴀʟ ᴀɪ ʙᴇsᴛɪᴇ, ᴍᴏᴅᴇʀᴀᴛᴏʀ & ᴇᴄᴏɴᴏᴍʏ ʙᴏᴛ!\n\n"
        "🌟 <b>Most Used:</b>\n"
        "/daily /bal /rob /kill /profile\n"
        "/collect /attack /ai /shop\n\n"
        "🛡️ <b>ᴀᴅᴍɪɴ (. or ! prefix):</b>\n"
        "<code>.warn .unwarn .warns</code>\n"
        "<code>.mute .imute .dmute .unmute</code>\n"
        "<code>.ban .dban .unban .kick</code>\n"
        "<code>.promote .demote .demote_all</code>\n"
        "<code>.add .remove .title .pin .unpin .d</code>\n\n"
        "👇 Tap below for all commands:",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 Economy",  callback_data="menu_economy"),
             InlineKeyboardButton("🎮 Games",    callback_data="menu_games")],
            [InlineKeyboardButton("🏰 Village",  callback_data="menu_village"),
             InlineKeyboardButton("😂 Fun",      callback_data="menu_friends")],
            [InlineKeyboardButton("🤖 AI Chat",  callback_data="menu_ai"),
             InlineKeyboardButton("🤝 Promoter", callback_data="menu_promoter")],
        ])
    )
