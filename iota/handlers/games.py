"""
Iota Bot — Games Handler
Card game with:
  • GIF result (like Baka bot)
  • Tie → normal users eliminated, premium share prize
  • Streak tracking
  • Card rank update
  • 5% fee (premium exempt)
  • XP gain
"""
import random, uuid, asyncio, json
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.mongo_db import (
    ensure_user, get_user, update_user, add_balance, deduct_balance,
    get_card_rank, update_card_rank, get_card_leaders, get_card_rank_position,
    is_gaming_open, set_gaming_status
)
from utils.helpers import mention, mention_id, fmt, xp_level, rank_title
from config import GIFS, CARD_FEE_PERCENT, CARD_XP_WIN, CARD_XP_LOSS, ITEMS

# ── In-memory game state (card games) ────────────────────────────────────────
_card_games: dict = {}   # game_id -> game dict
_bomb_games: dict = {}
_bluff_games: dict = {}
_hack_games: dict = {}
_word_games: dict = {}

WORD_LIST = [
    "python","telegram","robot","galaxy","empire","warrior","castle",
    "diamond","battle","legend","rocket","thunder","jungle","phantom",
    "dragon","knight","silver","golden","sunrise","victory",
]


async def game_menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📖 View All Games", callback_data="game_list")
    ]])
    await update.message.reply_html(
        "🎮 Cʟɪᴄᴋ Tʜᴇ Bᴜᴛᴛᴏɴ Bᴇʟᴏᴡ Tᴏ Kɴᴏᴡ Aʙᴏᴜᴛ Iᴏᴛᴀ Mɪɴɪ Gᴀᴍᴇꜱ.",
        reply_markup=kb
    )


async def game_list_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "game_list":
        await q.edit_message_text(
            "🎮 <b>Iota Mini Games</b>\n\n"
            "🃏 /card — Card Game (4 rounds)\n"
            "🃏 /bet <amount> — Card Game with Bet\n"
            "💣 /bomb — Bomb Passing Game\n"
            "🎭 /bluff — Bluff Card Game\n"
            "💻 /hack — Hack the Code\n"
            "📝 /wordgame — Word Guess\n"
            "🎲 /ludo — Ludo\n"
            "🏆 /leaders — Card Leaderboard\n"
            "📊 /rank — Your card rank\n\n"
            "Admin: /open | /close",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="game_back")]])
        )
    elif q.data == "game_back":
        await q.edit_message_text(
            "🎮 Cʟɪᴄᴋ Tʜᴇ Bᴜᴛᴛᴏɴ Bᴇʟᴏᴡ Tᴏ Kɴᴏᴡ Aʙᴏᴜᴛ Iᴏᴛᴀ Mɪɴɪ Gᴀᴍᴇꜱ.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📖 View All Games", callback_data="game_list")]])
        )


async def open_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_html("🚫 Yᴏᴜ Cᴀɴ Uꜱᴇ Tʜᴇꜱᴇ Cᴏᴍᴍᴀɴᴅꜱ Iɴ Gʀᴏᴜᴘꜱ Oɴʟʏ."); return
    from utils.helpers import is_admin
    if not await is_admin(update, context):
        await update.message.reply_html("❌ Admins only!"); return
    await set_gaming_status(chat.id, True)
    await update.message.reply_html(
        "💚 <b>Gaming Commands OPENED!</b>\n\nAll mini games are now available."
    )


async def close_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_html("🚫 Yᴏᴜ Cᴀɴ Uꜱᴇ Tʜᴇꜱᴇ Cᴏᴍᴍᴀɴᴅꜱ Iɴ Gʀᴏᴜᴘꜱ Oɴʟʏ."); return
    from utils.helpers import is_admin
    if not await is_admin(update, context):
        await update.message.reply_html("❌ Admins only!"); return
    await set_gaming_status(chat.id, False)
    await update.message.reply_html(
        "🔴 <b>Gaming Commands CLOSED!</b>\n\nMini games disabled for now."
    )


# ── /leaders ──────────────────────────────────────────────────────────────────

