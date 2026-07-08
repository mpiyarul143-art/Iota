"""
Iota Bot — Connect (Shared Memory)

Lets two users "connect" so Iota treats their AI-chat memory as shared —
if either of them tells Iota something, she remembers it consistently
for BOTH of them, instead of giving different answers to each person
separately. Think of it as a shared context/inside-jokes layer between
two friends (or a couple, etc.) chatting with Iota.

FLOW
─────
1. User A: /connect (reply to User B, or /connect @username)
   → Iota DMs User B an Accept/Deny request.
   → If User B has never DM'd the bot, Iota tells User A that instead
     of silently failing (Telegram blocks bots from DMing users who
     haven't started a chat with them first — a platform rule, not
     something the bot can bypass).
2. User B taps Accept → both users get a DM confirming the connection,
   including a unique connect ID and how long it will last.
   User B taps Deny → User A gets a DM saying the request was declined.
3. While connected, _respond() in ai_chat.py merges both users' recent
   memory into one shared context, so Iota's answers stay consistent
   for either of them.
4. After the configured duration, a background job automatically
   disconnects the pair and DMs both of them that the sync ended.
5. /disconnect ends an active connection early (either party can end it).
6. /connect_id shows the caller's current connection ID, if any.

DATA MODEL (MongoDB `connections` collection)
────────────────────────────────────────────
  {
    "_id": <connect_id (str)>,
    "user_a": <uid>, "user_b": <uid>,
    "status": "pending" | "active" | "expired" | "denied",
    "created_at": <ts>, "expires_at": <ts>,
  }
"""
import logging
import time
import uuid

from telegram import InlineKeyboardMarkup, InlineKeyboardButton
from telegram.error import Forbidden, BadRequest

from utils.mongo_db import get_db, ensure_user, get_user
from utils.helpers import mention
from utils.safe_html import safe_html

logger = logging.getLogger(__name__)

# How long a connection lasts once accepted, in seconds. 24 hours by
# default — long enough to matter, short enough that it doesn't become a
# permanent, forgotten state neither user intended.
CONNECT_DURATION_SECONDS = 24 * 3600


def _new_id() -> str:
    return str(uuid.uuid4())[:8]


async def get_active_connection(uid: int) -> dict | None:
    """Returns the active connection doc this user is part of, or None."""
    db = get_db()
    now = int(time.time())
    return await db.connections.find_one({
        "status": "active",
        "expires_at": {"$gt": now},
        "$or": [{"user_a": uid}, {"user_b": uid}],
    })


async def get_partner_id(uid: int) -> int | None:
    """If this user is actively connected, return the OTHER user's id."""
    conn = await get_active_connection(uid)
    if not conn:
        return None
    return conn["user_b"] if conn["user_a"] == uid else conn["user_a"]


async def create_request(inviter_id: int, target_id: int) -> tuple[bool, str]:
    """
    Creates a pending connection request. Returns (ok, reason) — reason
    is a human-readable error to show the inviter if ok is False.
    """
    if inviter_id == target_id:
        return False, "You can't connect with yourself! 😅"

    db = get_db()
    if await get_active_connection(inviter_id):
        return False, "You're already connected with someone! Use /disconnect first."
    if await get_active_connection(target_id):
        return False, "That user is already connected with someone else right now."

    # Clean up any old pending request between this exact pair so a
    # re-request doesn't collide with a stale one.
    await db.connections.delete_many({
        "status": "pending",
        "$or": [
            {"user_a": inviter_id, "user_b": target_id},
            {"user_a": target_id, "user_b": inviter_id},
        ],
    })

    cid = _new_id()
    await db.connections.insert_one({
        "_id": cid,
        "user_a": inviter_id,
        "user_b": target_id,
        "status": "pending",
        "created_at": int(time.time()),
        "expires_at": 0,  # set only once accepted
    })
    return True, cid


async def respond_to_request(cid: str, accept: bool) -> dict | None:
    """Accept or deny a pending request. Returns the updated doc, or None if not found/already resolved."""
    db = get_db()
    conn = await db.connections.find_one({"_id": cid, "status": "pending"})
    if not conn:
        return None
    if accept:
        expires = int(time.time()) + CONNECT_DURATION_SECONDS
        await db.connections.update_one(
            {"_id": cid}, {"$set": {"status": "active", "expires_at": expires}}
        )
        conn["status"] = "active"
        conn["expires_at"] = expires
    else:
        await db.connections.update_one({"_id": cid}, {"$set": {"status": "denied"}})
        conn["status"] = "denied"
    return conn


async def disconnect(uid: int) -> dict | None:
    """Ends the caller's active connection early. Returns the closed doc, or None if not connected."""
    conn = await get_active_connection(uid)
    if not conn:
        return None
    db = get_db()
    await db.connections.update_one({"_id": conn["_id"]}, {"$set": {"status": "expired"}})
    return conn


async def expire_due_connections(bot):
    """
    Background job: find connections whose time is up, close them, and
    DM both users that the sync ended. Call this periodically (see
    bot.py's job loop) — mirrors the pattern of other *_job() functions
    already in the codebase (protection_alert_job, auto_daily_job, etc.).
    """
    db = get_db()
    now = int(time.time())
    due = await db.connections.find({
        "status": "active", "expires_at": {"$lte": now}
    }).to_list(1000)
    for conn in due:
        await db.connections.update_one({"_id": conn["_id"]}, {"$set": {"status": "expired"}})
        for uid in (conn["user_a"], conn["user_b"]):
            try:
                await bot.send_message(
                    uid,
                    "🔌 <b>Connection ended!</b>\n\n"
                    "Your memory sync has automatically expired. Iota will "
                    "go back to remembering your conversations separately.\n\n"
                    "Want to reconnect? Just use /connect again!",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.debug(f"expire_due_connections: DM failed for {uid}: {e}")


def request_keyboard(cid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data=f"conn_accept_{cid}"),
        InlineKeyboardButton("❌ Deny", callback_data=f"conn_deny_{cid}"),
    ]])
