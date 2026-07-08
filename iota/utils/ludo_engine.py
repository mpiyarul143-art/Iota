"""
Iota Ludo — Shared Rules Engine

This module holds the pure game-logic (board math, move validation,
capture detection, win detection) used by BOTH:
  - the in-chat button-based /ludo game (handlers/ludo.py)
  - the new Ludo Mini App / WebApp (webapp/ludo_server.py)

Keeping ONE source of truth for the rules means the two experiences can
never drift out of sync or disagree about what a legal move is.

Board representation
─────────────────────
- 4 colors: red, blue, green, yellow — each has 4 pieces.
- piece position: 0 = in yard (not yet on board), 1-52 = on the shared
  outer track, 53-58 = home stretch (color-specific), 58 = home (won).
- SAFE_CELLS are star positions where pieces can't be captured.
- A 6 lets a piece leave the yard, and grants an extra turn (as does any
  capture).
"""
import time
import uuid

# ── Constants ──────────────────────────────────────────────────────────────

COLORS = {
    "red":    {"emoji": "🔴", "hex": "#e53935"},
    "blue":   {"emoji": "🔵", "hex": "#1e88e5"},
    "green":  {"emoji": "🟢", "hex": "#43a047"},
    "yellow": {"emoji": "🟡", "hex": "#fdd835"},
}
COLOR_LIST = ["red", "blue", "green", "yellow"]

BOARD_SIZE   = 52
HOME_STRETCH = 6
WINNING_POS  = BOARD_SIZE + HOME_STRETCH  # 58

SAFE_CELLS = {1, 9, 14, 22, 27, 35, 40, 48}

START_POSITIONS = {"red": 1, "blue": 14, "green": 27, "yellow": 40}
HOME_ENTRY      = {"red": 51, "blue": 12, "green": 25, "yellow": 38}

TURN_TIMEOUT_SECONDS = 60


# ── Pure game-state helpers ─────────────────────────────────────────────────

def new_game(chat_id, host_id, host_name: str, bet: int = 0, mode: str = "chat") -> dict:
    """
    Create a fresh game state dict.
    `mode` is "chat" (in-chat buttons) or "webapp" (Mini App) — both use
    the exact same state shape and rules, just different frontends.
    """
    gid = str(uuid.uuid4())[:8]
    return {
        "id":        gid,
        "chat_id":   chat_id,
        "bet":       bet,
        "mode":      mode,
        "status":    "waiting",   # waiting | playing | finished
        "players":   [{
            "id":     host_id,
            "name":   host_name,
            "color":  "red",
            "pieces": [0, 0, 0, 0],
            "finished_pieces": 0,
            "score":  0,
            "is_spectator": False,
        }],
        "spectators": [],   # [{id, name}] — webapp only: users watching without playing
        "chat_log":   [],   # [{id, name, text, ts}] — webapp lobby/in-game chat
        "turn":      0,
        "dice":      0,
        "last_roll": 0,
        "winner":    None,
        "created":   int(time.time()),
        "turn_deadline": 0,
        "updated_at": int(time.time()),
    }


def can_move(piece_pos: int, dice: int, color: str) -> bool:
    if piece_pos == 0:
        return dice == 6
    return calc_new_pos(piece_pos, dice, color) != piece_pos or piece_pos == 0


def calc_new_pos(current: int, dice: int, color: str) -> int:
    if current == 0:
        return START_POSITIONS[color] if dice == 6 else 0

    # Piece is already in its color's home stretch (53-58) — move straight
    # along it. This is NOT on the shared 52-cell ring, so it must be
    # handled separately from the outer-track math below (this was the
    # bug: reusing the outer-track modulo formula on a home-stretch
    # position produced a nonsensical result and made the final stretch
    # of every game unwinnable).
    if current > BOARD_SIZE:
        new_pos = current + dice
        return new_pos if new_pos <= WINNING_POS else current  # overshoot = illegal, no move

    start = START_POSITIONS[color]
    rel = (current - start) % BOARD_SIZE
    new_rel = rel + dice

    if new_rel >= BOARD_SIZE:
        home_pos = BOARD_SIZE + (new_rel - BOARD_SIZE)
        if home_pos > WINNING_POS:
            return current  # overshoot — illegal, no move
        return home_pos

    return (start + new_rel - 1) % BOARD_SIZE + 1