async def leaders_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows   = await get_card_leaders(10)
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text   = "🏆 <b>Bᴀᴋᴀ Cᴏɪɴ Tᴏᴜʀɴᴀᴍᴇɴᴛ — Lᴇᴀᴅᴇʀʙᴏᴀʀᴅ</b>\n\n"
    for i, r in enumerate(rows):
        try:
            u = await context.bot.get_chat(r["_id"])
            name = u.first_name
        except Exception:
            name = str(r["_id"])
        text += (
            f"{medals[i]} <b>{name}</b>\n"
            f"   🏅 Wins: {r['wins']} | 💸 Lost: {r['losses']}\n"
            f"   💰 Won: {fmt(r['won_amount'])} | 🔥 Streak: {r['best_streak']}\n\n"
        )
    if not rows:
        text += "No games played yet!"
    await update.message.reply_html(text)


# ═══════════════════════════════════════════════════════
#  CARD GAME — Full Baka-style
# ═══════════════════════════════════════════════════════

def _gen_hand():
    """4 hidden cards with random values 1-10."""
    return [random.randint(1, 10) for _ in range(4)]


async def card_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u    = update.effective_user
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_html("🎮 Yᴏᴜ Cᴀɴ Pʟᴀʏ Tʜᴇ Cᴀʀᴅ Gᴀᴍᴇ Iɴ Gʀᴏᴜᴘ Oɴʟʏ."); return
    if not await is_gaming_open(chat.id):
        await update.message.reply_html("🔴 Gaming is closed in this group! Admin: /open"); return

    await ensure_user(u.id, u.username or "", u.full_name)
    gid = str(uuid.uuid4())[:8]
    _card_games[gid] = {
        "chat_id": chat.id, "player1": u.id, "player2": 0,
        "bet": 0, "p1_cards": [], "p2_cards": [],
        "p1_choices": {}, "p2_choices": {},
        "round": 1, "score1": 0, "score2": 0,
        "status": "waiting"
    }
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🃏 Join Game", callback_data=f"card_join_{gid}"),
        InlineKeyboardButton("❌ Cancel",    callback_data=f"card_cancel_{gid}"),
    ]])
    await update.message.reply_html(
        f"🃏 <b>Cᴀʀᴅ Gᴀᴍᴇ</b>\n\n"
        f"Host: {mention(u)}\n"
        f"💰 Bet: Free\n\n"
        f"Waiting for player 2...",
        reply_markup=kb
    )


async def bet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u    = update.effective_user
    chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_html("🎮 Yᴏᴜ Cᴀɴ Pʟᴀʏ Tʜᴇ Cᴀʀᴅ Gᴀᴍᴇ Iɴ Gʀᴏᴜᴘ Oɴʟʏ."); return
    if not await is_gaming_open(chat.id):
        await update.message.reply_html("🔴 Gaming is closed!"); return

    if not context.args:
        await update.message.reply_html("❌ Usage: /bet <amount>"); return
    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_html("❌ Invalid amount!"); return
    if amount <= 0:
        await update.message.reply_html("❌ Amount must be positive!"); return

    await ensure_user(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)
    if d["balance"] < amount:
        await update.message.reply_html(
            f"❌ Need {fmt(amount)}, you have {fmt(d['balance'])}"
        ); return

    gid = str(uuid.uuid4())[:8]
    _card_games[gid] = {
        "chat_id": chat.id, "player1": u.id, "player2": 0,
        "bet": amount, "p1_cards": [], "p2_cards": [],
        "p1_choices": {}, "p2_choices": {},
        "round": 1, "score1": 0, "score2": 0,
        "status": "waiting"
    }
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"🃏 Join (Bet: {fmt(amount)})", callback_data=f"card_join_{gid}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"card_cancel_{gid}"),
    ]])
    await update.message.reply_html(
        f"🃏 <b>Cᴀʀᴅ Gᴀᴍᴇ</b>\n\n"
        f"Host: {mention(u)}\n"
        f"💰 Bet: <b>{fmt(amount)}</b>\n\n"
        f"Waiting for opponent...",
        reply_markup=kb
    )


async def flip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "❓ Use the buttons inside the card game to flip!\nStart a game: /card or /bet <amount>"
    )


