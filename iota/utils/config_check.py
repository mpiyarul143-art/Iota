"""
Iota — startup config validation.

Catches the most common "bot starts but everything is broken" mistakes
BEFORE run_polling(), with a single clear message instead of a cryptic
crash later (e.g. a missing MONGO_URI that only surfaces inside /bal).

Call `validate_config()` early in bot.py main(); it raises RuntimeError
with an actionable message on any problem.
"""


def validate_config():
    """Validate the loaded config module. Raises RuntimeError if invalid."""
    import config as cfg

    problems = []

    # Bot token
    token = getattr(cfg, "BOT_TOKEN", "")
    if not token or ":" not in str(token):
        problems.append(
            "BOT_TOKEN is missing or malformed (expected '<id>:<hash>').")

    # Owner id must be a positive int (0 means OWNER_ID was never set)
    owner_id = getattr(cfg, "OWNER_ID", 0)
    try:
        owner_id = int(owner_id)
    except Exception:
        owner_id = 0
    if owner_id <= 0:
        problems.append(
            "OWNER_ID is not set (or is 0). Set it to your Telegram user id.")

    # MongoDB connection string
    uri = getattr(cfg, "MONGO_URI", "")
    if not uri or not str(uri).startswith(("mongodb://", "mongodb+srv://")):
        problems.append(
            "MONGO_URI is missing/invalid. Set MONGO_URI (or MONGO_PASS).")

    # DB name
    if not getattr(cfg, "DB_NAME", ""):
        problems.append("DB_NAME is empty.")

    # Webapp port sane
    port = getattr(cfg, "WEBAPP_PORT", 0)
    try:
        port = int(port)
    except Exception:
        port = 0
    if port <= 0 or port > 65535:
        problems.append("WEBAPP_PORT is not a valid port (1-65535).")

    if problems:
        lines = "\n".join(f"  • {p}" for p in problems)
        raise RuntimeError(
            "❌ Iota config invalid — fix these before starting:\n" + lines
        )
    return True
