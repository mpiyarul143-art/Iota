"""
Iota — generic, reusable rate limiter.

Keeps a per-(bucket, key) sliding window of timestamps in memory (single
instance) with a thread-safe lock, so any command can cheaply throttle
abuse without a DB round-trip. Falls back gracefully if storage grows.

Usage (decorator):
    from utils.ratelimit import ratelimit

    @ratelimit("ai", limit=8, window=60)        # 8 calls / 60s per user
    async def ai_cmd(update, context): ...

Or programmatic:
    allowed = await ratelimit_allow("ai", user_id, limit=8, window=60)
    if not allowed:
        await update.message.reply_html("⏳ Slow down…")

The decorator auto-keys on the effective user id and, when the limit is
hit, replies with a friendly small-caps message and returns (so the
underlying handler never runs). Set reply=False to handle it yourself.
"""
import time
import asyncio
from functools import wraps
from telegram import Update
from utils.fonts import sc

_lock = asyncio.Lock()
# (bucket, key) -> list[float]  (timestamps, oldest first)
_store: dict = {}


def _prune(bucket_key, window):
    now = time.time()
    stamps = _store.get(bucket_key)
    if not stamps:
        return []
    # drop entries older than the window
    kept = [t for t in stamps if now - t < window]
    if kept:
        _store[bucket_key] = kept
    else:
        _store.pop(bucket_key, None)
    return kept


async def ratelimit_allow(bucket: str, key, *, limit: int, window: int) -> bool:
    """Return True if `key` is still allowed `limit` calls per `window` secs."""
    if limit <= 0:
        return True
    bk = (bucket, key)
    async with _lock:
        stamps = _prune(bk, window)
        if len(stamps) >= limit:
            return False
        stamps.append(time.time())
        _store[bk] = stamps
    return True


def ratelimit(bucket: str, *, limit: int, window: int, reply: bool = True,
              keyfn=None, message: str = None):
    """Decorator that throttles a Telegram handler by (bucket, user)."""
    def deco(fn):
        @wraps(fn)
        async def wrapper(update: Update, context):
            u = update.effective_user
            if u is None:
                return await fn(update, context)
            k = keyfn(u) if keyfn else u.id
            allowed = await ratelimit_allow(bucket, k, limit=limit, window=window)
            if allowed:
                return await fn(update, context)
            if reply:
                msg = update.effective_message
                if msg is not None:
                    text = message or (
                        f"{sc('Slow down!')} {sc('You can use this again in a moment')}."
                    )
                    try:
                        await msg.reply_html(text)
                    except Exception:
                        pass
            return None
        return wrapper
    return deco
