"""
Iota Ludo — Mini App Web Server

Serves the Ludo Mini App (webapp/ludo/index.html + assets) and exposes a
small JSON/WebSocket API that the frontend uses to play a REAL, live,
multiplayer Ludo game with a visual board — as opposed to the in-chat
button version.

SECURITY
────────
Every request must include Telegram's `initData` string (Telegram Web
Apps automatically attach this — see
https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app).
We verify its HMAC-SHA256 signature against the bot token before trusting
ANY user id it claims, so a user can never impersonate another user or
tamper with their own identity to cheat (e.g. claim someone else's coins,
or move on someone else's turn).

RUNS IN-PROCESS
────────────────
This aiohttp web server runs inside the SAME asyncio event loop as the
bot's polling loop (started as a background task from bot.py), so no
separate hosting/process is required — whatever server the bot itself
runs on, the Mini App is served from too.

DEPLOYMENT NOTE
────────────────
Telegram Mini Apps MUST be served over HTTPS with a real, publicly
reachable domain (not localhost, not a bare IP). Set WEBAPP_BASE_URL in
config.py to your bot's public HTTPS domain (e.g. behind a reverse proxy
/ your hosting provider's TLS termination) for /ludo's "Play" button to
work. Until that's set, /ludo will explain this to the host instead of
sending a broken WebApp link.
"""
import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

from aiohttp import web, WSMsgType

from utils import ludo_engine as engine
from utils.mongo_db import ensure_user, get_user, add_balance, deduct_balance
from config import BOT_TOKEN

logger = logging.getLogger(__name__)

# Resolve paths relative to this file, not the process's CWD — makes the
# server work correctly regardless of where `python bot.py` is launched from.
_WEBAPP_DIR = os.path.dirname(os.path.abspath(__file__))
_LUDO_DIR = os.path.join(_WEBAPP_DIR, "ludo")
_LUDO_STATIC_DIR = os.path.join(_LUDO_DIR, "static")

# ── In-memory live game store ───────────────────────────────────────────────
# Mirrors handlers/ludo.py's _ludo_games pattern but shared across all
# webapp game sessions. For a single-process deployment this is sufficient
# (matches how the rest of the bot already keeps live game state in
# memory, e.g. card games, bomb game). If Iota is ever scaled to multiple
# processes, this would need to move to Redis/Mongo — noted here for
# future scaling, not needed at current scale.
_games: dict = {}
_ws_clients: dict = {}  # game_id -> set of WebSocketResponse


def _verify_init_data(init_data: str) -> dict | None:
    """
    Validate Telegram Mini App initData per Telegram's documented HMAC
    scheme. Returns the parsed user dict if valid, None if invalid/forged.
    """
    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(pairs.items())
        )
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            logger.warning("Ludo WebApp: initData signature mismatch (possible forged request)")
            return None

        # Reject stale initData (older than 24h) as a defense-in-depth measure.
        auth_date = int(pairs.get("auth_date", 0))
        if time.time() - auth_date > 86400:
            logger.warning("Ludo WebApp: initData expired")
            return None

        user_json = pairs.get("user")
        if not user_json:
            return None
        return json.loads(user_json)
    except Exception as e:
        logger.warning(f"Ludo WebApp: initData validation error: {e}")
        return None


def _authed_user(request) -> dict | None:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        return None
    return _verify_init_data(init_data)


# ── REST handlers ────────────────────────────────────────────────────────────

async def handle_index(request):
    return web.FileResponse(os.path.join(_LUDO_DIR, "index.html"))


async def handle_create_game(request):
    """Host creates a new game from /ludo's 'Open Mini App' button."""
    user = _authed_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    body = await request.json()
    chat_id = body.get("chat_id")
    bet = int(body.get("bet", 0))

    await ensure_user(user["id"], user.get("username", ""), user.get("first_name", ""))
    if bet > 0:
        d = await get_user(user["id"])
        if d["balance"] < bet:
            return web.json_response({"error": "insufficient_balance"}, status=400)
        await deduct_balance(user["id"], bet)

    game = engine.new_game(chat_id, user["id"], user.get("first_name", "Player"), bet, mode="webapp")
    _games[game["id"]] = game
    return web.json_response({"game_id": game["id"], "state": engine.public_state(game)})


