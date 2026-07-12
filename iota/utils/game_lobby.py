"""
Iota — generic game-lobby registry with auto-expiry.

Several games keep live state in module-level dicts (bluff, hack, werewolf,
card, …) but nothing guarantees cleanup, so abandoned lobbies leak memory
and can stick around forever. This module gives every game ONE shared,
auto-expiring registry plus a single background job that sweeps it.

Usage:
    from utils.game_lobby import register_lobby, get_lobby, cancel_lobby

    register_lobby(f"bluff:{chat.id}", ttl=120, on_expire=_on_bluff_expire)
    lobby = get_lobby(f"bluff:{chat.id}")   # None if missing/expired
    cancel_lobby(f"bluff:{chat.id}")

Wire the sweeper once in bot.py post_init:
    from utils.game_lobby import lobby_expiry_job
    asyncio.create_task(lobby_expiry_job(application.bot))
"""
import time
import asyncio
import logging

logger = logging.getLogger(__name__)

# key -> {"expires_at": float, "data": dict, "on_expire": callable|None}
_lobbies: dict = {}
_lock = asyncio.Lock()


async def register_lobby(key: str, ttl: int, data: dict = None,
                         on_expire=None):
    """Register/update a lobby that auto-expires after `ttl` seconds."""
    async with _lock:
        _lobbies[key] = {
            "expires_at": time.time() + max(1, ttl),
            "data": data or {},
            "on_expire": on_expire,
        }


async def get_lobby(key: str):
    """Return the lobby data dict, or None if missing/expired."""
    async with _lock:
        lob = _lobbies.get(key)
        if not lob:
            return None
        if time.time() > lob["expires_at"]:
            _lobbies.pop(key, None)
            return None
        return lob["data"]


async def cancel_lobby(key: str):
    async with _lock:
        _lobbies.pop(key, None)


async def _sweep(bot):
    now = time.time()
    expired = []
    async with _lock:
        for k, lob in list(_lobbies.items()):
            if now > lob["expires_at"]:
                expired.append((k, lob))
                _lobbies.pop(k, None)
    for k, lob in expired:
        cb = lob.get("on_expire")
        if cb:
            try:
                await cb(k, lob.get("data") or {})
            except Exception:
                logger.debug("lobby on_expire callback failed", exc_info=True)


async def lobby_expiry_job(bot, interval: int = 30):
    """Background sweeper. Runs until the event loop stops."""
    while True:
        try:
            await _sweep(bot)
        except Exception:
            logger.debug("lobby sweep failed", exc_info=True)
        await asyncio.sleep(interval)