async def card_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q   = update.callback_query
    u   = q.from_user
    data = q.data
    await q.answer()

    # ── JOIN ──────────────────────────────────────────────────────────────────
    if data.startswith("card_join_"):
        gid  = data[len("card_join_"):]
        game = _card_games.get(gid)
        if not game:
            await q.edit_message_text("❌ Game expired!"); return
        if game["status"] != "waiting":
            await q.answer("Game already started!", show_alert=True); return
        if game["player1"] == u.id:
            await q.answer("You created this game!", show_alert=True); return

        await ensure_user(u.id, u.username or "", u.full_name)
        p1d = await get_user(game["player1"])
        p2d = await get_user(u.id)
        bet = game["bet"]

        # Deduct bets
        if bet > 0:
            if p2d["balance"] < bet:
                await q.answer("Not enough balance!", show_alert=True); return
            if p1d["balance"] < bet:
                await q.answer("Host doesn't have enough balance!", show_alert=True); return
            await update_user(game["player1"], balance=p1d["balance"] - bet)
            await update_user(u.id, balance=p2d["balance"] - bet)

        game["player2"]   = u.id
        game["p1_cards"]  = _gen_hand()
        game["p2_cards"]  = _gen_hand()
        game["status"]    = "playing"
        _card_games[gid]  = game

        try:
            p1u = await context.bot.get_chat(game["player1"])
            p1_name = p1u.first_name
        except Exception:
            p1_name = "Player1"

        kb = _card_buttons(gid)
        await q.edit_message_text(
            f"🃏 <b>Cᴀʀᴅ Gᴀᴍᴇ Sᴛᴀʀᴛᴇᴅ!</b>\n\n"
            f"⚔️ {p1_name} vs {u.first_name}\n"
            f"💰 Bet: {fmt(bet)}\n\n"
            f"🔵 Round <b>1 / 4</b>\n"
            f"Choose your card (A/B/C/D):",
            parse_mode="HTML",
            reply_markup=kb
        )
        return

    # ── CANCEL ────────────────────────────────────────────────────────────────
    if data.startswith("card_cancel_"):
        gid  = data[len("card_cancel_"):]
        game = _card_games.pop(gid, None)
        if game and game["player1"] != u.id:
            await q.answer("Only host can cancel!", show_alert=True); return
        await q.edit_message_text("❌ Card game cancelled!")
        return

    # ── FLIP ──────────────────────────────────────────────────────────────────
    if data.startswith("card_flip_"):
        parts = data.split("_")
        # card_flip_<gid>_<card>
        card  = parts[-1]
        gid   = "_".join(parts[2:-1])
        game  = _card_games.get(gid)
        if not game or game["status"] != "playing":
            await q.answer("No active game!", show_alert=True); return
        if u.id not in (game["player1"], game["player2"]):
            await q.answer("You're not in this game!", show_alert=True); return

        is_p1   = u.id == game["player1"]
        choices = game["p1_choices"] if is_p1 else game["p2_choices"]
        rnd     = str(game["round"])

        if rnd in choices:
            await q.answer("Already chose this round!", show_alert=True); return

        card_idx = {"A":0,"B":1,"C":2,"D":3}[card]
        cards    = game["p1_cards"] if is_p1 else game["p2_cards"]
        val      = cards[card_idx]
        choices[rnd] = (card, val)

        if is_p1:
            game["p1_choices"] = choices
        else:
            game["p2_choices"] = choices

        # Both chose?
        if rnd in game["p1_choices"] and rnd in game["p2_choices"]:
            await _resolve_round(q, context, gid)
        else:
            await q.answer(f"✅ Card {card} selected! Waiting for opponent...", show_alert=False)


def _card_buttons(gid):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🅰️ A", callback_data=f"card_flip_{gid}_A"),
        InlineKeyboardButton("🅱️ B", callback_data=f"card_flip_{gid}_B"),
        InlineKeyboardButton("©️ C", callback_data=f"card_flip_{gid}_C"),
        InlineKeyboardButton("🅾️ D", callback_data=f"card_flip_{gid}_D"),
    ]])


async def _resolve_round(q, context, gid):
    game  = _card_games.get(gid)
    if not game:
        return
    rnd   = str(game["round"])
    p1c, p1v = game["p1_choices"][rnd]
    p2c, p2v = game["p2_choices"][rnd]

    if p1v > p2v:
        game["score1"] += p1v
        rnd_winner = "p1"
    elif p2v > p1v:
        game["score2"] += p2v
        rnd_winner = "p2"
    else:
        game["score1"] += p1v
        game["score2"] += p2v
        rnd_winner = "tie"

    try:
        p1u = await context.bot.get_chat(game["player1"])
        p2u = await context.bot.get_chat(game["player2"])
        p1_name = p1u.first_name
        p2_name = p2u.first_name
    except Exception:
        p1_name = "Player1"; p2_name = "Player2"

    rw_text = p1_name if rnd_winner=="p1" else (p2_name if rnd_winner=="p2" else "🤝 TIE")

    if game["round"] >= 4:
        # Game over
        await _end_game(q, context, gid, p1_name, p2_name, p1c, p1v, p2c, p2v, rw_text)
    else:
        game["round"] += 1
        _card_games[gid] = game
        kb = _card_buttons(gid)
        await q.edit_message_text(
            f"🃏 <b>Cᴀʀᴅ Gᴀᴍᴇ</b>\n\n"
            f"Round {rnd} result:\n"
            f"🔵 {p1_name}: {p1c} = <b>{p1v}</b>\n"
            f"🔴 {p2_name}: {p2c} = <b>{p2v}</b>\n"
            f"Round Winner: <b>{rw_text}</b>\n\n"
            f"Score — {p1_name}: {game['score1']} | {p2_name}: {game['score2']}\n\n"
            f"🔵 Round <b>{game['round']} / 4</b> — Choose your card:",
            parse_mode="HTML",
            reply_markup=kb
        )


