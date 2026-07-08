"""
Iota AI Memory System
- Per-user private memory (30 day auto-delete)
- Group context (only public info: names/usernames)
- Privacy: no cross-user personal data sharing
"""
import time
from utils.mongo_db import get_db

MEMORY_TTL_DAYS = 30

async def save_memory(uid: int, role: str, content: str, shared_with: int = None):
    """
    Save one message to memory. If `shared_with` is given (the partner's
    user id, from an active /connect), the message is tagged with a
    stable pair-key so BOTH users' get_memory() calls can see it — this
    is what makes Iota's answers consistent for two connected users
    instead of remembering each of them separately.
    """
    db = get_db()
    doc = {"uid": uid, "role": role, "content": content, "ts": int(time.time())}
    if shared_with is not None:
        doc["pair_key"] = _pair_key(uid, shared_with)
    await db.ai_memory.insert_one(doc)

def _pair_key(a: int, b: int) -> str:
    """Deterministic, order-independent key for two user ids."""
    lo, hi = sorted([a, b])
    return f"{lo}:{hi}"

async def get_memory(uid: int, limit=12, shared_with: int = None) -> list:
    """
    Get recent messages for this user. If `shared_with` is given (an
    active connection partner), this returns the SHARED conversation
    history for the pair (both users' messages, in order) instead of
    just this user's own — so Iota's replies stay consistent for either
    of them while they're connected.
    """
    db = get_db()
    now = int(time.time())
    cutoff = now - (MEMORY_TTL_DAYS * 86400)
    await db.ai_memory.delete_many({"uid": uid, "ts": {"$lt": cutoff}})

    if shared_with is not None:
        pk = _pair_key(uid, shared_with)
        docs = await db.ai_memory.find(
            {"pair_key": pk}, sort=[("ts", -1)], limit=limit
        ).to_list(limit)
        docs.reverse()
        return [{"role": d["role"], "content": d["content"]} for d in docs]

    docs = await db.ai_memory.find(
        {"uid": uid}, sort=[("ts", -1)], limit=limit
    ).to_list(limit)
    docs.reverse()
    return [{"role": d["role"], "content": d["content"]} for d in docs]

async def clear_memory(uid: int):
    await get_db().ai_memory.delete_many({"uid": uid})

async def cleanup_old_memories():
    """Background job: delete memories older than 30 days."""
    cutoff = int(time.time()) - (MEMORY_TTL_DAYS * 86400)
    result = await get_db().ai_memory.delete_many({"ts": {"$lt": cutoff}})
    return result.deleted_count

async def get_group_member_names(chat_id: int, bot) -> str:
    """Get public info of group members for context (names only)."""
    try:
        admins = await bot.get_chat_administrators(chat_id)
        names = [a.user.first_name for a in admins if not a.user.is_bot]
        return ", ".join(names[:10]) if names else ""
    except Exception:
        return ""
