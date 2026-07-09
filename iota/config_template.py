"""
Iota Bot — ENV-DRIVEN CONFIG TEMPLATE  (committed to the repo)

This file is the CANONICAL, secret-free configuration. It is copied to
`config.py` at deploy/start time by `start.sh` ONLY when a real `config.py`
does not already exist (e.g. on Render, where the gitignored local
`config.py` is not in the cloned repo).

All SECRETS and deploy-specific values are read from environment variables.
Set these on Render (or in your shell) — see the deploy guide. If a secret is
missing, the bot will refuse to start with a clear error instead of silently
failing on every command.

All non-secret TUNING constants (economy numbers, items, village, etc.) live
here inline so they are version-controlled and identical everywhere.
"""
import os
from urllib.parse import quote_plus


def _env(name: str, default: str = "") -> str:
    """Read an env var; returns '' (never None) when unset."""
    return os.environ.get(name, default) or ""


def _require(name: str) -> str:
    """Read a required secret; raise a clear error if missing."""
    val = _env(name)
    if not val:
        raise RuntimeError(
            f"❌ Required env var {name} is not set. "
            f"Set it in your deployment environment (e.g. Render dashboard)."
        )
    return val


# ── Bot credentials ───────────────────────────────────────────────────────
BOT_TOKEN = _require("BOT_TOKEN")

# ── Owner identity ────────────────────────────────────────────────────────
OWNER_ID       = int(_env("OWNER_ID", "0") or "0")
OWNER_USERNAME = _env("OWNER_USERNAME", "@owner")
OWNER_NAME     = _env("OWNER_NAME", "Owner")

# ── Bot's own identity ────────────────────────────────────────────────────
BOT_NAME       = _env("BOT_NAME", "Iota")
BOT_USERNAME   = _env("BOT_USERNAME", "Its_iotabot")
BOT_AGE        = int(_env("BOT_AGE", "17") or "17")

# ── Update channel (leave blank to hide the button) ──────────────────────
UPDATE_CHANNEL_USERNAME = _env("UPDATE_CHANNEL_USERNAME", "")

# ── Ludo Mini App ─────────────────────────────────────────────────────────
# On Render, WEBAPP_BASE_URL should be your live Render URL, e.g.
# https://iota-bot.onrender.com  (set via env). WEBAPP_PORT is taken from
# Render's $PORT so the Mini App server binds to the port Render expects.
WEBAPP_BASE_URL = _env("WEBAPP_BASE_URL", "")
WEBAPP_PORT     = int(_env("PORT", _env("WEBAPP_PORT", "8080")) or "8080")

# ── MongoDB ───────────────────────────────────────────────────────────────
# Preferred: provide a FULL connection string via MONGO_URI.
# Fallback: provide MONGO_USER + MONGO_PASS + MONGO_CLUSTER and we build it.
_MONGO_USER  = _env("MONGO_USER", "kalu923476")
_MONGO_PASS  = _env("MONGO_PASS", "")
_MONGO_CLUSTER = _env("MONGO_CLUSTER", "cluster0.tjpjh4k.mongodb.net")
if _env("MONGO_URI"):
    MONGO_URI = _env("MONGO_URI")
else:
    if not _MONGO_PASS:
        raise RuntimeError(
            "❌ Set MONGO_URI (full connection string) or MONGO_PASS on Render."
        )
    MONGO_URI = (
        f"mongodb+srv://{_MONGO_USER}:{quote_plus(_MONGO_PASS)}"
        f"@{_MONGO_CLUSTER}/iota_bot"
        f"?retryWrites=true&w=majority&appName=Cluster0"
    )
DB_NAME = _env("DB_NAME", "iota_bot")

# ── Sarvam (TTS) ──────────────────────────────────────────────────────────
SARVAM_API_KEY  = _env("SARVAM_API_KEY", "")
SARVAM_CHAT_URL = _env("SARVAM_CHAT_URL", "https://api.sarvam.ai/v1/chat/completions")
SARVAM_TTS_URL  = _env("SARVAM_TTS_URL", "https://api.sarvam.ai/text-to-speech")

# ── AI Providers ──────────────────────────────────────────────────────────
# Provide keys as a single space/comma/newline-joined string in each env var.
def _list_env(name: str, fallback: list) -> list:
    raw = _env(name)
    if not raw:
        return list(fallback)
    return [k.strip() for k in raw.replace("\n", ",").split(",") if k.strip()]

