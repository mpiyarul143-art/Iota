from urllib.parse import quote_plus

BOT_TOKEN      = "8740709364:AAF0i0ZsJlgbIK1mXK85NUVJwfn7AMljLmU"
OWNER_ID       = 6998484205
OWNER_USERNAME = "@Boobies_00"
BOT_NAME       = "Iota"

_MONGO_PASS = "YOUR_MONGODB_PASSWORD"
MONGO_URI = (
    f"mongodb+srv://kalu923476:{quote_plus(_MONGO_PASS)}"
    "@cluster0.tjpjh4k.mongodb.net/iota_bot"
    "?retryWrites=true&w=majority&appName=Cluster0"
)
DB_NAME = "iota_bot"

SARVAM_API_KEY  = "sk_7g5tp3qz_BJC0dd3mk7xsUpC5PCDK4YF4"
SARVAM_CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"
SARVAM_TTS_URL  = "https://api.sarvam.ai/text-to-speech"

# ── Economy ───────────────────────────────────
DAILY_NORMAL        = 500
DAILY_PREMIUM       = 1250
DAILY_KILLS_NORMAL  = 200
DAILY_KILLS_PREMIUM = 400
DAILY_ROBS_NORMAL   = 150
DAILY_ROBS_PREMIUM  = 300
ROB_MAX_NORMAL      = 10_000
ROB_MAX_PREMIUM     = 100_000
TAX_NORMAL          = 0.10
TAX_PREMIUM         = 0.05
KILL_REWARD_NORMAL  = (100, 200)
KILL_REWARD_PREMIUM = (200, 400)
XP_KILL_NORMAL      = (0,   5)
XP_KILL_PREMIUM     = (10, 20)
XP_ROB_PER_1K       = 1
XP_PER_LEVEL        = 1000
REVIVE_COST         = 600    # coins to revive self or others
PROTECT_1D_COST     = 0      # FREE for all
PROTECT_2D_COST     = 1000   # Premium only

# ── Premium ───────────────────────────────────
PREMIUM_PRICE_COINS    = 50_000
PREMIUM_PRICE_STARS    = 100   # Goes to owner's Telegram account
PREMIUM_DURATION_DAYS  = 90    # 3 months
GEMS_PRICE_STARS       = 50
GEMS_PRICE_COINS       = 10_000

# ── Card ──────────────────────────────────────
CARD_FEE_PERCENT = 5
CARD_XP_WIN      = 250
CARD_XP_LOSS     = 50

# ── Items ─────────────────────────────────────
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

# ── Village ───────────────────────────────────
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

GLOBAL_COUPONS: dict = {
    "nobi10":  1000,
    "iota50":  5000,
    "welcome": 500,
}

# ── Multiple GIFs per action ──────────────────
import random
_GIFS = {
    "slap":      ["https://media.giphy.com/media/uqSU9IEYEKAbS/giphy.gif",
                  "https://media.giphy.com/media/Zau0yrl17uzdK/giphy.gif",
                  "https://media.giphy.com/media/jLeyZWgtwgr2U/giphy.gif"],
    "punch":     ["https://media.giphy.com/media/xT8qBvH1pAhtfSx52U/giphy.gif",
                  "https://media.giphy.com/media/3Zl9JHrn9XZNS/giphy.gif"],
    "kiss":      ["https://media.giphy.com/media/G3va31oEEnIkM/giphy.gif",
                  "https://media.giphy.com/media/bGm9FuBCGg4SY/giphy.gif",
                  "https://media.giphy.com/media/zkppEMFvRX5FC/giphy.gif",
                  "https://media.giphy.com/media/mXnO9IiWMYnDa/giphy.gif"],
    "hug":       ["https://media.giphy.com/media/od5H3PmEG5EVq/giphy.gif",
                  "https://media.giphy.com/media/l2QDM9Jnim1YVILXa/giphy.gif",
                  "https://media.giphy.com/media/3M4NpbLCTxBqU/giphy.gif"],
    "bite":      ["https://media.giphy.com/media/l2R013yx6S7K9YqMM/giphy.gif",
                  "https://media.giphy.com/media/BI2as38GDMpKg/giphy.gif"],
    "pat":       ["https://media.giphy.com/media/5UZaRieUCvxX1UFZYU/giphy.gif"],
    "murder":    ["https://media.giphy.com/media/l2RsnnJ4pFNTXMwKc/giphy.gif"],
    "welcome":   ["https://media.giphy.com/media/3ohzdIuqJoo8QdKlnW/giphy.gif",
                  "https://media.giphy.com/media/g9582DNuQppxC/giphy.gif"],
    "card_win":  ["https://media.giphy.com/media/3o7abKhOpu0NwenH3O/giphy.gif"],
    "card_tie":  ["https://media.giphy.com/media/xT9IgG50Lg7rusXgqU/giphy.gif"],
    "attack_win":["https://media.giphy.com/media/l0HlBO7eyXzSZkJri/giphy.gif"],
    "ludo":      ["https://media.giphy.com/media/l4FGuhL4U2WyjdkaY/giphy.gif"],
}
def get_gif(action: str) -> str:
    gifs = _GIFS.get(action, [])
    return random.choice(gifs) if gifs else ""
