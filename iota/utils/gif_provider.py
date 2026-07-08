"""
Iota Bot — GIF Provider (GIPHY-backed)

WHY THIS FILE WAS REWRITTEN
─────────────────────────────
This used to search Google's Tenor API. Google permanently shut down
the Tenor API on 2026-06-30 (registrations were frozen back on
2026-01-14) — every Tenor search call now fails outright, which is why
GIFs across the whole bot (welcome, /slap, /pat, card wins, etc.) had
stopped working. This file now searches GIPHY instead, which is still
live and has no signup requirement for basic/beta-tier search.

It also no longer falls back to a hardcoded list of specific GIF media
IDs. The previous backup list was exactly this bot's earlier failure
mode: individual hardcoded Giphy links rot (deleted, rate-limited,
moderated) — every single one of them had already gone dead (403) by
the time of this rewrite. Baking in a fresh set of hardcoded IDs would
just repeat the same mistake on a delay. Instead: the live search IS
the GIF source, and if it's ever unreachable, callers get back `None`
and gracefully send text only — never a broken image.

SETUP
─────
Works out of the box with a shared public GIPHY demo key. For real
use, get your own free key (2 minutes, no cost) and put it in
config.py as GIPHY_API_KEY — see the comment there for the exact
steps. A personal key isn't shared with every other bot using this
same code, so you won't be affected by anyone else's rate limit.
"""
import aiohttp
import asyncio
import logging
import random
import time

logger = logging.getLogger(__name__)

try:
    from config import GIPHY_API_KEY as _CONFIGURED_KEY
except ImportError:
    _CONFIGURED_KEY = ""

# Long-standing public GIPHY beta key, documented across GIPHY's own
# historical developer materials for anyone to experiment with. Used
# only if no personal key is set in config.py. It is rate-limited
# (shared across everyone using it) — get your own free key for
# reliable production use, see config.py.
_PUBLIC_DEMO_KEY = "dc6zaTOxFJmzC"

GIPHY_API_KEY = _CONFIGURED_KEY or _PUBLIC_DEMO_KEY
GIPHY_SEARCH_URL = "https://api.giphy.com/v1/gifs/search"

# In-memory cache: query -> (timestamp, [gif_urls])
_cache: dict = {}
_CACHE_TTL = 600  # 10 minutes — keeps replies snappy, results still fresh

# Mood/action -> best search terms (kept human/natural so search
# quality stays high; each call picks a random result from the top N).
_SEARCH_TERMS = {
    "happy":    "anime happy excited",
    "sad":      "anime sad crying",
    "love":     "anime love heart cute",
    "laugh":    "anime laughing lol",
    "angry":    "anime angry mad rage",
    "cute":     "anime cute aww",
    "dance":    "anime dance happy",
    "cool":     "anime cool sunglasses",
    "surprise": "anime surprised shocked",
    "default":  "anime wave hello",
    "slap":     "anime slap",
    "punch":    "anime punch",
    "kiss":     "anime kiss",
    "hug":      "anime hug",
    "bite":     "anime bite",
    "pat":      "anime head pat",
    "murder":   "anime knife dramatic",
    "welcome":  "anime welcome wave",
    "card_win": "anime celebration win",
    "card_tie": "anime tie draw",
    "attack_win": "anime victory battle",
    "ludo":     "dice roll game",
    "fall":     "anime falling cliff",
    "throw":    "anime throw across room",
    "kick":     "anime kick",
    "funny":    "funny meme reaction",
}


async def _giphy_search(query: str, limit: int = 20) -> list:
    """Search GIPHY for GIFs matching `query`. Returns a list of direct
    .gif URLs, or an empty list on any failure (never raises)."""
    now = time.time()
    cached = _cache.get(query)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    try:
        async with aiohttp.ClientSession() as s:
            params = {
                "q": query,
                "api_key": GIPHY_API_KEY,
                "limit": limit,
                "rating": "pg-13",
                "lang": "en",
            }
            async with s.get(
                GIPHY_SEARCH_URL, params=params,
                timeout=aiohttp.ClientTimeout(total=6)
            ) as r:
                if r.status == 429:
                    logger.warning(
                        "GIPHY rate limit hit (429). If you're using the "
                        "shared public demo key, get your own free key at "
                        "https://developers.giphy.com/dashboard/ and set "
                        "GIPHY_API_KEY in config.py."
                    )
                    return []
                if r.status != 200:
                    logger.debug(f"GIPHY search non-200 ({r.status}) for '{query}'")
                    return []
                data = await r.json()
    except Exception as e:
        logger.debug(f"GIPHY search failed for '{query}': {e}")
        return []

    urls = []
    for item in data.get("data", []):
        try:
            # "downsized" keeps file size reasonable while staying a
            # real animated .gif Telegram can send directly by URL.
            gif_url = (
                item.get("images", {}).get("downsized", {}).get("url")
                or item.get("images", {}).get("original", {}).get("url")
            )
            if gif_url:
                urls.append(gif_url)
        except (KeyError, TypeError, AttributeError):
            continue

    if urls:
        _cache[query] = (now, urls)
    return urls


async def get_gif_for_mood(mood: str):
    """
    Return a single GIF URL matching `mood`, or None if GIPHY is
    completely unreachable. Callers should treat None as "skip the
    GIF, send text only" rather than substituting a hardcoded link —
    hardcoded links rot silently over time (this is exactly the bug
    that broke every GIF in this bot before).
    """
    query = _SEARCH_TERMS.get(mood, _SEARCH_TERMS["default"])
    try:
        urls = await _giphy_search(query)
        if urls:
            return random.choice(urls)
    except Exception as e:
        logger.debug(f"get_gif_for_mood unexpected error for '{mood}': {e}")
    return None


async def get_gif_for_query(query: str, fallback_mood: str = "default"):
    """Search GIPHY for an arbitrary free-text query (e.g. a user-supplied
    GIF search term). Falls back to a mood category GIF if nothing is
    found, and to None (not a broken hardcoded link) if nothing works."""
    try:
        urls = await _giphy_search(query)
        if urls:
            return random.choice(urls)
    except Exception as e:
        logger.debug(f"get_gif_for_query unexpected error for '{query}': {e}")
    return await get_gif_for_mood(fallback_mood)
