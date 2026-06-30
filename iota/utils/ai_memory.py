"""
Iota AI Memory System
- Per-user private memory (30 day auto-delete)
- Group context (only public info: names/usernames)
- Privacy: no cross-user personal data sharing
"""
import time
from utils.mongo_db import get_db

MEMORY_TTL_DAYS = 30

async def save_memory(uid: int, role: str, content: str):
    """Save one message to user's private memory."""
    db = get_db()
    await db.ai_memory.insert_one({
        "uid": uid, "role": role, "content": content,
        "ts": int(time.time())
    })

async def get_memory(uid: int, limit=12) -> list:
    """Get last N messages for this user only."""
    db = get_db()
    now = int(time.time())
    cutoff = now - (MEMORY_TTL_DAYS * 86400)
    # Delete old memories first
    await db.ai_memory.delete_many({"uid": uid, "ts": {"$lt": cutoff}})
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