def is_safe(pos: int) -> bool:
    return pos in SAFE_CELLS or pos > BOARD_SIZE


def check_capture(game: dict, mover_color: str, new_pos: int) -> list:
    """Sends any opponent pieces on new_pos back to their yard. Returns
    list of {name, color} for captured players (for event/animation text)."""
    if is_safe(new_pos):
        return []
    captured = []
    for p in game["players"]:
        if p["color"] == mover_color:
            continue
        for i, pp in enumerate(p["pieces"]):
            if pp == new_pos:
                p["pieces"][i] = 0
                captured.append({"name": p["name"], "color": p["color"]})
    return captured


def count_movable(pieces: list, dice: int, color: str) -> list:
    """Returns list of piece indices that can legally move with this dice roll."""
    return [i for i, pos in enumerate(pieces)
            if (pos == 0 and dice == 6) or (pos != 0 and calc_new_pos(pos, dice, color) != pos)]


def has_won(pieces: list) -> bool:
    return all(p == WINNING_POS for p in pieces)


def next_turn(game: dict):
    """Advance to the next player who is still an active player (not a
    pure spectator) and hasn't already won all pieces."""
    n = len(game["players"])
    for _ in range(n):
        game["turn"] = (game["turn"] + 1) % n
        if not has_won(game["players"][game["turn"]]["pieces"]):
            break


def apply_move(game: dict, piece_idx: int) -> dict:
    """
    Executes a move for the current player's given piece using game["dice"].
    Mutates `game` in place and returns an event summary dict:
      {left_yard, captured, reached_home, home_count, won, extra_turn}
    """
    current_p = game["players"][game["turn"]]
    color = current_p["color"]
    dice  = game["dice"]
    old_pos = current_p["pieces"][piece_idx]
    new_pos = calc_new_pos(old_pos, dice, color)
    if new_pos > WINNING_POS:
        new_pos = old_pos

    current_p["pieces"][piece_idx] = new_pos

    left_yard = (old_pos == 0 and new_pos > 0)
    captured = check_capture(game, color, new_pos)
    if captured:
        current_p["score"] += 50 * len(captured)

    reached_home = (new_pos == WINNING_POS)
    if reached_home:
        current_p["score"] += 100

    won = has_won(current_p["pieces"])
    extra_turn = (dice == 6 or bool(captured)) and not won

    if not extra_turn and not won:
        next_turn(game)

    game["updated_at"] = int(time.time())

    return {
        "left_yard": left_yard,
        "captured": captured,
        "reached_home": reached_home,
        "home_count": current_p["pieces"].count(WINNING_POS),
        "won": won,
        "extra_turn": extra_turn,
        "mover": {"id": current_p["id"], "name": current_p["name"], "color": color},
    }


def roll_dice_and_get_movable(game: dict) -> dict:
    """Rolls the dice for the current player and returns which pieces can move.
    Does NOT auto-apply the move — caller decides (auto-move if only one option)."""
    import random
    current_p = game["players"][game["turn"]]
    dice = random.randint(1, 6)
    game["dice"] = dice
    game["last_roll"] = int(time.time())
    movable = count_movable(current_p["pieces"], dice, current_p["color"])
    return {"dice": dice, "movable": movable, "player_id": current_p["id"]}


def public_state(game: dict) -> dict:
    """Returns a JSON-safe snapshot of the game for sending to the Mini App
    frontend (strips nothing sensitive — Ludo has no hidden information,
    unlike card games, so the full state is always safe to expose to all
    participants, including spectators)."""
    return {
        "id": game["id"],
        "status": game["status"],
        "bet": game["bet"],
        "players": [
            {
                "id": p["id"], "name": p["name"], "color": p["color"],
                "pieces": p["pieces"], "score": p["score"],
                "home_count": p["pieces"].count(WINNING_POS),
            } for p in game["players"]
        ],
        "spectator_count": len(game.get("spectators", [])),
        "turn": game["turn"],
        "dice": game["dice"],
        "winner": game["winner"],
        "safe_cells": sorted(SAFE_CELLS),
        "start_positions": START_POSITIONS,
        "updated_at": game["updated_at"],
    }
