"""
╔══════════════════════════════════════════════════════════════════╗
║   IOTA BOT — Werewolf (social deduction, original)                 ║
║                                                                      ║
║   Host: /werewolf         — open a 90-second lobby (5-10 players)  ║
║   Join: /join              — join during the lobby window          ║
║                                                                      ║
║   ROLES (auto-assigned, sent privately via DM):                    ║
║     🐺 Werewolf  — 1 per 4 players (min 1). Each night, werewolves ║
║                    secretly vote together to eliminate a villager. ║
║     🔮 Seer       — 1 (if 5+ players). Each night, may secretly    ║
║                    check one player's true role.                   ║
║     💉 Doctor      — 1 (if 6+ players). Each night, may protect one ║
║                    player from being eliminated.                    ║
║     👤 Villager     — everyone else. No night action — survive by  ║
║                    working out who the werewolves are.              ║
║                                                                      ║
║   FLOW: Night phase (60s, DMs) → Day phase (90s, group vote via     ║
║   /vote) → repeat until werewolves are all eliminated (villagers    ║
║   win) or werewolves equal/outnumber villagers (werewolves win).    ║
║                                                                      ║
║   Requires each player to have DM'd the bot at least once before    ║
║   (a Telegram platform requirement for any bot DM) — Iota tells      ║
║   anyone who hasn't exactly what to do instead of silently failing. ║
╚══════════════════════════════════════════════════════════════════╝
"""
import asyncio
import logging
import random
import time
import uuid

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from utils.mongo_db import ensure_user, add_balance
from utils.helpers import mention, fmt
from utils.safe_html import safe_html
from utils.system_gate import games_gate
from utils.game_ui import send_gif_result

logger = logging.getLogger(__name__)

LOBBY_SECONDS = 90
NIGHT_SECONDS = 60
DAY_SECONDS   = 90
MIN_PLAYERS   = 5
MAX_PLAYERS   = 10

# chat_id -> state
_ww_lobbies: dict = {}   # pre-game, collecting /join
_ww_games:   dict = {}   # active games


def _role_counts(n: int) -> dict:
    """How many of each role for `n` players."""
    werewolves = max(1, n // 4)
    seer   = 1 if n >= 5 else 0
    doctor = 1 if n >= 6 else 0
    villagers = n - werewolves - seer - doctor
    return {"werewolf": werewolves, "seer": seer, "doctor": doctor, "villager": villagers}


def _new_lobby(chat_id: int, host_id: int, host_name: str) -> dict:
    return {
        "host_id": host_id,
        "players": [{"id": host_id, "name": safe_html(host_name)}],
        "opened_at": int(time.time()),
    }


# ── /werewolf — open lobby ───────────────────────────────────────────────

@games_gate
async def werewolf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    u = update.effective_user
    if chat.type == "private":
        await update.message.reply_html("🐺 Werewolf sirf group mein khela ja sakta hai!"); return
    if chat.id in _ww_lobbies or chat.id in _ww_games:
        await update.message.reply_html("❌ Pehle se ek Werewolf game/lobby active hai!"); return

    await ensure_user(u.id, u.username or "", u.full_name)
    lobby = _new_lobby(chat.id, u.id, u.first_name)
    _ww_lobbies[chat.id] = lobby

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🐺 Join ({len(lobby['players'])}/{MAX_PLAYERS})", callback_data=f"ww_join_{chat.id}")],
        [InlineKeyboardButton("▶️ Start Now", callback_data=f"ww_start_{chat.id}")],
    ])
    await update.message.reply_html(
        f"🐺 <b>Werewolf lobby opened by {mention(u)}!</b>\n\n"
        f"A social deduction game — werewolves hide among villagers and "
        f"strike at night. Can the village find them before it's too late?\n\n"
        f"👥 Players ({len(lobby['players'])}/{MAX_PLAYERS}):\n• {mention(u)}\n\n"
        f"⏱️ Lobby closes in {LOBBY_SECONDS}s, or tap <b>Start Now</b> once "
        f"{MIN_PLAYERS}+ have joined.\n"
        f"💡 You must have DM'd me before (send /start in my DM) to receive "
        f"your secret role!",
        reply_markup=kb
    )
    asyncio.create_task(_lobby_timeout(context, chat.id))


