"""
Tests for the /connect SHARED-MEMORY system (utils/ai_memory + utils/connect).

Real MongoDB isn't available, so a small in-memory fake implementing the
exact Motor operations ai_memory.py uses ($exists / pair_key / uid / ts /
sort / limit / to_list / delete_many) is injected.

Covers the bug that the previous get_memory() only returned the SHARED pair
history — which made each connected user's OWN private memory invisible while
connected ("Iota forgot / isn't sharing properly"). After the fix, get_memory
with shared_with merges: this user's private history + the shared pair
history, while never leaking one partner's private memory to the other.
"""
import asyncio
import os
import unittest

os.environ.setdefault("BOT_TOKEN", "123456:fake")
os.environ.setdefault("OWNER_ID", "111111")
os.environ.setdefault(
    "MONGO_URI", "mongodb+srv://test:test@cluster0.mongodb.net/iota_bot"
)

import utils.mongo_db as mm
from utils import ai_memory as am


# ── tiny in-memory fake Motor ────────────────────────────────────────────────
def _matches(doc, flt):
    for k, cond in flt.items():
        if isinstance(cond, dict):
            for op, v in cond.items():
                if op == "$exists":
                    has = k in doc
                    if (v is True and not has) or (v is False and has):
                        return False
                elif op == "$lt":
                    if not (doc.get(k, 0) < v):
                        return False
                elif op == "$gt":
                    if not (doc.get(k, 0) > v):
                        return False
        else:
            if doc.get(k) != cond:
                return False
    return True


class _Result:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeColl:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = object()
        self.docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    async def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt)]
        return _Result(deleted_count=before - len(self.docs))

    def find(self, flt=None, sort=None, limit=None):
        return _Cur(self.docs, flt or {}, sort, limit)


class _Cur:
    def __init__(self, docs, flt, sort, limit):
        self.docs = docs
        self.flt = flt
        self.sort = sort
        self.limit = limit

    def _matched(self):
        ms = [d for d in self.docs if _matches(d, self.flt)]
        if self.sort:
            for key, direction in self.sort:
                ms.sort(key=lambda d, _k=key: d.get(_k, 0),
                        reverse=(direction == -1))
        if self.limit:
            ms = ms[: self.limit]
        return ms

    async def to_list(self, length=None):
        return self._matched()


class FakeDB:
    def __init__(self):
        self.ai_memory = FakeColl()


_db = FakeDB()
mm.get_db = lambda: _db
am.get_db = lambda: _db


def _run(coro):
    return asyncio.run(coro)


# ═══════════════════════════════════════════════════════════════════════════
class TestSharedMemory(unittest.TestCase):
    def setUp(self):
        _db.ai_memory.docs = []

    def test_shared_messages_visible_to_both(self):
        # A(100) and B(200) connected: A's shared msg is visible to B.
        _run(am.save_memory(100, "user", "I am A, fav color blue", shared_with=200))
        _run(am.save_memory(200, "user", "I am B", shared_with=100))
        a_sees = [d["content"] for d in _run(am.get_memory(100, shared_with=200))]
        b_sees = [d["content"] for d in _run(am.get_memory(200, shared_with=100))]
        self.assertIn("I am A, fav color blue", a_sees)
        self.assertIn("I am A, fav color blue", b_sees)  # B sees A's shared
        self.assertIn("I am B", a_sees)                  # A sees B's shared

    def test_own_private_memory_not_lost_while_connected(self):
        # A's private memory (before connecting) must stay visible to A while
        # connected — this was the regression: it used to vanish.
        _run(am.save_memory(100, "user", "my dog's name is Max"))  # private
        _run(am.save_memory(100, "user", "I am A", shared_with=200))
        seen = [d["content"] for d in _run(am.get_memory(100, shared_with=200))]
        self.assertIn("my dog's name is Max", seen)
        self.assertIn("I am A", seen)

    def test_partner_private_not_leaked(self):
        # A's PRIVATE (non-shared) memory must NOT be visible to B.
        _run(am.save_memory(100, "user", "my secret bank pin 1234"))  # private
        _run(am.save_memory(100, "user", "I am A (shared)", shared_with=200))
        b_sees = [d["content"] for d in _run(am.get_memory(200, shared_with=100))]
        self.assertNotIn("my secret bank pin 1234", b_sees)
        self.assertIn("I am A (shared)", b_sees)

    def test_other_pair_docs_excluded(self):
        # Messages from a different /connect pair must not bleed in.
        _run(am.save_memory(100, "user", "talking to C", shared_with=999))  # other pair
        _run(am.save_memory(100, "user", "talking to B", shared_with=200))
        seen = [d["content"] for d in _run(am.get_memory(100, shared_with=200))]
        self.assertIn("talking to B", seen)
        self.assertNotIn("talking to C", seen)

    def test_disconnect_returns_own_history(self):
        # After disconnect (no shared_with), A still sees everything they own
        # including the messages they shared while connected.
        _run(am.save_memory(100, "user", "private A"))
        _run(am.save_memory(100, "user", "shared A", shared_with=200))
        seen = [d["content"] for d in _run(am.get_memory(100))]
        self.assertIn("private A", seen)
        self.assertIn("shared A", seen)

    def test_per_user_cleanup_keeps_shared(self):
        # Per-user TTL cleanup must NOT delete co-owned shared messages
        # (those are cleaned globally instead).
        _run(am.save_memory(100, "user", "shared with B", shared_with=200))
        # Insert an OLD private message (ts in the past, no pair_key) and then
        # trigger the per-user cleanup path via a get_memory read. The old
        # private message must be purged, but the shared message must survive
        # (shared docs are co-owned and cleaned globally instead).
        _db.ai_memory.docs.append({"uid": 100, "ts": 0, "role": "user",
                                    "content": "old private"})
        _run(am.get_memory(100))
        remaining = [d["content"] for d in _db.ai_memory.docs]
        self.assertIn("shared with B", remaining)  # shared preserved
        self.assertNotIn("old private", remaining)  # old private purged


if __name__ == "__main__":
    unittest.main()