async def _end_game(q, context, gid, p1_name, p2_name, p1c, p1v, p2c, p2v, rw_text):
    game = _card_games.pop(gid, None)
    if not game:
        return

    s1 = game["score1"]; s2 = game["score2"]
    bet = game["bet"]
    p1_id = game["player1"]; p2_id = game["player2"]

    p1d = await get_user(p1_id)
    p2d = await get_user(p2_id)
    cr1 = await get_card_rank(p1_id)
    cr2 = await get_card_rank(p2_id)

    is_tie = (s1 == s2)

    if is_tie:
        # Tie logic (like Baka): normal users eliminated, premium share
        p1_prem = p1d["is_premium"]
        p2_prem = p2d["is_premium"]

        if p1_prem and p2_prem:
            # Both premium: split prize
            prize = bet * 2 if bet > 0 else 0
            each = prize // 2
            if each > 0:
                await add_balance(p1_id, each)
                await add_balance(p2_id, each)
            tie_result_text = f"⚖️ Tɪᴇ Dᴇᴛᴇᴄᴛᴇᴅ! Nᴏʀᴍᴀʟ ᴜꜱᴇʀꜱ ᴇʟɪᴍɪɴᴀᴛᴇᴅ, Pʀᴇᴍɪᴜᴍ Pʟᴀʏᴇʀꜱ ꜱʜᴀʀᴇ Pʀɪᴢᴇ 💓"
            winner_ids = [p1_id, p2_id]
            prize_each = each
        elif p1_prem:
            winner_ids = [p1_id]; prize_each = bet*2 if bet else 0
            if prize_each: await add_balance(p1_id, prize_each)
            tie_result_text = f"⚖️ Tɪᴇ! Nᴏʀᴍᴀʟ ᴜꜱᴇʀ ᴇʟɪᴍɪɴᴀᴛᴇᴅ, Pʀᴇᴍɪᴜᴍ Wɪɴꜱ 💓"
        elif p2_prem:
            winner_ids = [p2_id]; prize_each = bet*2 if bet else 0
            if prize_each: await add_balance(p2_id, prize_each)
            tie_result_text = f"⚖️ Tɪᴇ! Nᴏʀᴍᴀʟ ᴜꜱᴇʀ ᴇʟɪᴍɪɴᴀᴛᴇᴅ, Pʀᴇᴍɪᴜᴍ Wɪɴꜱ 💓"
        else:
            # Both normal: random winner
            winner_id = random.choice([p1_id, p2_id])
            winner_ids = [winner_id]; prize_each = bet*2 if bet else 0
            if prize_each: await add_balance(winner_id, prize_each)
            tie_result_text = f"⚖️ Tɪᴇ! Rᴀɴᴅᴏᴍ Wɪɴɴᴇʀ Sᴇʟᴇᴄᴛᴇᴅ"

        # Card rank for tie
        for wid in winner_ids:
            cr = await get_card_rank(wid)
            new_streak = cr["streak"] + 1
            await update_card_rank(wid,
                wins=cr["wins"]+1, won_amount=cr["won_amount"]+prize_each,
                streak=new_streak,
                best_streak=max(cr["best_streak"], new_streak)
            )

        # Build result message
        winner_name = p1_name if (winner_ids[0] if len(winner_ids)==1 else 0) == p1_id else p2_name
        if len(winner_ids) == 2:
            winner_display = f"🏅 {p1_name} & {p2_name}"
        else:
            winner_display = f"👑 {winner_name}"

        result_text = (
            f"{tie_result_text}\n\n"
            f"👑 Fɪɴᴀʟ Wɪɴɴᴇʀ(ꜱ) 👑\n\n"
            f"🎿 {winner_display}\n"
            f"🎯 Pᴏɪɴᴛꜱ: {max(s1,s2)}\n"
            f"💵 Wᴏɴ: {fmt(prize_each)} (🎿 {CARD_FEE_PERCENT}% Fee)\n"
            f"🔥 Sᴛʀᴇᴀᴋ: N/A\n"
            f"⚡ Xᴘ Gᴀɪɴᴇᴅ: +{CARD_XP_WIN}\n\n"
            f"👥 Mᴇᴍʙᴇʀꜱ: 👤🎿👤👤\n\n"
            f"👉 Pʟᴀʏ Aɢᴀɪɴ Uꜱɪɴɢ : /card {bet if bet else ''}"
        )

        try:
            await context.bot.send_animation(
                game["chat_id"],
                animation=GIFS["card_tie"],
                caption=result_text,
                parse_mode="HTML"
            )
        except Exception:
            await context.bot.send_message(game["chat_id"], result_text, parse_mode="HTML")
        return

    # Normal win
    if s1 > s2:
        winner_id = p1_id; loser_id = p2_id; winner_name = p1_name; loser_name = p2_name
        winner_score = s1
    else:
        winner_id = p2_id; loser_id = p1_id; winner_name = p2_name; loser_name = p1_name
        winner_score = s2

    # Calculate prize
    prize = bet * 2 if bet > 0 else 0
    wd = await get_user(winner_id)
    fee_exempt = wd["is_premium"]
    fee = 0 if fee_exempt else int(prize * CARD_FEE_PERCENT / 100)
    net = prize - fee
    if net > 0:
        await add_balance(winner_id, net)

    # XP
    await update_user(winner_id, xp=(await get_user(winner_id))["xp"] + CARD_XP_WIN)
    await update_user(loser_id,  xp=(await get_user(loser_id))["xp"]  + CARD_XP_LOSS)

    # Card rank winner
    crw = await get_card_rank(winner_id)
    new_streak = crw["streak"] + 1
    await update_card_rank(winner_id,
        wins=crw["wins"]+1, won_amount=crw["won_amount"]+net,
        streak=new_streak,
        best_streak=max(crw["best_streak"], new_streak)
    )
    # Card rank loser
    crl = await get_card_rank(loser_id)
    await update_card_rank(loser_id,
        losses=crl["losses"]+1, lost_amount=crl["lost_amount"]+bet,
        streak=0
    )

    result_text = (
        f"👑 Fɪɴᴀʟ Wɪɴɴᴇʀ(ꜱ) 👑\n\n"
        f"🎿 {winner_name}\n"
        f"🎯 Pᴏɪɴᴛꜱ: {winner_score}\n"
        f"💵 Wᴏɴ: {fmt(net)} (🎿 {CARD_FEE_PERCENT}% Fee)\n"
        f"🔥 Sᴛʀᴇᴀᴋ: {new_streak}/{crw['best_streak']+1}\n"
        f"⚡ Xᴘ Gᴀɪɴᴇᴅ: +{CARD_XP_WIN}\n\n"
        f"👥 Mᴇᴍʙᴇʀꜱ: 👤🎿👤👤\n\n"
        f"👉 Pʟᴀʏ Aɢᴀɪɴ Uꜱɪɴɢ : /card {bet if bet else ''}"
    )

    try:
        await context.bot.send_animation(
            game["chat_id"],
            animation=GIFS["card_win"],
            caption=result_text,
            parse_mode="HTML"
        )
    except Exception:
        await context.bot.send_message(game["chat_id"], result_text, parse_mode="HTML")