async def _lobby_timeout(context, chat_id):
    await asyncio.sleep(LOBBY_SECONDS)
    lobby = _ww_lobbies.get(chat_id)
    if not lobby:
        return  # already started or cancelled
    if len(lobby["players"]) < MIN_PLAYERS:
        _ww_lobbies.pop(chat_id, None)
        try:
            await context.bot.send_message(
                chat_id,
                f"🐺 Werewolf lobby closed — not enough players "
                f"({len(lobby['players'])}/{MIN_PLAYERS} minimum). Try /werewolf again!",
                parse_mode="HTML"
            )
        except Exception:
            pass
        return
    await _start_game(context, chat_id)


async def werewolf_end_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/wwend — host (or bot owner) can cancel a lobby or an in-progress game."""
    chat = update.effective_chat
    u = update.effective_user

    lobby = _ww_lobbies.get(chat.id)
    if lobby:
        if u.id != lobby["host_id"]:
            await update.message.reply_html("❌ Sirf host lobby cancel kar sakta hai!"); return
        _ww_lobbies.pop(chat.id, None)
        await update.message.reply_html("🐺 Werewolf lobby cancelled."); return

    game = _ww_games.get(chat.id)
    if not game:
        await update.message.reply_html("❌ Koi active Werewolf game nahi hai!"); return
    # Any original lobby host info isn't kept on the game object, so allow
    # any surviving player to call for an end (with a confirmation-style
    # message) — this avoids the game getting stuck forever if the host
    # goes inactive mid-game, while still requiring a real player (not a
    # random bystander) to trigger it.
    if u.id not in game["players"]:
        await update.message.reply_html("❌ Sirf players game end kar sakte hain!"); return

    _ww_games.pop(chat.id, None)
    reveal = "\n".join(f"• {p['name']} — {_role_label(p['role'])}" for p in game["players"].values())
    await update.message.reply_html(
        f"🐺 <b>Game ended early by {mention(u)}.</b>\n\n"
        f"🎭 Roles were:\n{reveal}",
    )


async def werewolf_join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Text-command alternative to tapping the Join button (mirrors /enter for /bluff)."""
    chat = update.effective_chat
    u = update.effective_user
    lobby = _ww_lobbies.get(chat.id)
    if not lobby:
        await update.message.reply_html("❌ No Werewolf lobby is open right now. Host one with /werewolf!"); return
    if any(p["id"] == u.id for p in lobby["players"]):
        await update.message.reply_html("You already joined!"); return
    if len(lobby["players"]) >= MAX_PLAYERS:
        await update.message.reply_html("❌ Lobby is full!"); return
    await ensure_user(u.id, u.username or "", u.full_name)
    lobby["players"].append({"id": u.id, "name": safe_html(u.first_name)})
    await update.message.reply_html(
        f"🐺 {mention(u)} joined! ({len(lobby['players'])}/{MAX_PLAYERS})"
    )