GROQ_API_KEYS = _list_env("GROQ_API_KEYS", [])
GEMINI_API_KEYS = _list_env("GEMINI_API_KEYS", [])
OPENROUTER_API_KEYS = _list_env("OPENROUTER_API_KEYS", [])
CLOUDFLARE_API_KEYS = _list_env("CLOUDFLARE_API_KEYS", [])
CLOUDFLARE_ACCOUNT_ID = _env("CLOUDFLARE_ACCOUNT_ID", "")

# ── Economy ───────────────────────────────────────────────────────────────
DAILY_NORMAL        = 500
DAILY_PREMIUM       = 1250
DAILY_KILLS_NORMAL  = 200
DAILY_KILLS_PREMIUM = 400
DAILY_ROBS_NORMAL   = 150
DAILY_ROBS_PREMIUM  = 300
ROB_MAX_NORMAL      = 10_000
ROB_MAX_PREMIUM     = 100_000

# ── Weekly / Monthly (used by /weekly and /monthly in handlers/economy.py)
# Scaled up from the daily amounts (≈7× and ≈30×) so the bigger cooldown
# feels worth the wait.
WEEKLY_NORMAL       = 3_000
WEEKLY_PREMIUM      = 7_500
MONTHLY_NORMAL      = 15_000
MONTHLY_PREMIUM     = 37_500
HIGH_VALUE_THEFT_THRESHOLD = 5_000
TAX_NORMAL          = 0.10
TAX_PREMIUM         = 0.05
KILL_REWARD_NORMAL  = (100, 200)
KILL_REWARD_PREMIUM = (200, 400)
XP_KILL_NORMAL      = (0,   5)
XP_KILL_PREMIUM     = (10, 20)
XP_ROB_PER_1K       = 1
XP_PER_LEVEL        = 1000
REVIVE_COST         = 600
PROTECT_1D_COST     = 400
PROTECT_2D_COST     = 1000

# ── Premium ───────────────────────────────────────────────────────────────
PREMIUM_PRICE_COINS    = 50_000
PREMIUM_PRICE_STARS    = 100
PREMIUM_DURATION_DAYS  = 90
GEMS_PRICE_STARS       = 50
GEMS_PRICE_COINS       = 10_000

# ── Card ──────────────────────────────────────────────────────────────────
CARD_FEE_PERCENT = 5
CARD_XP_WIN      = 250
CARD_XP_LOSS     = 50
CARD_MIN_BET     = 10
CARD_MAX_BET     = 100_000
CARD_LOBBY_TIMEOUT_SECONDS = 90

# ── Items ─────────────────────────────────────────────────────────────────
ITEMS = {
    "rose":         ("🌹", 500),
    "chocolate":    ("🍫", 800),
    "ring":         ("💍", 2000),
    "teddy":        ("🧸", 1500),
    "pizza":        ("🍕", 600),
    "surprise_box": ("🎁", 2500),
    "puppy":        ("🐶", 3000),
    "cake":         ("🎂", 1000),
    "love_letter":  ("💌", 400),
    "cat":          ("🐱", 2500),
    "tulip":        ("🌷", 1500),
    "bmw":          ("🏎", 5000),
    "diamond":      ("💎", 8000),
    "crown":        ("👑", 15000),
}

# ── Village ───────────────────────────────────────────────────────────────
MINE_INTERVAL   = 3600
CITIZEN_START   = 50
TROOP_TYPES = {
    "warriors": {"hp":50,  "damage":15, "cost_coins":100},
    "archers":  {"hp":30,  "damage":25, "cost_coins":150},
    "knights":  {"hp":100, "damage":20, "cost_coins":200},
    "mages":    {"hp":40,  "damage":40, "cost_coins":300},
}
WALL_TYPES = {
    "wood":  {"hp":300,  "cost_wood":200},
    "stone": {"hp":700,  "cost_stone":300},
    "iron":  {"hp":1500, "cost_iron":400},
}
DEFENSE_TYPES = {
    "archer_tower": {"hp":300, "damage":20, "cost_coins":500},
    "cannon":       {"hp":500, "damage":35, "cost_coins":800},
}
MARKET_PRICES = {"wood": 50, "stone": 120, "iron": 300}
MARKET_SELL_RATIO = 0.7

GLOBAL_COUPONS: dict = {
    "nobi10":  1000,
    "iota50":  5000,
    "welcome": 500,
}

# ── GIFs (optional — get your own free GIPHY key) ─────────────────────────
GIPHY_API_KEY = _env("GIPHY_API_KEY", "")