async def handle_join_game(request):
    user = _authed_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    gid = request.match_info["gid"]
    game = _games.get(gid)
    if not game:
        return web.json_response({"error": "game_not_found"}, status=404)

    body = await request.json()
    as_spectator = bool(body.get("spectator", False))

    already_playing = any(p["id"] == user["id"] for p in game["players"])
    already_watching = any(s["id"] == user["id"] for s in game["spectators"])

    if as_spectator:
        if not already_watching and not already_playing:
            game["spectators"].append({"id": user["id"], "name": user.get("first_name", "Guest")})
    else:
        if game["status"] != "waiting":
            return web.json_response({"error": "already_started"}, status=400)
        if already_playing:
            pass
        elif len(game["players"]) >= 4:
            return web.json_response({"error": "game_full"}, status=400)
        else:
            await ensure_user(user["id"], user.get("username", ""), user.get("first_name", ""))
            if game["bet"] > 0:
                d = await get_user(user["id"])
                if d["balance"] < game["bet"]:
                    return web.json_response({"error": "insufficient_balance"}, status=400)
                await deduct_balance(user["id"], game["bet"])
            color = engine.COLOR_LIST[len(game["players"])]
            game["players"].append({
                "id": user["id"], "name": user.get("first_name", "Player"),
                "color": color, "pieces": [0, 0, 0, 0],
                "finished_pieces": 0, "score": 0, "is_spectator": False,
            })

    await _broadcast(gid, {"type": "state", "state": engine.public_state(game)})
    return web.json_response({"state": engine.public_state(game)})


async def handle_start_game(request):
    user = _authed_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    gid = request.match_info["gid"]
    game = _games.get(gid)
    if not game:
        return web.json_response({"error": "game_not_found"}, status=404)
    if game["players"][0]["id"] != user["id"]:
        return web.json_response({"error": "only_host_can_start"}, status=403)
    if len(game["players"]) < 2:
        return web.json_response({"error": "need_2_players"}, status=400)

    game["status"] = "playing"
    game["turn"] = 0
    await _broadcast(gid, {"type": "state", "state": engine.public_state(game)})
    return web.json_response({"state": engine.public_state(game)})


async def handle_roll(request):
    user = _authed_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    gid = request.match_info["gid"]
    game = _games.get(gid)
    if not game or game["status"] != "playing":
        return web.json_response({"error": "game_not_active"}, status=400)

    current_p = game["players"][game["turn"]]
    if current_p["id"] != user["id"]:
        return web.json_response({"error": "not_your_turn"}, status=403)

    result = engine.roll_dice_and_get_movable(game)

    # No legal move → auto pass turn (mirrors chat version's behaviour).
    if not result["movable"]:
        engine.next_turn(game)
        game["updated_at"] = int(time.time())
        payload = {"type": "roll", "dice": result["dice"], "movable": [],
                   "auto_passed": True, "state": engine.public_state(game)}
        await _broadcast(gid, payload)
        return web.json_response(payload)

    payload = {"type": "roll", "dice": result["dice"], "movable": result["movable"],
               "auto_passed": False, "state": engine.public_state(game)}
    await _broadcast(gid, payload)
    return web.json_response(payload)