async def werewolf_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    u = q.from_user
    parts = q.data.split("_")
    action, chat_id = parts[1], int(parts[2])

    if action == "join":
        lobby = _ww_lobbies.get(chat_id)
        if not lobby:
            await q.answer("Lobby expired or game already started!", show_alert=True); return
        if any(p["id"] == u.id for p in lobby["players"]):
            await q.answer("You already joined!"); return
        if len(lobby["players"]) >= MAX_PLAYERS:
            await q.answer("Lobby is full!", show_alert=True); return
        await ensure_user(u.id, u.username or "", u.full_name)
        lobby["players"].append({"id": u.id, "name": safe_html(u.first_name)})
        await q.answer("Joined! 🐺")
        names = "\n".join(f"• {mention_from_dict(p)}" for p in lobby["players"])
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"🐺 Join ({len(lobby['players'])}/{MAX_PLAYERS})", callback_data=f"ww_join_{chat_id}")],
            [InlineKeyboardButton("▶️ Start Now", callback_data=f"ww_start_{chat_id}")],
        ])
        try:
            await q.edit_message_text(
                f"🐺 <b>Werewolf lobby!</b>\n\n"
                f"👥 Players ({len(lobby['players'])}/{MAX_PLAYERS}):\n{names}\n\n"
                f"⏱️ Tap <b>Start Now</b> once {MIN_PLAYERS}+ have joined.",
                parse_mode="HTML", reply_markup=kb
            )
        except Exception:
            pass

    elif action == "start":
        lobby = _ww_lobbies.get(chat_id)
        if not lobby:
            await q.answer("Lobby expired or game already started!", show_alert=True); return
        if u.id != lobby["host_id"]:
            await q.answer("Only the host can start early!", show_alert=True); return
        if len(lobby["players"]) < MIN_PLAYERS:
            await q.answer(f"Need at least {MIN_PLAYERS} players!", show_alert=True); return
        await q.answer("Starting! 🐺")
        await _start_game(context, chat_id)


def mention_from_dict(p: dict) -> str:
    return f'<a href="tg://user?id={p["id"]}">{p["name"]}</a>'


# ── Game start: assign roles, DM everyone ──────────────────────────────────

async def _start_game(context, chat_id):
    lobby = _ww_lobbies.pop(chat_id, None)
    if not lobby:
        return
    players = lobby["players"]
    n = len(players)
    counts = _role_counts(n)

    roles = (["werewolf"] * counts["werewolf"] +
             ["seer"] * counts["seer"] +
             ["doctor"] * counts["doctor"] +
             ["villager"] * counts["villager"])
    random.shuffle(roles)

    game_players = {}
    dm_failed = []
    for p, role in zip(players, roles):
        game_players[p["id"]] = {
            "id": p["id"], "name": p["name"], "role": role, "alive": True,
        }

    game = {
        "id": str(uuid.uuid4())[:8],
        "chat_id": chat_id,
        "players": game_players,
        "phase": "night",
        "round": 1,
        "night_kill_vote": {},   # werewolf_id -> target_id
        "doctor_protect": None,
        "votes": {},             # voter_id -> target_id (day phase)
        "started_at": int(time.time()),
    }
    _ww_games[chat_id] = game

    werewolf_names = [p["name"] for p in game_players.values() if p["role"] == "werewolf"]

    for pid, pdata in game_players.items():
        role = pdata["role"]
        try:
            if role == "werewolf":
                pack = ", ".join(n for n in werewolf_names if n != pdata["name"]) or "you're the only one!"
                await context.bot.send_message(
                    pid,
                    f"🐺 <b>You are a WEREWOLF!</b>\n\n"
                    f"Your fellow werewolves: {pack}\n\n"
                    f"Each night, use /prowl (in this DM) during the night phase to "
                    f"vote on who to eliminate. Blend in during the day — don't get caught!",
                    parse_mode="HTML"
                )
            elif role == "seer":
                await context.bot.send_message(
                    pid,
                    f"🔮 <b>You are the SEER!</b>\n\n"
                    f"Each night, use /peek (in this DM) during the night phase to "
                    f"secretly check one player's true role. Use what you learn "
                    f"carefully during the day — revealing you're the Seer makes "
                    f"you a target!",
                    parse_mode="HTML"
                )
            elif role == "doctor":
                await context.bot.send_message(
                    pid,
                    f"💉 <b>You are the DOCTOR!</b>\n\n"
                    f"Each night, use /heal (in this DM) during the night phase to "
                    f"protect one player (including yourself) from elimination.",
                    parse_mode="HTML"
                )
            else:
                await context.bot.send_message(
                    pid,
                    f"👤 <b>You are a VILLAGER.</b>\n\n"
                    f"No night action — survive by paying attention during the day "
                    f"and voting out the werewolves with /vote.",
                    parse_mode="HTML"
                )
        except Exception as e:
            logger.debug(f"werewolf: DM failed for {pid}: {e}")
            dm_failed.append(pdata["name"])

    warn = ""
    if dm_failed:
        warn = (f"\n\n⚠️ Couldn't DM: {', '.join(dm_failed)} — they need to send "
                f"/start to me in DM first, then rejoin next game!")

    await context.bot.send_message(
        chat_id,
        f"🌙 <b>Roles have been sent! The game begins...</b>\n\n"
        f"👥 {n} players | 🐺 {counts['werewolf']} werewolves | "
        f"🔮 {counts['seer']} seer | 💉 {counts['doctor']} doctor | "
        f"👤 {counts['villager']} villagers\n\n"
        f"🌙 <b>Night {game['round']} has fallen.</b> Werewolves, Seer, and "
        f"Doctor — check your DMs! Villagers, just wait.\n"
        f"⏱️ Night ends in {NIGHT_SECONDS}s." + warn,
        parse_mode="HTML"
    )
    asyncio.create_task(_night_timer(context, chat_id))