# ═══════════════════════════════════════════════════════
#  BOMB GAME
# ═══════════════════════════════════════════════════════

async def bomb_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; chat = update.effective_chat
    if chat.type == "private":
        await update.message.reply_html("🎮 Gʀᴏᴜᴘ Oɴʟʏ!"); return
    await ensure_user(u.id, u.username or "", u.full_name)
    gid = str(uuid.uuid4())[:8]
    _bomb_games[gid] = {
        "chat_id": chat.id, "players": [u.id],
        "holder": u.id, "status": "waiting", "bet": 0
    }
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("💣 Join!", callback_data=f"bomb_join_{gid}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"bomb_cancel_{gid}"),
    ]])
    await update.message.reply_html(
        f"💣 <b>Bomb Game!</b>\n\nHost: {mention(u)}\n"
        f"Pass the bomb before it explodes! (30s)\nWaiting for players...",
        reply_markup=kb
    )


async def bomb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; u = q.from_user; await q.answer()

    if q.data.startswith("bomb_join_"):
        gid  = q.data[len("bomb_join_"):]
        game = _bomb_games.get(gid)
        if not game: await q.edit_message_text("❌ Expired!"); return
        if u.id in game["players"]: await q.answer("Already joined!", show_alert=True); return
        game["players"].append(u.id)
        if len(game["players"]) >= 2:
            game["status"] = "playing"
            _bomb_games[gid] = game
            names = []
            for pid in game["players"]:
                try:
                    c = await context.bot.get_chat(pid)
                    names.append(c.first_name)
                except: names.append(str(pid))
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("💣 Pass Bomb!", callback_data=f"bomb_pass_{gid}")
            ]])
            await q.edit_message_text(
                f"💣 <b>Bomb Game Started!</b>\nPlayers: {', '.join(names)}\n\n"
                f"🔥 <b>{names[0]}</b> has the bomb!\n⏱️ 30 seconds!",
                parse_mode="HTML", reply_markup=kb
            )
            asyncio.create_task(_bomb_explode(context, gid, game["chat_id"]))
        else:
            await q.edit_message_text(
                f"💣 Waiting... {len(game['players'])} player(s) joined.",
                reply_markup=q.message.reply_markup
            )

    elif q.data.startswith("bomb_pass_"):
        gid  = q.data[len("bomb_pass_"):]
        game = _bomb_games.get(gid)
        if not game or game["status"] != "playing":
            await q.answer("No active game!", show_alert=True); return
        if u.id != game["holder"]:
            await q.answer("You don't have the bomb! 💣", show_alert=True); return
        idx  = game["players"].index(u.id)
        nxt  = game["players"][(idx+1) % len(game["players"])]
        game["holder"] = nxt; _bomb_games[gid] = game
        try:
            nc = await context.bot.get_chat(nxt)
            nname = nc.first_name
        except: nname = str(nxt)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("💣 Pass Bomb!", callback_data=f"bomb_pass_{gid}")
        ]])
        await q.edit_message_text(
            f"💣 <b>Bomb Game!</b>\n🔥 <b>{nname}</b> has the bomb!\n⏱️ 30 seconds!",
            parse_mode="HTML", reply_markup=kb
        )

    elif q.data.startswith("bomb_cancel_"):
        gid = q.data[len("bomb_cancel_"):]
        _bomb_games.pop(gid, None)
        await q.edit_message_text("❌ Bomb game cancelled!")


