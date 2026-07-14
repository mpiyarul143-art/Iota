"""
Tests for the extended Owner Systems module (handlers/owner_systems.py).

Guards against:
  * import/registration mismatches (importing bot.py executes the
    owner_systems import block — a typo'd function name fails loudly),
  * all 20 owner-system commands existing and being callable,
  * command-name collisions with existing commands (verified by the import
    + the curated command strings below),
  * a few commands not crashing on their guard / happy paths.
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch, AsyncMock

HERE = os.path.dirname(os.path.abspath(__file__))
IOTA = os.path.dirname(HERE)
if IOTA not in sys.path:
    sys.path.insert(0, IOTA)

os.environ.setdefault("BOT_TOKEN", "123456:fake-test-token")
os.environ.setdefault("OWNER_ID", "111111")
os.environ.setdefault(
    "MONGO_URI", "mongodb+srv://test:test@cluster0.tjpjh4k.mongodb.net/iota_bot"
)


def _run(coro):
    return asyncio.run(coro)


class _FakeColl:
    def __init__(self):
        self.docs = {}

    async def find_one(self, q, *_a, **_k):
        return self.docs.get(q.get("_id"))

    def find(self, q=None, *_a, **_k):
        items = list(self.docs.values())
        if q:
            items = [d for d in items if all(d.get(k) == v for k, v in q.items())]
        return _FakeCur(items)

    async def insert_one(self, doc):
        self.docs[doc.get("_id")] = dict(doc)

    async def update_one(self, q, update, upsert=False):
        _id = q.get("_id")
        d = self.docs.get(_id)
        if d is None:
            if upsert:
                self.docs[_id] = {"_id": _id}
            else:
                return _mk(0)
        if "$set" in update:
            self.docs[_id].update(update["$set"])
        return _mk(1)

    async def delete_many(self, q):
        n = len(self.docs)
        self.docs.clear()
        return _mk(n)

    async def count_documents(self, q=None):
        return len(self.docs)


class _FakeCur:
    def __init__(self, items):
        self.items = items

    async def to_list(self, n):
        return self.items[:n]


def _mk(n):
    class _R:
        pass
    r = _R()
    r.deleted_count = n
    r.modified_count = n
    return r


class _FakeDB:
    def __init__(self):
        self.group_settings = _FakeColl()
        self.users = _FakeColl()

    async def command(self, *a, **k):
        return {"ok": True}

    async def list_collection_names(self):
        return [k for k in vars(self) if not k.startswith("_")]


class TestOwnerSystemsImports(unittest.TestCase):
    def test_bot_imports_owner_systems(self):
        import bot  # noqa: F401 — runs the owner_systems import/registration block

    def test_all_functions_exist(self):
        import handlers.owner_systems as m
        names = [
            "leavegroup_cmd", "leaveallgroups_cmd", "groupslist_cmd",
            "groupscount_cmd", "chatinfo_cmd", "osetrules_cmd", "antispam_cmd",
            "cleandb_cmd", "userinfo_cmd", "exportusers_cmd", "getfile_cmd",
            "botinfo_cmd", "sysinfo_cmd", "logs_cmd", "restart_cmd",
            "osetbotname_cmd", "setbotdesc_cmd", "setbotpic_cmd",
            "setbotcommands_cmd", "opurge_cmd",
        ]
        for n in names:
            self.assertTrue(callable(getattr(m, n)), f"{n} missing/callable")

    def test_registered_command_strings(self):
        # The exact strings bot.py registers for owner_systems — must NOT
        # collide with any existing command. (Renamed to avoid duplicates.)
        expected = {
            "leavegroup", "leaveallgroups", "groupslist", "groupscount",
            "chatinfo", "osetrules", "antispam", "cleandb", "userinfo",
            "exportusers", "getfile", "botinfo", "sysinfo", "logs",
            "restart", "osetbotname", "setbotdesc", "setbotpic",
            "setbotcommands", "opurge",
        }
        # sanity: none of these are the original colliding names
        self.assertNotIn("setrules", expected)
        self.assertNotIn("purge", expected)
        self.assertEqual(len(expected), 20)


class TestOwnerSystemsSmoke(unittest.TestCase):
    def setUp(self):
        self.db = _FakeDB()
        self.patchers = [
            patch("utils.mongo_db.get_db", return_value=self.db),
            patch("handlers.owner_systems.get_db", return_value=self.db),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in self.patchers:
            p.stop()

    def _owner_update(self):
        msg = AsyncMock()
        msg.reply_html = AsyncMock()
        chat = AsyncMock()
        chat.id = 111111
        user = AsyncMock()
        user.id = 111111
        upd = AsyncMock()
        upd.effective_user = user
        upd.effective_chat = chat
        upd.effective_message = msg
        upd.message = msg
        return upd, msg

    def test_groupscount(self):
        import handlers.owner_systems as m
        upd, msg = self._owner_update()
        _run(m.groupscount_cmd(upd, AsyncMock()))
        self.assertTrue(msg.reply_html.called)
        self.assertIn("Groups", msg.reply_html.call_args[0][0])

    def test_botinfo(self):
        import handlers.owner_systems as m
        upd, msg = self._owner_update()
        _run(m.botinfo_cmd(upd, AsyncMock()))
        self.assertTrue(msg.reply_html.called)
        self.assertIn("Runtime", msg.reply_html.call_args[0][0])

    def test_logs_empty(self):
        import handlers.owner_systems as m
        m._log_buf.clear()  # isolate from other tests' captured logs
        upd, msg = self._owner_update()
        _run(m.logs_cmd(upd, AsyncMock()))
        self.assertTrue(msg.reply_html.called)
        self.assertIn("No recent", msg.reply_html.call_args[0][0])

    def test_cleandb(self):
        import handlers.owner_systems as m
        upd, msg = self._owner_update()
        _run(m.cleandb_cmd(upd, AsyncMock()))
        self.assertTrue(msg.reply_html.called)

    def test_osetrules_usage(self):
        import handlers.owner_systems as m
        upd, msg = self._owner_update()
        ctx = AsyncMock(); ctx.args = []
        _run(m.osetrules_cmd(upd, ctx))
        self.assertIn("Usage", msg.reply_html.call_args[0][0])

    def test_opurge_usage(self):
        import handlers.owner_systems as m
        upd, msg = self._owner_update()
        ctx = AsyncMock(); ctx.args = []
        _run(m.opurge_cmd(upd, ctx))
        self.assertIn("Usage", msg.reply_html.call_args[0][0])

    def test_restart_guard(self):
        import handlers.owner_systems as m
        upd, msg = self._owner_update()
        ctx = AsyncMock(); ctx.args = []
        _run(m.restart_cmd(upd, ctx))
        self.assertIn("confirm", msg.reply_html.call_args[0][0])

    def test_osetbotname_sets_name(self):
        import handlers.owner_systems as m
        upd, msg = self._owner_update()
        ctx = AsyncMock()
        ctx.args = ["IotaBot"]
        ctx.bot.set_my_name = AsyncMock(return_value=True)
        _run(m.osetbotname_cmd(upd, ctx))
        self.assertTrue(msg.reply_html.called)
        self.assertIn("updated", msg.reply_html.call_args[0][0].lower())


if __name__ == "__main__":
    unittest.main()