# ── Night actions (DM commands) ─────────────────────────────────────────────

async def prowl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Werewolf night-kill vote — used in DM."""
    u = update.effective_user
    game = _find_active_game_for_player(u.id)
    if game == "ambiguous":
        await update.message.reply_html(
            "⚠️ You're in more than one active Werewolf night phase right now — "
            "I can't tell which game this action is for. Please finish one game "
            "before acting in another."
        ); return
    if not game or game["phase"] != "night":
        await update.message.reply_html("❌ No active night phase for you right now."); return
    me = game["players"].get(u.id)
    if not me or me["role"] != "werewolf" or not me["alive"]:
        await update.message.reply_html("❌ This isn't your action to take."); return

    alive_others = [p for p in game["players"].values() if p["alive"] and p["role"] != "werewolf"]
    if not context.args:
        options = "\n".join(f"{i+1}. {p['name']}" for i, p in enumerate(alive_others))
        await update.message.reply_html(
            f"🐺 Who do you want to eliminate tonight?\nUsage: /prowl <number>\n\n{options}"
        ); return
    try:
        idx = int(context.args[0]) - 1
        target = alive_others[idx]
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid choice."); return

    game["night_kill_vote"][u.id] = target["id"]
    await update.message.reply_html(f"🐺 Vote recorded: eliminate <b>{target['name']}</b>.")


async def peek_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Seer night action — used in DM."""
    u = update.effective_user
    game = _find_active_game_for_player(u.id)
    if game == "ambiguous":
        await update.message.reply_html(
            "⚠️ You're in more than one active Werewolf night phase right now — "
            "I can't tell which game this action is for. Please finish one game "
            "before acting in another."
        ); return
    if not game or game["phase"] != "night":
        await update.message.reply_html("❌ No active night phase for you right now."); return
    me = game["players"].get(u.id)
    if not me or me["role"] != "seer" or not me["alive"]:
        await update.message.reply_html("❌ This isn't your action to take."); return

    alive_others = [p for p in game["players"].values() if p["alive"] and p["id"] != u.id]
    if not context.args:
        options = "\n".join(f"{i+1}. {p['name']}" for i, p in enumerate(alive_others))
        await update.message.reply_html(
            f"🔮 Who do you want to peek at?\nUsage: /peek <number>\n\n{options}"
        ); return
    try:
        idx = int(context.args[0]) - 1
        target = alive_others[idx]
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid choice."); return

    role_emoji = {"werewolf": "🐺 Werewolf", "seer": "🔮 Seer",
                  "doctor": "💉 Doctor", "villager": "👤 Villager"}
    await update.message.reply_html(
        f"🔮 <b>{target['name']}</b> is a... <b>{role_emoji[target['role']]}</b>!"
    )