async def handle_move(request):
    user = _authed_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    gid = request.match_info["gid"]
    game = _games.get(gid)
    if not game or game["status"] != "playing":
        return web.json_response({"error": "game_not_active"}, status=400)

    current_p = game["players"][game["turn"]]
    if current_p["id"] != user["id"]:
        return web.json_response({"error": "not_your_turn"}, status=403)

    body = await request.json()
    piece_idx = int(body.get("piece_idx", -1))
    if piece_idx not in (0, 1, 2, 3):
        return web.json_response({"error": "invalid_piece"}, status=400)

    movable = engine.count_movable(current_p["pieces"], game["dice"], current_p["color"])
    if piece_idx not in movable:
        return web.json_response({"error": "illegal_move"}, status=400)

    event = engine.apply_move(game, piece_idx)

    payload = {"type": "move", "event": event, "state": engine.public_state(game)}

    if event["won"]:
        bet = game["bet"]
        total = bet * len(game["players"])
        prize = int(total * 0.95)
        if prize > 0:
            await add_balance(current_p["id"], prize)
        game["status"] = "finished"
        game["winner"] = {"id": current_p["id"], "name": current_p["name"],
                           "color": current_p["color"], "prize": prize}
        payload["state"] = engine.public_state(game)
        payload["winner"] = game["winner"]
        await _broadcast(gid, payload)
        _games.pop(gid, None)
        return web.json_response(payload)

    await _broadcast(gid, payload)
    return web.json_response(payload)


async def handle_chat(request):
    """In-lobby / in-game chat, visible to players AND spectators."""
    user = _authed_user(request)
    if not user:
        return web.json_response({"error": "unauthorized"}, status=401)

    gid = request.match_info["gid"]
    game = _games.get(gid)
    if not game:
        return web.json_response({"error": "game_not_found"}, status=404)

    body = await request.json()
    text = str(body.get("text", ""))[:200].strip()
    if not text:
        return web.json_response({"error": "empty_message"}, status=400)

    entry = {"id": user["id"], "name": user.get("first_name", "Guest"),
              "text": text, "ts": int(time.time())}
    game["chat_log"].append(entry)
    game["chat_log"] = game["chat_log"][-50:]  # keep last 50 only

    await _broadcast(gid, {"type": "chat", "entry": entry})
    return web.json_response({"ok": True})


async def handle_state(request):
    gid = request.match_info["gid"]
    game = _games.get(gid)
    if not game:
        return web.json_response({"error": "game_not_found"}, status=404)
    return web.json_response({"state": engine.public_state(game), "chat_log": game["chat_log"]})


# ── WebSocket for real-time push (dice rolls, moves, chat) ─────────────────

async def handle_ws(request):
    gid = request.match_info["gid"]
    ws = web.WebSocketResponse(heartbeat=25)
    await ws.prepare(request)

    _ws_clients.setdefault(gid, set()).add(ws)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.ERROR:
                break
            # Clients only receive pushes; all actions go through REST
            # endpoints above (keeps validation/auth in one place).
    finally:
        _ws_clients.get(gid, set()).discard(ws)
    return ws


async def _broadcast(gid: str, payload: dict):
    clients = _ws_clients.get(gid)
    if not clients:
        return
    dead = set()
    text = json.dumps(payload)
    for ws in clients:
        try:
            await ws.send_str(text)
        except Exception:
            dead.add(ws)
    clients -= dead


# ── App factory ───────────────────────────────────────────────────────────

def build_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/ludo", handle_index)
    app.router.add_get("/ludo/", handle_index)
    app.router.add_static("/ludo/static", path=_LUDO_STATIC_DIR, name="ludo_static")

    app.router.add_post("/api/ludo/create", handle_create_game)
    app.router.add_post("/api/ludo/{gid}/join", handle_join_game)
    app.router.add_post("/api/ludo/{gid}/start", handle_start_game)
    app.router.add_post("/api/ludo/{gid}/roll", handle_roll)
    app.router.add_post("/api/ludo/{gid}/move", handle_move)
    app.router.add_post("/api/ludo/{gid}/chat", handle_chat)
    app.router.add_get("/api/ludo/{gid}/state", handle_state)
    app.router.add_get("/api/ludo/{gid}/ws", handle_ws)
    return app


async def run_webapp_server(host="0.0.0.0", port=8080):
    """Started as a background asyncio task from bot.py's main()."""
    app = build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host, port)
    await site.start()
    logger.info(f"🎲 Ludo Mini App server running on {host}:{port}")
    return runner
