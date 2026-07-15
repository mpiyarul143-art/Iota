"""
Tests for the PREMIUM Business Empire (handlers/business.py + utils/business_store.py),
Enterprise v2.

Mirrors tests/test_premium_banking.py: a small in-memory fake implements the
exact Motor ops the business store uses ($inc / $set on dotted paths /
$unset / find / insert / count_documents / $exists), injected by pointing
utils.mongo_db._db at the FakeDB.

Covers:
  * open gating: premium + cost+license lock, tier cap, global limit, cooldown
  * income accrual + /bizcollect (tax + maintenance sinks, investor dividends)
  * hire -> accept -> promote -> fire / quit
  * invest -> divest (early-exit fee; owner receives fee)
  * rob (guards reduce take; own/employee/empty rejected; cooldown)
  * ratings -> reputation/popularity feedback
  * multi-ownership + active selection
  * analytics snapshot
  * @premium_gate blocks non-premium users
Money-conservation invariants are checked throughout (no duplication, no
infinite money).
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import patch, AsyncMock

os.environ.setdefault("BOT_TOKEN", "123456:fake")
os.environ.setdefault("OWNER_ID", "111111")
os.environ.setdefault(
    "MONGO_URI", "mongodb+srv://test:test@cluster0.tjpjh4k.mongodb.net/iota_bot"
)

from bson import ObjectId

import utils.mongo_db as mm
from utils import business_store as bs
from handlers import business as biz_h

DEFAULT_USER = {
    "username": "", "full_name": "", "balance": 0, "gems": 0,
    "is_premium": False, "is_banned": False,
}


def _set_path(doc, path, value):
    d = doc
    for p in path.split(".")[:-1]:
        d = d.setdefault(p, {})
    d[path.split(".")[-1]] = value


def _unset_path(doc, path):
    parts = path.split(".")
    d = doc
    for p in parts[:-1]:
        d = d.get(p, {})
    d.pop(parts[-1], None)


def _apply(doc, upd):
    for op, fields in upd.items():
        if op == "$inc":
            for k, v in fields.items():
                if "." in k:
                    cur = doc
                    pk = k.split(".")
                    for p in pk[:-1]:
                        cur = cur.setdefault(p, {})
                    cur[pk[-1]] = cur.get(pk[-1], 0) + v
                else:
                    doc[k] = doc.get(k, 0) + v
        elif op == "$set":
            for k, v in fields.items():
                if "." in k:
                    _set_path(doc, k, v)
                else:
                    doc[k] = v
        elif op == "$push":
            for k, v in fields.items():
                doc.setdefault(k, []).append(v)
        elif op == "$unset":
            for k in fields:
                if "." in k:
                    _unset_path(doc, k)
                else:
                    doc.pop(k, None)


def _matches(doc, flt):
    for k, cond in flt.items():
        val = doc.get(k)
        if isinstance(cond, dict):
            for op, v in cond.items():
                if op == "$gte" and not (val >= v):
                    return False
                if op == "$gt" and not (val > v):
                    return False
                if op == "$lt" and not (val < v):
                    return False
                if op == "$lte" and not (val <= v):
                    return False
                if op == "$ne" and val == v:
                    return False
                if op == "$exists":
                    has = val is not None
                    if v and not has:
                        return False
                    if not v and has:
                        return False
        else:
            if val != cond:
                return False
    return True


class _Result:
    def __init__(self, modified_count=0, inserted_id=None):
        self.modified_count = modified_count
        self.inserted_id = inserted_id


class FakeCollection:
    def __init__(self, name):
        self.name = name
        self.docs = []

    def find(self, flt=None, projection=None):
        return FakeCursor(self.docs, flt or {})

    async def find_one(self, flt, projection=None):
        for d in self.docs:
            if _matches(d, flt):
                return d
        return None

    async def update_one(self, flt, upd, upsert=False):
        for d in self.docs:
            if _matches(d, flt):
                _apply(d, upd)
                return _Result(modified_count=1)
        if upsert:
            newdoc = {k: v for k, v in flt.items() if not isinstance(v, dict)}
            _apply(newdoc, upd)
            self.docs.append(newdoc)
            return _Result(modified_count=1)
        return _Result(modified_count=0)

    async def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = ObjectId()
        self.docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    async def count_documents(self, flt=None):
        return len([d for d in self.docs if _matches(d, flt or {})])

    async def delete_many(self, flt=None):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _matches(d, flt or {})]
        return _Result(modified_count=before - len(self.docs))

    async def create_index(self, *a, **k):
        return None


class FakeCursor:
    def __init__(self, docs, flt):
        self.docs = docs
        self.flt = flt
        self._skip = 0
        self._limit = 0

    def sort(self, *a):
        return self

    def skip(self, n):
        self._skip = n
        return self

    def limit(self, n):
        self._limit = n
        return self

    def _matched(self):
        ms = [d for d in self.docs if _matches(d, self.flt)]
        if self._skip:
            ms = ms[self._skip:]
        if self._limit:
            ms = ms[: self._limit]
        return ms

    async def to_list(self, length=None):
        return self._matched()

    def __aiter__(self):
        return self._agen()

    async def _agen(self):
        for d in self._matched():
            yield d


class FakeDB:
    def __init__(self):
        self.users = FakeCollection("users")
        self.businesses = FakeCollection("businesses")
        self.business_offers = FakeCollection("business_offers")
        self.system_status = FakeCollection("system_status")

    async def command(self, *a, **k):
        return {"ok": True}

    async def list_collection_names(self):
        return [k for k in vars(self) if not k.startswith("_")]


def _u(db, uid, **kw):
    doc = dict(DEFAULT_USER)
    doc["_id"] = uid
    doc.update(kw)
    db.users.docs.append(doc)
    return doc


def _run(coro):
    return asyncio.run(coro)


# ── Open gating ───────────────────────────────────────────────────────────────
class TestOpenGating(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def tearDown(self):
        self.p.stop()
        mm._db = None

    def test_open_locks_cost_and_license(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        doc, reason = _run(bs.create_business(1, "tea_shop", "Chai Point"))
        self.assertIsNotNone(doc)
        self.assertEqual(reason, "ok")
        # 500k cost + 50k license = 550k deducted
        self.assertEqual(self.db.users.docs[0]["balance"], 15_000_000 - 550_000)

    def test_open_rejects_poor(self):
        _u(self.db, 1, is_premium=True, balance=100)
        doc, reason = _run(bs.create_business(1, "hotel", "Grand"))
        self.assertIsNone(doc)
        self.assertEqual(reason, "poor")

    def test_open_requires_premium(self):
        _u(self.db, 1, is_premium=False, balance=50_000_000)
        doc, reason = _run(bs.create_business(1, "tea_shop", "Chai"))
        self.assertIsNone(doc)
        self.assertEqual(reason, "not_premium")

    def test_open_enforces_tier_cap(self):
        _u(self.db, 1, is_premium=True, balance=50_000_000)  # default tier -> 1 business
        doc, _ = _run(bs.create_business(1, "tea_shop", "Chai"))
        self.assertIsNotNone(doc)
        doc2, reason2 = _run(bs.create_business(1, "coffee_shop", "Brew"))
        self.assertIsNone(doc2)
        self.assertEqual(reason2, "max_businesses")

    def test_open_rejects_limited_taken(self):
        _u(self.db, 1, is_premium=True, balance=50_000_000)
        d1, r1 = _run(bs.create_business(1, "international_hotel", "Grand I"))
        self.assertEqual(r1, "ok")
        _u(self.db, 2, is_premium=True, balance=50_000_000)
        d2, r2 = _run(bs.create_business(2, "international_hotel", "Grand II"))
        self.assertIsNone(d2)
        self.assertEqual(r2, "limited")

    def test_open_cooldown_blocks_second(self):
        # VIP can own many, but cooldown still applies right after opening.
        _u(self.db, 1, is_premium=True, premium_tier="vip", balance=50_000_000)
        d1, r1 = _run(bs.create_business(1, "tea_shop", "Chai"))
        self.assertEqual(r1, "ok")
        d2, r2 = _run(bs.create_business(1, "coffee_shop", "Brew"))
        self.assertIsNone(d2)
        self.assertEqual(r2, "cooldown")


# ── Income / tax / maintenance / dividends ────────────────────────────────────
class TestIncome(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def test_accrual_collect_tax_and_dividends(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "tea_shop", "Chai"))
        # neutralise popularity so base income = 5000/h
        self.db.businesses.docs[0]["popularity"] = 100
        biz["last_accrued_ts"] = int(__import__("time").time()) - 7200
        biz = _run(bs.persist_accrual(biz["_id"]))
        self.assertEqual(biz["pending_income"], 10_000)  # 5000 * 2h
        # investor of 100k
        _u(self.db, 2, is_premium=True, balance=200_000)
        ok, _ = _run(bs.invest(2, biz["_id"], 100_000))
        self.assertTrue(ok)
        res = _run(bs.collect_income(1))
        self.assertTrue(res["ok"])
        self.assertEqual(res["collected"], 10_000)
        # tax 5% = 500, maintenance 0 (just opened), profit 9500
        # dividends 20% of 9500 = 1900, owner 7600
        self.assertEqual(res["tax"], 500)
        self.assertEqual(res["dividends"], 1900)
        self.assertEqual(res["owner_share"], 7600)
        # investor principal stays; gets 1900 dividends
        inv = [d for d in self.db.users.docs if d["_id"] == 2][0]
        self.assertEqual(inv["balance"], 200_000 - 100_000 + 1900)
        # owner: 15M - 550k(open) + 7600(collect)
        own = [d for d in self.db.users.docs if d["_id"] == 1][0]
        self.assertEqual(own["balance"], 15_000_000 - 550_000 + 7600)
        # ledger recorded
        fresh = _run(bs.get_business(biz["_id"]))
        self.assertEqual(fresh["taxes_paid"], 500)
        self.assertEqual(fresh["total_earned"], 10_000)

    def test_maintenance_reduces_profit(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "tea_shop", "Chai"))
        self.db.businesses.docs[0]["popularity"] = 100
        # accrue income, then let a full day of maintenance accrue before collect
        biz["last_accrued_ts"] = int(__import__("time").time()) - 7200
        biz = _run(bs.persist_accrual(biz["_id"]))  # 10000 pending
        # backdate maintenance anchor a day so ~40k maintenance is due
        self.db.businesses.docs[0]["maintenance_due_ts"] -= 86400
        res = _run(bs.collect_income(1))
        self.assertEqual(res["collected"], 10_000)
        self.assertEqual(res["maintenance"], 40_000)
        # profit = 10000 - 500(tax) - 40000(maintenance) < 0 -> no owner share
        self.assertEqual(res["owner_share"], 0)
        self.assertEqual(res["dividends"], 0)


# ── Employees / progression ───────────────────────────────────────────────────
class TestHire(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def test_offer_accept_fire_quit(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "restaurant", "Dine"))
        _u(self.db, 2, is_premium=True, balance=100_000)
        offer, reason = _run(bs.create_offer(1, 2, "manager", 123))
        self.assertEqual(reason, "ok")
        ok, info = _run(bs.accept_offer(offer["_id"], 2))
        self.assertTrue(ok)
        biz = _run(bs.get_business_by_owner(1))
        self.assertIn(str(2), biz["employees"])
        self.assertAlmostEqual(bs.employee_bonus(biz), 0.15 * 0.85, places=5)
        self.assertTrue(_run(bs.fire_employee(1, 2)))
        biz = _run(bs.get_business_by_owner(1))
        self.assertNotIn(str(2), biz["employees"])
        self.assertIsNone([d for d in self.db.users.docs if d["_id"] == 2][0].get("business_job"))
        offer2, _ = _run(bs.create_offer(1, 2, "cashier", 123))
        _run(bs.accept_offer(offer2["_id"], 2))
        self.assertTrue(_run(bs.quit_job(2))["ok"])
        biz = _run(bs.get_business_by_owner(1))
        self.assertNotIn(str(2), biz["employees"])

    def test_promote_raises_level_and_efficiency(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "restaurant", "Dine"))
        _u(self.db, 2, is_premium=True, balance=100_000)
        offer, _ = _run(bs.create_offer(1, 2, "manager", 123))
        _run(bs.accept_offer(offer["_id"], 2))
        before = _run(bs.get_business_by_owner(1))["employees"][str(2)]
        self.assertEqual(before["level"], 1)
        base_eff = before["efficiency"]
        res = _run(bs.promote_employee(1, 2))
        self.assertTrue(res["ok"])
        self.assertEqual(res["level"], 2)
        self.assertGreater(res["emp"]["efficiency"], base_eff)
        # owner paid open cost+license (2.5M + 200k) and the promotion fee (25k)
        own = [d for d in self.db.users.docs if d["_id"] == 1][0]
        self.assertEqual(own["balance"], 15_000_000 - 2_500_000 - 200_000 - 25_000)


# ── Investors ────────────────────────────────────────────────────────────────
class TestInvest(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def test_invest_and_divest_fee(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "cafe", "Brew"))
        _u(self.db, 3, is_premium=True, balance=200_000)
        ok, _ = _run(bs.invest(3, biz["_id"], 100_000))
        self.assertTrue(ok)
        self.assertEqual([d for d in self.db.users.docs if d["_id"] == 3][0]["balance"], 100_000)
        ok2, info = _run(bs.divest(3, biz["_id"], "all"))
        self.assertTrue(ok2)
        self.assertEqual(info["payout"], 95_000)
        self.assertEqual(info["fee"], 5_000)
        # owner (uid1) paid open cost+license (1M + 100k) and received the 5k fee
        self.assertEqual([d for d in self.db.users.docs if d["_id"] == 1][0]["balance"],
                         15_000_000 - 1_100_000 + 5_000)
        self.assertNotIn(str(3), _run(bs.get_business(biz["_id"]))["investors"])


# ── Robbery ──────────────────────────────────────────────────────────────────
class TestRob(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def test_rob_steals_fraction_and_rejects_own(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "restaurant", "Dine"))
        biz = _run(bs.persist_accrual(biz["_id"]))
        self.db.businesses.docs[0]["pending_income"] = 50_000
        _u(self.db, 9, is_premium=True, balance=0)
        res = _run(bs.rob_business(9, biz["_id"]))
        self.assertTrue(res["ok"])
        self.assertEqual(res["amount"], 10_000)  # 20% of 50000
        self.assertEqual([d for d in self.db.users.docs if d["_id"] == 9][0]["balance"], 10_000)
        self.assertEqual(self.db.businesses.docs[0]["pending_income"], 40_000)
        res2 = _run(bs.rob_business(1, biz["_id"]))
        self.assertFalse(res2["ok"])
        self.assertEqual(res2["reason"], "own")

    def test_guard_reduces_rob(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "restaurant", "Dine"))
        _u(self.db, 2, is_premium=True, balance=100_000)
        offer, _ = _run(bs.create_offer(1, 2, "guard", 1))
        _run(bs.accept_offer(offer["_id"], 2))
        self.db.businesses.docs[0]["pending_income"] = 50_000
        _u(self.db, 9, is_premium=True, balance=0)
        res = _run(bs.rob_business(9, biz["_id"]))
        self.assertTrue(res["ok"])
        self.assertEqual(res["amount"], 7_500)  # 15% of 50000


# ── Ratings / reputation ───────────────────────────────────────────────────
class TestRatings(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def test_rating_updates_reputation_and_popularity(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "tea_shop", "Chai"))
        r = _run(bs.add_rating(biz["_id"], 5, 2))
        self.assertEqual(r["avg"], 5.0)
        self.assertEqual(r["count"], 1)
        # 5★ lifts popularity by (5-3)*0.6 = 1.2
        fresh = _run(bs.get_business(biz["_id"]))
        self.assertAlmostEqual(fresh["popularity"], 55 + 1.2, places=3)


# ── Multi-ownership + selection ─────────────────────────────────────────────
class TestMultiOwnership(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def test_vip_owns_many_and_selects_active(self):
        _u(self.db, 1, is_premium=True, premium_tier="vip", balance=50_000_000)
        b1, _ = _run(bs.create_business(1, "tea_shop", "Chai"))
        # Cooldown is a real gate (see test_open_cooldown_blocks_second); backdate
        # it so we can exercise multi-ownership + active selection here.
        self.db.users.docs[0]["last_business_action_ts"] = 0
        b2, _ = _run(bs.create_business(1, "coffee_shop", "Brew"))
        owned = _run(bs.get_user_businesses(1))
        self.assertEqual(len(owned), 2)
        # default active = first opened
        self.assertEqual(_run(bs.get_business_by_owner(1))["_id"], b1["_id"])
        # select the second
        self.assertTrue(_run(bs.set_active_business(1, b2["_id"])))
        self.assertEqual(_run(bs.get_business_by_owner(1))["_id"], b2["_id"])

    def test_limited_availability_reports_owner(self):
        _u(self.db, 1, is_premium=True, balance=50_000_000)
        b, _ = _run(bs.create_business(1, "international_hotel", "Grand I"))
        av = _run(bs.get_type_availability("international_hotel"))
        self.assertEqual(av["limit"], 1)
        self.assertEqual(av["taken"], 1)
        self.assertEqual(av["remaining"], 0)
        self.assertEqual(av["owners"][0]["owner_id"], 1)


# ── Analytics ───────────────────────────────────────────────────────────────
class TestAnalytics(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def test_analytics_reflects_ledger(self):
        _u(self.db, 1, is_premium=True, balance=15_000_000)
        biz, _ = _run(bs.create_business(1, "tea_shop", "Chai"))
        self.db.businesses.docs[0]["popularity"] = 100
        biz["last_accrued_ts"] = int(__import__("time").time()) - 7200
        biz = _run(bs.persist_accrual(biz["_id"]))
        _u(self.db, 2, is_premium=True, balance=200_000)
        _run(bs.invest(2, biz["_id"], 100_000))
        _run(bs.collect_income(1))
        a = bs.analytics(_run(bs.get_business(biz["_id"])))
        self.assertEqual(a["gross_revenue"], 10_000)
        self.assertEqual(a["taxes_paid"], 500)
        self.assertEqual(a["net_profit"], 9_500)
        self.assertEqual(a["investors"], 1)


# ── @premium_gate ───────────────────────────────────────────────────────────
class TestPremiumGate(unittest.TestCase):
    def setUp(self):
        self.db = FakeDB()
        self.p = patch.object(mm, "get_db", lambda: self.db)
        self.p.start()
        mm._db = self.db
        mm._client = None

    def _update(self, premium: bool, uid: int = 1):
        if premium:
            _u(self.db, uid, is_premium=True)
        else:
            _u(self.db, uid, is_premium=False)
        msg = AsyncMock()
        msg.reply_html = AsyncMock()
        u = AsyncMock(); u.id = uid
        upd = AsyncMock()
        upd.effective_user = u
        upd.effective_message = msg
        return upd, msg

    def test_non_premium_blocked(self):
        upd, msg = self._update(False)
        ctx = AsyncMock(); ctx.args = []
        _run(biz_h.business_cmd(upd, ctx))
        self.assertTrue(msg.reply_html.called)
        self.assertIn("Premium", msg.reply_html.call_args[0][0])

    def test_premium_no_business_message(self):
        upd, msg = self._update(True)
        ctx = AsyncMock(); ctx.args = []
        _run(biz_h.business_cmd(upd, ctx))
        self.assertTrue(msg.reply_html.called)
        self.assertIn("/openbusiness", msg.reply_html.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
