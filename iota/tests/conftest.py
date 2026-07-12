"""
Pytest conftest for the Iota test-suite.

The bot's `config` module reads required secrets (BOT_TOKEN, OWNER_ID,
MONGO_URI) from the environment at import time and raises RuntimeError if
they're missing. Tests therefore need a minimal valid environment so that
`import config` (pulled in transitively by almost every handler) succeeds.

Set these defaults BEFORE any test module is collected. Individual tests
that need different values (e.g. config-validation tests) override them
locally.
"""
import os

os.environ.setdefault("BOT_TOKEN", "123456:fake-test-token")
os.environ.setdefault("OWNER_ID", "111111")
os.environ.setdefault(
    "MONGO_URI",
    "mongodb+srv://test:test@cluster0.tjpjh4k.mongodb.net/iota_bot",
)