async def _bomb_explode(context, gid, chat_id):
    await asyncio.sleep(30)
    game = _bomb_games.pop(gid, None)
    if not game or game["status"] != "playing": return
    try:
        hc = await context.bot.get_chat(game["holder"])
        hname = hc.first_name
    except: hname = str(game["holder"])
    try:
        await context.bot.send_message(
            chat_id,
            f"💥 <b>BOOM!</b>\n💀 <b>{hname}</b> got blown up! Everyone else survives! 🎉",
            parse_mode="HTML"
        )
    except: pass


# ═══════════════════════════════════════════════════════
#  BLUFF GAME
# ═══════════════════════════════════════════════════════

async def bluff_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; chat = update.effective_chat
    if chat.type == "private": await update.message.reply_html("🎮 Group only!"); return
    await ensure_user(u.id, u.username or "", u.full_name)
    gid = str(uuid.uuid4())[:8]
    _bluff_games[gid] = {
        "player1": u.id, "player2": 0,
        "p1_card": random.randint(1,13), "p2_card": 0,
        "status": "waiting", "chat_id": chat.id
    }
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🎭 Join Bluff!", callback_data=f"bluff_join_{gid}"),
        InlineKeyboardButton("❌ Cancel", callback_data=f"bluff_cancel_{gid}"),
    ]])
    await update.message.reply_html(
        f"🎭 <b>Bluff Game!</b>\nHost: {mention(u)}\n\nEach player gets a secret card!\nWaiting...",
        reply_markup=kb
    )