async def heal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Doctor night action — used in DM."""
    u = update.effective_user
    game = _find_active_game_for_player(u.id)
    if game == "ambiguous":
        await update.message.reply_html(
            "⚠️ You're in more than one active Werewolf night phase right now — "
            "I can't tell which game this action is for. Please finish one game "
            "before acting in another."
        ); return
    if not game or game["phase"] != "night":
        await update.message.reply_html("❌ No active night phase for you right now."); return
    me = game["players"].get(u.id)
    if not me or me["role"] != "doctor" or not me["alive"]:
        await update.message.reply_html("❌ This isn't your action to take."); return

    alive = [p for p in game["players"].values() if p["alive"]]
    if not context.args:
        options = "\n".join(f"{i+1}. {p['name']}{' (you)' if p['id']==u.id else ''}" for i, p in enumerate(alive))
        await update.message.reply_html(
            f"💉 Who do you want to protect tonight?\nUsage: /heal <number>\n\n{options}"
        ); return
    try:
        idx = int(context.args[0]) - 1
        target = alive[idx]
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid choice."); return

    game["doctor_protect"] = target["id"]
    await update.message.reply_html(f"💉 You'll protect <b>{target['name']}</b> tonight.")


def _find_active_game_for_player(uid: int):
    """
    Find the game this player should act in via DM right now.

    EDGE CASE: a player could theoretically be in more than one active
    Werewolf game at once (different groups). If more than one of their
    games is currently in the night phase, we can't tell which DM action
    was meant for which game from the DM alone — so we deliberately
    refuse to guess (a wrong guess could let a night action affect the
    wrong game). We only auto-resolve when exactly one of the player's
    games is actually in a night phase that needs their action.
    """
    night_phase_games = [
        g for g in _ww_games.values()
        if uid in g["players"] and g["phase"] == "night" and g["players"][uid]["alive"]
    ]
    if len(night_phase_games) == 1:
        return night_phase_games[0]
    if len(night_phase_games) > 1:
        return "ambiguous"  # signal to the caller — see night-action commands below
    return None


# ── Night → Day transition ──────────────────────────────────────────────────

async def _night_timer(context, chat_id):
    await asyncio.sleep(NIGHT_SECONDS)
    game = _ww_games.get(chat_id)
    if not game or game["phase"] != "night":
        return
    await _resolve_night(context, chat_id)


async def _resolve_night(context, chat_id):
    game = _ww_games[chat_id]

    # Tally werewolf votes (majority, random tiebreak).
    votes = list(game["night_kill_vote"].values())
    victim_id = None
    if votes:
        tally = {}
        for v in votes:
            tally[v] = tally.get(v, 0) + 1
        top = max(tally.values())
        candidates = [k for k, v in tally.items() if v == top]
        victim_id = random.choice(candidates)

    protected_id = game["doctor_protect"]
    game["night_kill_vote"] = {}
    game["doctor_protect"] = None

    text = f"☀️ <b>Day {game['round']} breaks...</b>\n\n"
    if victim_id and victim_id != protected_id:
        victim = game["players"][victim_id]
        victim["alive"] = False
        text += f"💀 <b>{victim['name']}</b> was found dead — they were a {_role_label(victim['role'])}!\n\n"
    elif victim_id and victim_id == protected_id:
        text += f"💉 The Doctor's protection saved someone last night! Nobody died.\n\n"
    else:
        text += f"😴 The werewolves couldn't agree — nobody died last night.\n\n"

    win = _check_win(game)
    if win:
        await _end_game(context, chat_id, win)
        return

    alive = [p for p in game["players"].values() if p["alive"]]
    names = "\n".join(f"• {p['name']}" for p in alive)
    game["phase"] = "day"
    game["votes"] = {}
    text += (
        f"👥 <b>Alive ({len(alive)}):</b>\n{names}\n\n"
        f"🗳️ Discuss, then use <code>/vote &lt;number&gt;</code> in this group "
        f"to vote out a suspect. Most votes = eliminated.\n"
        f"⏱️ Day ends in {DAY_SECONDS}s."
    )
    await context.bot.send_message(chat_id, text, parse_mode="HTML")
    asyncio.create_task(_day_timer(context, chat_id))


def _role_label(role: str) -> str:
    return {"werewolf": "🐺 Werewolf", "seer": "🔮 Seer",
            "doctor": "💉 Doctor", "villager": "👤 Villager"}[role]


# ── Day vote ─────────────────────────────────────────────────────────────

async def vote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    u = update.effective_user
    game = _ww_games.get(chat.id)
    if not game or game["phase"] != "day":
        await update.message.reply_html("❌ No voting phase active right now."); return
    me = game["players"].get(u.id)
    if not me or not me["alive"]:
        await update.message.reply_html("❌ You're not in this game (or you're eliminated)."); return

    alive = [p for p in game["players"].values() if p["alive"]]
    if not context.args:
        options = "\n".join(f"{i+1}. {p['name']}" for i, p in enumerate(alive))
        await update.message.reply_html(f"🗳️ Usage: /vote <number>\n\n{options}"); return
    try:
        idx = int(context.args[0]) - 1
        target = alive[idx]
    except (ValueError, IndexError):
        await update.message.reply_html("❌ Invalid choice."); return

    game["votes"][u.id] = target["id"]
    await update.message.reply_html(f"🗳️ {mention(u)} voted to eliminate <b>{target['name']}</b>!")


async def _day_timer(context, chat_id):
    await asyncio.sleep(DAY_SECONDS)
    game = _ww_games.get(chat_id)
    if not game or game["phase"] != "day":
        return
    await _resolve_day(context, chat_id)


async def _resolve_day(context, chat_id):
    game = _ww_games[chat_id]
    votes = list(game["votes"].values())
    text = f"🗳️ <b>Votes are in!</b>\n\n"

    if votes:
        tally = {}
        for v in votes:
            tally[v] = tally.get(v, 0) + 1
        top = max(tally.values())
        candidates = [k for k, v in tally.items() if v == top]
        eliminated_id = random.choice(candidates)
        eliminated = game["players"][eliminated_id]
        eliminated["alive"] = False
        text += f"⚖️ <b>{eliminated['name']}</b> was voted out — they were a {_role_label(eliminated['role'])}!\n\n"
    else:
        text += "😶 Nobody voted — no elimination today.\n\n"

    win = _check_win(game)
    if win:
        await _end_game(context, chat_id, win)
        return

    game["round"] += 1
    game["phase"] = "night"
    alive = [p for p in game["players"].values() if p["alive"]]
    names = "\n".join(f"• {p['name']}" for p in alive)
    text += (
        f"🌙 <b>Night {game['round']} falls...</b>\n\n"
        f"👥 <b>Alive ({len(alive)}):</b>\n{names}\n\n"
        f"Werewolves, Seer, Doctor — check your DMs!\n"
        f"⏱️ Night ends in {NIGHT_SECONDS}s."
    )
    await context.bot.send_message(chat_id, text, parse_mode="HTML")
    asyncio.create_task(_night_timer(context, chat_id))


def _check_win(game) -> str | None:
    alive = [p for p in game["players"].values() if p["alive"]]
    wolves = [p for p in alive if p["role"] == "werewolf"]
    villagers = [p for p in alive if p["role"] != "werewolf"]
    if not wolves:
        return "villagers"
    if len(wolves) >= len(villagers):
        return "werewolves"
    return None


async def _end_game(context, chat_id, winner: str):
    game = _ww_games.pop(chat_id, None)
    if not game:
        return
    all_players = list(game["players"].values())
    reveal = "\n".join(f"• {p['name']} — {_role_label(p['role'])} {'💀' if not p['alive'] else '✅'}"
                        for p in all_players)

    if winner == "villagers":
        title = "🎉 <b>VILLAGERS WIN!</b> All werewolves have been eliminated."
        winners = [p for p in all_players if p["role"] != "werewolf"]
    else:
        title = "🐺 <b>WEREWOLVES WIN!</b> They've taken over the village."
        winners = [p for p in all_players if p["role"] == "werewolf"]

    # Small coin reward for the winning side.
    for p in winners:
        try:
            await add_balance(p["id"], 150)
        except Exception:
            pass

    await send_gif_result(
        context, chat_id, "werewolf_win",
        f"{title}\n\n"
        f"🎭 <b>Final roles:</b>\n{reveal}\n\n"
        f"💰 Winners earned 150 coins each!\n"
        f"Play again anytime with /werewolf.",
    )
