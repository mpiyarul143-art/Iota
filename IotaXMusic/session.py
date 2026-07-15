"""
Iota Music Bot — Pyrogram assistant session generator.

The bot REQUIRES at least one Pyrogram "assistant" session (STRING_SESSION)
to join voice chats and stream music. Run this script once to generate it:

    python3 session.py

It will ask for the assistant account's phone number, the login code Telegram
sends, and (if enabled) the 2FA password. When done, it prints a session
STRING — copy that value into IotaXMusic/.env as STRING_SESSION.
"""
import os
from pyrogram import Client
from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "33489956"))
API_HASH = os.getenv("API_HASH", "6dcab6618cef41125017059e455fbec1")


def main() -> None:
    print("» Generating Iota Music Bot assistant session string…")
    with Client("iota_music_assistant", api_id=API_ID, api_hash=API_HASH) as app:
        session_string = app.export_session_string()
    print("\n✅ Session string generated. Copy everything below into .env:\n")
    print(session_string)
    print(
        "\nThen set STRING_SESSION=<above> in IotaXMusic/.env and start the bot "
        "with: python3 -m IotaXMedia"
    )


if __name__ == "__main__":
    main()