async def bluff_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; u = q.from_user; await q.answer()
    if q.data.startswith("bluff_join_"):
        gid  = q.data[len("bluff_join_"):]
        game = _bluff_games.get(gid)
        if not game or game["status"] != "waiting": await q.edit_message_text("❌ Game gone!"); return
        if game["player1"] == u.id: await q.answer("You created this!", show_alert=True); return
        game["player2"] = u.id; game["p2_card"] = random.randint(1,13); game["status"] = "playing"
        p1 = await context.bot.get_chat(game["player1"])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Reveal", callback_data=f"bluff_reveal_{gid}"),
            InlineKeyboardButton("🤥 Bluff!",  callback_data=f"bluff_bluff_{gid}"),
        ]])
        await q.edit_message_text(
            f"🎭 <b>Bluff Game!</b>\n{p1.first_name} vs {u.first_name}\n\nCards dealt! Reveal or Bluff?",
            parse_mode="HTML", reply_markup=kb
        )
    elif q.data.startswith("bluff_reveal_") or q.data.startswith("bluff_bluff_"):
        action = "reveal" if "reveal" in q.data else "bluff"
        gid    = q.data.split(f"bluff_{action}_")[1]
        game   = _bluff_games.pop(gid, None)
        if not game: return
        p1 = await context.bot.get_chat(game["player1"])
        p2 = await context.bot.get_chat(game["player2"])
        if action == "reveal":
            winner = p1 if game["p1_card"]>game["p2_card"] else p2
            await q.edit_message_text(
                f"🎭 Reveal!\n{p1.first_name}: {game['p1_card']} | {p2.first_name}: {game['p2_card']}\n🏆 Winner: <b>{winner.first_name}</b>!",
                parse_mode="HTML"
            )
        else:
            win = random.random() < 0.5
            if win:
                await q.edit_message_text(f"🤥 Bluff success! {u.first_name} wins!", parse_mode="HTML")
            else:
                other = p1 if u.id==game["player2"] else p2
                await q.edit_message_text(f"🚫 Bluff caught! {other.first_name} wins!", parse_mode="HTML")
    elif q.data.startswith("bluff_cancel_"):
        gid = q.data[len("bluff_cancel_"):]
        _bluff_games.pop(gid, None)
        await q.edit_message_text("❌ Cancelled!")


# ═══════════════════════════════════════════════════════
#  HACK GAME
# ═══════════════════════════════════════════════════════

async def hack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    gid    = str(uuid.uuid4())[:8]
    secret = random.randint(1000, 9999)
    reward = random.randint(500, 3000)
    _hack_games[gid] = {"player": u.id, "secret": secret, "attempts": 0, "max": 5, "reward": reward}
    context.chat_data[f"hack_{gid}"] = ""
    await update.message.reply_html(
        f"💻 <b>Hack The System!</b>\n{mention(u)}\n\nGuess the 4-digit code!\n"
        f"Attempts: 0/5 | 💰 Reward: {fmt(reward)}\n\nInput: <code>____</code>",
        reply_markup=_hack_kb(gid)
    )


def _hack_kb(gid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("1️⃣",callback_data=f"hack_d_{gid}_1"),
         InlineKeyboardButton("2️⃣",callback_data=f"hack_d_{gid}_2"),
         InlineKeyboardButton("3️⃣",callback_data=f"hack_d_{gid}_3"),
         InlineKeyboardButton("4️⃣",callback_data=f"hack_d_{gid}_4")],
        [InlineKeyboardButton("5️⃣",callback_data=f"hack_d_{gid}_5"),
         InlineKeyboardButton("6️⃣",callback_data=f"hack_d_{gid}_6"),
         InlineKeyboardButton("7️⃣",callback_data=f"hack_d_{gid}_7"),
         InlineKeyboardButton("8️⃣",callback_data=f"hack_d_{gid}_8")],
        [InlineKeyboardButton("9️⃣",callback_data=f"hack_d_{gid}_9"),
         InlineKeyboardButton("0️⃣",callback_data=f"hack_d_{gid}_0"),
         InlineKeyboardButton("⌫", callback_data=f"hack_del_{gid}"),
         InlineKeyboardButton("✅ Enter",callback_data=f"hack_sub_{gid}")],
    ])


async def hack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; u = q.from_user; await q.answer()
    parts = q.data.split("_")

    if q.data.startswith("hack_d_"):
        # hack_d_<gid>_<digit>
        digit = parts[-1]; gid = "_".join(parts[2:-1])
        game  = _hack_games.get(gid)
        if not game or game["player"] != u.id: return
        cur = context.chat_data.get(f"hack_{gid}", "")
        if len(cur) < 4: cur += digit
        context.chat_data[f"hack_{gid}"] = cur
        display = cur.ljust(4,"_")
        await q.edit_message_text(
            f"💻 <b>Hack The System!</b>\nAttempts: {game['attempts']}/5 | 💰 {fmt(game['reward'])}\n"
            f"Input: <code>{display}</code>",
            parse_mode="HTML", reply_markup=_hack_kb(gid)
        )
    elif q.data.startswith("hack_del_"):
        gid = q.data[len("hack_del_"):]
        game = _hack_games.get(gid)
        if not game or game["player"] != u.id: return
        cur = context.chat_data.get(f"hack_{gid}", "")[:-1]
        context.chat_data[f"hack_{gid}"] = cur
        await q.edit_message_text(
            f"💻 <b>Hack The System!</b>\nInput: <code>{cur.ljust(4,'_')}</code>",
            parse_mode="HTML", reply_markup=_hack_kb(gid)
        )
    elif q.data.startswith("hack_sub_"):
        gid = q.data[len("hack_sub_"):]
        game = _hack_games.get(gid)
        if not game or game["player"] != u.id: return
        cur = context.chat_data.get(f"hack_{gid}", "")
        if len(cur) != 4: await q.answer("Enter 4 digits!", show_alert=True); return
        guess = int(cur); secret = game["secret"]; game["attempts"] += 1
        context.chat_data[f"hack_{gid}"] = ""
        if guess == secret:
            _hack_games.pop(gid)
            await add_balance(u.id, game["reward"])
            await q.edit_message_text(
                f"💻 ✅ <b>HACKED!</b>\nCode: {secret}\nAttempts: {game['attempts']}\n💰 +{fmt(game['reward'])}",
                parse_mode="HTML"
            )
        elif game["attempts"] >= game["max"]:
            _hack_games.pop(gid)
            await q.edit_message_text(
                f"💻 ❌ <b>FAILED!</b>\nCode was: <b>{secret}</b>",
                parse_mode="HTML"
            )
        else:
            hint = sum(1 for a,b in zip(str(guess).zfill(4),str(secret).zfill(4)) if a==b)
            await q.edit_message_text(
                f"💻 ❌ Wrong! Hint: <b>{hint}/4</b> digits correct\n"
                f"Attempts: {game['attempts']}/5 | Input: <code>____</code>",
                parse_mode="HTML", reply_markup=_hack_kb(gid)
            )


# ── ludo / wordgame ────────────────────────────────────────────────────────────

async def ludo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await update.message.reply_html("Yᴏᴜ Cᴀɴ Pʟᴀʏ Tʜᴇ Lᴜᴅᴏ Gᴀᴍᴇ Iɴ Gʀᴏᴜᴘ Oɴʟʏ."); return
    await update.message.reply_html("🎲 Ludo mini app coming soon! Stay tuned 👀")


async def wordgame_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; chat = update.effective_chat
    await ensure_user(u.id, u.username or "", u.full_name)
    word   = random.choice(WORD_LIST)
    reward = len(word) * 200
    _word_games[chat.id] = {"word": word, "masked": list("_"*len(word)), "reward": reward, "attempts": 6}
    await update.message.reply_html(
        f"📝 <b>Word Game!</b>\nHost: {mention(u)}\n💰 Reward: {fmt(reward)}\n\n"
        f"Word: <code>{' '.join('_'*len(word))}</code>  ({len(word)} letters)\n"
        f"Attempts: 6\n\nReply with a single letter!"
    )


async def wordgame_letter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; u = update.effective_user
    game = _word_games.get(chat.id)
    if not game: return
    text = (update.message.text or "").strip().lower()
    if len(text) != 1 or not text.isalpha(): return
    word = game["word"]; masked = game["masked"]
    if text in word:
        for i, ch in enumerate(word):
            if ch == text: masked[i] = text
        game["masked"] = masked
        if "_" not in masked:
            _word_games.pop(chat.id, None)
            await add_balance(u.id, game["reward"])
            await update.message.reply_html(
                f"🎉 {mention(u)} guessed: <b>{word}</b>!\n💰 +{fmt(game['reward'])}"
            )
        else:
            await update.message.reply_html(
                f"✅ '{text}' found!\n<code>{' '.join(masked)}</code>\nAttempts: {game['attempts']}"
            )
    else:
        game["attempts"] -= 1
        if game["attempts"] <= 0:
            _word_games.pop(chat.id, None)
            await update.message.reply_html(f"❌ Game over! Word: <b>{word}</b>")
        else:
            await update.message.reply_html(
                f"❌ '{text}' not in word!\n<code>{' '.join(masked)}</code>\nAttempts: {game['attempts']}"
            )
