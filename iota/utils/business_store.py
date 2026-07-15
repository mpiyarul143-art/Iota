"""
Iota Bot — Business Empire storage layer (atomic DB operations) — Enterprise v2

This is the single source of truth for the PREMIUM Business system
(handlers/business.py). It mirrors utils/banking_store.py: every coin move
goes through Motor with conditional `$inc` / gated `update_one`, so income can
never be created or destroyed except exactly as intended.

A business is one document in the `businesses` collection. The schema is
additive over v1 (every new field is optional / defaulted, so legacy documents
keep working):

    {
      _id, owner_id, type, name, level,
      pending_income,          # uncollected gross coins in the till (robbable)
      last_accrued_ts,         # when pending_income was last brought up to date
      maintenance_due_ts,      # anchor for accrued-upkeep calculation
      total_earned,            # lifetime GROSS income collected by the owner
      employees: { "<uid>": {role, hired_ts, unpaid_days, earned,
                             xp, level, efficiency, mood, bonuses, penalties,
                             last_pay_ts} },
      investors: { "<uid>": {amount, invested_ts, dividends} },
      total_invested, investor_peak,
      next_salary_ts,          # when the next daily salary run is due
      created_at, active,
      popularity,              # 0-100 marketing / footfall
      rating_sum, rating_count,# drives reputation (avg = sum/count, 1..5)
      customers_served,        # cumulative
      revenue, taxes_paid, expenses,   # cumulative ledger
      license_paid,            # one-time registration fee actually paid
      valuation,               # live estimated value (for limited display / sale)
      history: [ {ts, event, detail} ], # ownership / status timeline
    }

Design notes
────────────
• Income accrues over time at a rate derived from the type, level, hired
  employees (role bonus × their skill & level efficiency), pooled investor
  capital, POPULARITY, REPUTATION (avg customer rating) and whether the
  minimum staffing requirement is met — up to a "till cap" so the owner MUST
  /bizcollect regularly (and an idle till can be robbed).
• `_pending_now()` computes the up-to-date till WITHOUT writing (cheap for
  display). `persist_accrual()` writes it (used before collect / rob / by the
  background loop) so the robbable amount is real and reducible.
• On /bizcollect the GROSS till is distributed: business TAX + MAINTENANCE are
  economic sinks, the AFTER-TAX-AFTER-MAINTENANCE profit is split (investors'
  pro-rata dividends, then the owner's share). Net profit is real, never
  duplicated, never created beyond the passive accrual.
• This module never imports telegram — it is pure data, easy to unit-test.
"""
import time

from bson import ObjectId

from utils.mongo_db import get_db, get_user
from config import (
    BUSINESS_TYPES, BUSINESS_ROLES, BUSINESS_EMP_BONUS_CAP,
    BUSINESS_SALARY_UNPAID_MAX, BUSINESS_MAX_LEVEL, BUSINESS_LEVEL_INCOME_STEP,
    BUSINESS_UPGRADE_COST_FACTOR, BUSINESS_SELL_REFUND,
    BUSINESS_INVESTOR_PROFIT_SHARE, BUSINESS_INVEST_PER_BONUS,
    BUSINESS_INVEST_BONUS_MAX, BUSINESS_INVEST_MIN, BUSINESS_DIVEST_FEE,
    BUSINESS_ROB_PCT, BUSINESS_ROB_MAX, BUSINESS_GUARD_PROTECT,
    BUSINESS_ROB_MIN_TILL,
    BUSINESS_OWNERSHIP_TIERS,     BUSINESS_MAX_BUSINESSES_DEFAULT,
    BUSINESS_OPEN_COOLDOWN, BUSINESS_POPULARITY_START, BUSINESS_REPUTATION_FLOOR,
    BUSINESS_STAFFING_FLOOR,
    BUSINESS_EMP_MAX_LEVEL, BUSINESS_EMP_LEVEL_BONUS, BUSINESS_PROMOTE_COST,
    BUSINESS_DEMOTE_PENALTY, BUSINESS_BONUS_MIN, BUSINESS_XP_PER_LEVEL,
    BUSINESS_DEFAULT_RISK,
)

DAY = 86400


# ═══════════════════════════════════════════════════════════════════════════
# Economy maths (pure — safe to unit-test without a DB)
# ═══════════════════════════════════════════════════════════════════════════
def type_meta(btype: str) -> dict:
    return BUSINESS_TYPES.get(btype, {})


def risk_factor(biz: dict) -> float:
    return float(type_meta(biz.get("type")).get("risk_factor", BUSINESS_DEFAULT_RISK))


def max_businesses_for(user: dict) -> int:
    """How many businesses this premium user may own (by tier)."""
    if not user.get("is_premium"):
        return 0
    tier = user.get("premium_tier")
    return int(BUSINESS_OWNERSHIP_TIERS.get(tier, BUSINESS_MAX_BUSINESSES_DEFAULT))


def employee_bonus(biz: dict) -> float:
    """Combined income bonus from all hired employees, each weighted by their
    realised efficiency (skill × level growth), capped."""
    total = 0.0
    for e in (biz.get("employees") or {}).values():
        role = BUSINESS_ROLES.get(e.get("role"))
        if not role:
            continue
        skill = role.get("skill", 0.6)
        lvl = e.get("level", 1)
        eff = e.get("efficiency", skill) * (1 + (lvl - 1) * BUSINESS_EMP_LEVEL_BONUS)
        eff = min(1.0, max(0.0, eff))
        total += role["income_bonus"] * eff
    return min(BUSINESS_EMP_BONUS_CAP, total)


def investor_bonus(biz: dict) -> float:
    """Small income bonus from pooled investor capital (capped)."""
    invested = biz.get("total_invested", 0) or 0
    if invested <= 0 or BUSINESS_INVEST_PER_BONUS <= 0:
        return 0.0
    bonus = (invested / BUSINESS_INVEST_PER_BONUS) * 0.01
    return min(BUSINESS_INVEST_BONUS_MAX, bonus)


def level_multiplier(biz: dict) -> float:
    return 1.0 + (max(1, biz.get("level", 1)) - 1) * BUSINESS_LEVEL_INCOME_STEP


def popularity_factor(biz: dict) -> float:
    p = biz.get("popularity", BUSINESS_POPULARITY_START)
    p = max(0, min(100, p))
    return 0.4 + 0.6 * (p / 100.0)   # 0.40 .. 1.00


def reputation_factor(biz: dict) -> float:
    s = biz.get("rating_sum", 0) or 0
    c = biz.get("rating_count", 0) or 0
    if c <= 0:
        return 1.0
    avg = s / c                      # 1 .. 5
    return max(BUSINESS_REPUTATION_FLOOR, avg / 5.0)


def staffing_factor(biz: dict) -> float:
    """How much of the required head-count the business actually has.
    Returns 1.0 at/above the requirement. Even an under-staffed business still
    operates at a reduced (floored) capacity — the owner + any on-site family
    keep the doors open — so a till can always accrue and be held/robbed."""
    t = type_meta(biz.get("type"))
    if not t:
        return 1.0
    req = t.get("min_employees", 0) or 0
    if req <= 0:
        return 1.0
    have = len(biz.get("employees") or {})
    return min(1.0, max(BUSINESS_STAFFING_FLOOR, have / req))


def income_rate(biz: dict) -> int:
    """Coins earned per hour, right now, at this business's current state."""
    t = type_meta(biz.get("type"))
    if not t:
        return 0
    base = t["income_per_hour"]
    mult = level_multiplier(biz) * (1.0 + employee_bonus(biz) + investor_bonus(biz))
    rate = base * mult * popularity_factor(biz) * reputation_factor(biz) * staffing_factor(biz)
    return int(rate)


def till_cap(biz: dict) -> int:
    """Maximum coins the till can hold before income stops accruing."""
    t = type_meta(biz.get("type"))
    if not t:
        return 0
    return income_rate(biz) * t["store_hours"]


def guard_count(biz: dict) -> int:
    return sum(1 for e in (biz.get("employees") or {}).values()
               if e.get("role") == "guard")


def upgrade_cost(biz: dict) -> int:
    """Cost to go from the current level to the next one."""
    t = type_meta(biz.get("type"))
    if not t:
        return 0
    lvl = max(1, biz.get("level", 1))
    return int(t["cost"] * lvl * BUSINESS_UPGRADE_COST_FACTOR)


def recompute_valuation(biz: dict) -> int:
    """Live estimated business value (used for limited display / sale)."""
    t = type_meta(biz.get("type"))
    if not t:
        return 0
    base = t["cost"] * level_multiplier(biz)
    val = int(base * 0.5 + (biz.get("total_invested", 0) or 0)
              + max(0, biz.get("total_earned", 0) or 0) * 0.2)
    return val


def _pending_now(biz: dict, now: int = None) -> int:
    """Up-to-date till value WITHOUT writing to the DB (display / preview)."""
    now = int(time.time()) if now is None else now
    stored = biz.get("pending_income") or 0
    last = biz.get("last_accrued_ts")
    if last is None:
        last = now
    elapsed = max(0, now - last)
    rate = income_rate(biz)
    grown = stored + int(rate * elapsed / 3600)
    return max(0, min(till_cap(biz), grown))


def snapshot(biz: dict) -> dict:
    """A read-only bundle of the derived numbers a handler needs to display."""
    return {
        "rate": income_rate(biz),
        "cap": till_cap(biz),
        "pending": _pending_now(biz),
        "emp_bonus": employee_bonus(biz),
        "invest_bonus": investor_bonus(biz),
        "level_mult": level_multiplier(biz),
        "guards": guard_count(biz),
        "upgrade_cost": upgrade_cost(biz),
        "popularity": biz.get("popularity", BUSINESS_POPULARITY_START),
        "reputation": reputation_factor(biz),
        "rating": (biz.get("rating_sum", 0) or 0) / max(1, biz.get("rating_count", 0) or 0),
        "rating_count": biz.get("rating_count", 0) or 0,
        "customers": biz.get("customers_served", 0) or 0,
        "valuation": recompute_valuation(biz),
        "revenue": biz.get("revenue", 0) or 0,
        "expenses": biz.get("expenses", 0) or 0,
        "taxes": biz.get("taxes_paid", 0) or 0,
    }


def analytics(biz: dict) -> dict:
    """Richer analytics bundle for the /bizstats dashboard."""
    rev = biz.get("revenue", 0) or 0
    exp = biz.get("expenses", 0) or 0
    tax = biz.get("taxes_paid", 0) or 0
    profit = rev - exp - tax
    s = snapshot(biz)
    return {
        **s,
        "gross_revenue": rev,
        "maintenance_expenses": exp,
        "taxes_paid": tax,
        "net_profit": profit,
        "employees": len(biz.get("employees") or {}),
        "investors": len(biz.get("investors") or {}),
        "total_invested": biz.get("total_invested", 0) or 0,
        "lifetime_earned": biz.get("total_earned", 0) or 0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Fetch helpers
# ═══════════════════════════════════════════════════════════════════════════
async def get_business(biz_id) -> dict:
    try:
        if not isinstance(biz_id, ObjectId):
            biz_id = ObjectId(biz_id)
    except Exception:
        return None
    return await get_db().businesses.find_one({"_id": biz_id})


async def get_user_businesses(owner_id: int) -> list:
    cur = get_db().businesses.find({"owner_id": owner_id, "active": True})
    rows = await cur.to_list(length=None)
    rows.sort(key=lambda b: b.get("created_at", 0))
    return rows


async def get_business_by_owner(owner_id: int) -> dict:
    """The owner's active business. Supports multi-ownership: prefers the
    user's selected `active_business`, else the oldest active business."""
    u = await get_user(owner_id)
    active = u.get("active_business")
    if active:
        b = await get_business(active)
        if b and b.get("active") and b.get("owner_id") == owner_id:
            return b
    bizs = await get_user_businesses(owner_id)
    return bizs[0] if bizs else None


async def set_active_business(owner_id: int, biz_id) -> bool:
    """Select which of the owner's businesses the single-arg commands target."""
    b = await get_business(biz_id)
    if not b or not b.get("active") or b.get("owner_id") != owner_id:
        return False
    await get_db().users.update_one(
        {"_id": owner_id}, {"$set": {"active_business": b["_id"]}}
    )
    return True


async def count_user_businesses(owner_id: int) -> int:
    return await get_db().businesses.count_documents({"owner_id": owner_id, "active": True})


async def count_type_active(btype: str) -> int:
    return await get_db().businesses.count_documents({"type": btype, "active": True})


async def list_businesses(limit: int = 10) -> list:
    cur = get_db().businesses.find({"active": True}).sort("total_earned", -1).limit(limit)
    return await cur.to_list(length=limit)


async def _resolve_owner_biz(owner_id: int, biz_id=None) -> dict:
    if biz_id is not None:
        b = await get_business(biz_id)
        if b and b.get("active") and b.get("owner_id") == owner_id:
            return b
        return None
    return await get_business_by_owner(owner_id)


async def get_user_job(uid: int) -> dict:
    """Return {'biz': <doc>, 'role': str} for a user's current employment, or None."""
    u = await get_user(uid)
    job = u.get("business_job")
    if not job:
        return None
    biz = await get_business(job.get("biz_id"))
    if not biz or not biz.get("active") or str(uid) not in (biz.get("employees") or {}):
        await get_db().users.update_one({"_id": uid}, {"$unset": {"business_job": ""}})
        return None
    return {"biz": biz, "role": job.get("role"),
            "emp": biz["employees"][str(uid)]}


async def get_type_availability(btype: str) -> dict:
    """For globally-limited types: how many are taken / remaining and by whom."""
    t = type_meta(btype)
    limit = t.get("global_limit", 0) if t else 0
    taken = await count_type_active(btype)
    owners = []
    if limit:
        cur = get_db().businesses.find({"type": btype, "active": True})
        async for b in cur:
            owner = await get_user(b["owner_id"])
            owners.append({
                "biz_id": str(b["_id"]),
                "owner_id": b["owner_id"],
                "owner_name": (owner or {}).get("full_name") or (owner or {}).get("username") or f"User {b['owner_id']}",
                "name": b.get("name"),
                "valuation": recompute_valuation(b),
                "level": b.get("level", 1),
            })
    return {
        "type": btype, "limit": limit, "taken": taken,
        "remaining": max(0, limit - taken) if limit else None,
        "owners": owners,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Open / rename / upgrade / close
# ═══════════════════════════════════════════════════════════════════════════
async def create_business(owner_id: int, btype: str, name: str, chat_id: int = None) -> tuple:
    """Open a business. Enforces the stricter unlock rules atomically:
      • owner is premium
      • balance >= cost + license_fee
      • owns fewer than their tier's max businesses
      • the type's global_limit (if any) is not exhausted
      • cooldown since last open/close has elapsed
    Locks the total (cost + license) from the owner's wallet atomically.
    Returns (doc, reason). doc is None on failure; reason is a short code:
      not_premium | bad_type | exists | poor | max_businesses | limited | cooldown
    """
    if btype not in BUSINESS_TYPES:
        return None, "bad_type"
    db = get_db()
    u = await get_user(owner_id)
    if not u.get("is_premium"):
        return None, "not_premium"
    if await get_user_job(owner_id):
        return None, "employed"   # can't own while employed elsewhere
    t = BUSINESS_TYPES[btype]
    limit = t.get("global_limit", 0)
    if limit:
        if await count_type_active(btype) >= limit:
            return None, "limited"
    # tier cap
    owned = await count_user_businesses(owner_id)
    if owned >= max_businesses_for(u):
        return None, "max_businesses"
    # cooldown since last business action
    last_action = u.get("last_business_action_ts", 0) or 0
    if last_action and (int(time.time()) - last_action) < BUSINESS_OPEN_COOLDOWN:
        return None, "cooldown"
    total = t["cost"] + t.get("license_fee", 0)
    res = await db.users.update_one(
        {"_id": owner_id, "balance": {"$gte": total}},
        {"$inc": {"balance": -total},
         "$set": {"last_business_action_ts": int(time.time())}},
    )
    if res.modified_count == 0:
        return None, "poor"
    now = int(time.time())
    doc = {
        "owner_id": owner_id,
        "type": btype,
        "name": (name or t["name"])[:40],
        "level": 1,
        "pending_income": 0,
        "last_accrued_ts": now,
        "maintenance_due_ts": now,
        "total_earned": 0,
        "employees": {},
        "investors": {},
        "total_invested": 0,
        "investor_peak": 0,
        "next_salary_ts": now + DAY,
        "created_at": now,
        "active": True,
        "popularity": t.get("popularity", BUSINESS_POPULARITY_START),
        "rating_sum": 0,
        "rating_count": 0,
        "customers_served": 0,
        "revenue": 0,
        "taxes_paid": 0,
        "expenses": 0,
        "license_paid": t.get("license_fee", 0),
        "valuation": int(t["cost"] * 0.5),
        "history": [{"ts": now, "event": "opened",
                     "detail": f"Registered as {t['name']} (license {t.get('license_fee',0):,})"}],
    }
    r = await db.businesses.insert_one(doc)
    doc["_id"] = r.inserted_id
    return doc, "ok"


async def rename_business(owner_id: int, name: str, biz_id=None) -> bool:
    name = (name or "").strip()[:40]
    if not name:
        return False
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz:
        return False
    now = int(time.time())
    await get_db().businesses.update_one(
        {"_id": biz["_id"]},
        {"$set": {"name": name},
         "$push": {"history": {"ts": now, "event": "renamed", "detail": name}}},
    )
    return True


async def upgrade_business(owner_id: int, biz_id=None) -> dict:
    """Upgrade the owner's business one level. Cost is locked atomically."""
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz:
        return {"ok": False, "reason": "none"}
    if biz.get("level", 1) >= BUSINESS_MAX_LEVEL:
        return {"ok": False, "reason": "maxed"}
    cost = upgrade_cost(biz)
    db = get_db()
    res = await db.users.update_one(
        {"_id": owner_id, "balance": {"$gte": cost}},
        {"$inc": {"balance": -cost}},
    )
    if res.modified_count == 0:
        return {"ok": False, "reason": "poor", "cost": cost}
    await persist_accrual(biz["_id"])
    await db.businesses.update_one(
        {"_id": biz["_id"]},
        {"$inc": {"level": 1},
         "$set": {"valuation": recompute_valuation(biz)}},
    )
    new = await get_business(biz["_id"])
    return {"ok": True, "cost": cost, "level": new["level"], "biz": new}


async def close_business(owner_id: int, biz_id=None) -> dict:
    """Close a business: pay out the uncollected till + a partial refund of the
    original premises cost to the owner, return every investor's principal in
    full, detach employees, reset the open cooldown. Deactivates the document."""
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz:
        return {"ok": False, "reason": "none"}
    db = get_db()
    biz = await persist_accrual(biz["_id"]) or biz
    till = biz.get("pending_income") or 0
    refund = int(BUSINESS_TYPES[biz["type"]]["cost"] * BUSINESS_SELL_REFUND)
    owner_payout = till + refund
    if owner_payout > 0:
        await db.users.update_one({"_id": owner_id}, {"$inc": {"balance": owner_payout}})
    returned = 0
    for uid_s, inv in (biz.get("investors") or {}).items():
        amt = inv.get("amount", 0)
        if amt <= 0:
            continue
        try:
            uid = int(uid_s)
        except (TypeError, ValueError):
            continue
        await db.users.update_one({"_id": uid}, {"$inc": {"balance": amt}})
        returned += amt
    for uid_s in list((biz.get("employees") or {}).keys()):
        try:
            await db.users.update_one({"_id": int(uid_s)}, {"$unset": {"business_job": ""}})
        except (TypeError, ValueError):
            pass
    now = int(time.time())
    await db.businesses.update_one(
        {"_id": biz["_id"]},
        {"$set": {"active": False, "valuation": 0},
         "$push": {"history": {"ts": now, "event": "closed",
                               "detail": f"Premises refund {refund:,}; investors {returned:,}"}}},
    )
    await db.users.update_one({"_id": owner_id}, {"$set": {"last_business_action_ts": now}})
    return {"ok": True, "till": till, "refund": refund,
            "owner_payout": owner_payout, "returned": returned}


# ═══════════════════════════════════════════════════════════════════════════
# Income: accrual & collection
# ═══════════════════════════════════════════════════════════════════════════
async def persist_accrual(biz_id) -> dict:
    """Bring the till up to date in the DB (capped) and stamp last_accrued_ts.
    Returns the fresh business doc (or None)."""
    biz = await get_business(biz_id)
    if not biz or not biz.get("active"):
        return biz
    now = int(time.time())
    new_pending = _pending_now(biz, now)
    await get_db().businesses.update_one(
        {"_id": biz["_id"]},
        {"$set": {"pending_income": new_pending, "last_accrued_ts": now}},
    )
    biz["pending_income"] = new_pending
    biz["last_accrued_ts"] = now
    return biz


async def collect_income(owner_id: int, biz_id=None) -> dict:
    """Collect the till. Distributes the GROSS pending: business TAX + accrued
    MAINTENANCE are economic sinks; the AFTER-TAX-AFTER-MAINTENANCE profit is
    split (investor dividends pro-rata, then owner share). Atomic: the till is
    zeroed (gated) so coins are never duplicated. Returns a summary dict."""
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz:
        return {"ok": False, "reason": "none"}
    db = get_db()
    for _ in range(3):
        biz = await persist_accrual(biz["_id"])
        if not biz:
            return {"ok": False, "reason": "none"}
        pending = biz.get("pending_income") or 0
        if pending <= 0:
            return {"ok": True, "collected": 0, "owner_share": 0,
                    "dividends": 0, "biz": biz}
        t = type_meta(biz["type"])
        tax_rate = t.get("tax_rate", 0.0)
        maint_per_day = t.get("maintenance_per_day", 0)
        now = int(time.time())
        due = biz.get("maintenance_due_ts") or biz.get("last_accrued_ts") or now
        days = max(0.0, (now - due) / 86400.0)
        maintenance = int(maint_per_day * days)
        tax = int(pending * tax_rate)
        profit = pending - tax - maintenance
        dividends = 0
        owner_share = 0
        if profit > 0:
            dividends = int(profit * BUSINESS_INVESTOR_PROFIT_SHARE)
            owner_share = profit - dividends
        res = await db.businesses.update_one(
            {"_id": biz["_id"], "pending_income": pending},
            {"$set": {"pending_income": 0, "last_accrued_ts": now, "maintenance_due_ts": now,
                      "valuation": recompute_valuation(biz)},
             "$inc": {"total_earned": pending, "revenue": pending,
                      "taxes_paid": tax, "expenses": maintenance,
                      "customers_served": max(1, int(pending / 1000))}},
        )
        if res.modified_count == 1:
            break
    else:
        return {"ok": False, "reason": "busy"}

    investors = biz.get("investors") or {}
    total_inv = sum(i.get("amount", 0) for i in investors.values())
    dividends_paid = 0
    if total_inv > 0 and dividends > 0:
        for uid_s, inv in investors.items():
            share = int(dividends * inv.get("amount", 0) / total_inv)
            if share <= 0:
                continue
            try:
                uid = int(uid_s)
            except (TypeError, ValueError):
                continue
            await db.users.update_one({"_id": uid}, {"$inc": {"balance": share}})
            await db.businesses.update_one(
                {"_id": biz["_id"]},
                {"$inc": {f"investors.{uid_s}.dividends": share}},
            )
            dividends_paid += share
    # any rounding remainder goes to the owner (never lost, never duplicated)
    owner_share_actual = owner_share + (dividends - dividends_paid)
    if owner_share_actual > 0:
        await db.users.update_one({"_id": owner_id}, {"$inc": {"balance": owner_share_actual}})
    biz["pending_income"] = 0
    return {"ok": True, "collected": pending, "owner_share": owner_share_actual,
            "dividends": dividends_paid, "tax": tax, "maintenance": maintenance,
            "profit": max(0, profit), "biz": biz}


# ═══════════════════════════════════════════════════════════════════════════
# Employees: offers, hire, fire, quit, progression
# ═══════════════════════════════════════════════════════════════════════════
def _fresh_employee(role: str) -> dict:
    r = BUSINESS_ROLES.get(role, {})
    skill = r.get("skill", 0.6)
    now = int(time.time())
    return {
        "role": role, "hired_ts": now, "unpaid_days": 0, "earned": 0,
        "xp": 0, "level": 1, "efficiency": skill, "mood": 1.0,
        "bonuses": 0, "penalties": 0, "last_pay_ts": now,
    }


def _recompute_efficiency(emp: dict) -> float:
    r = BUSINESS_ROLES.get(emp.get("role"), {})
    skill = r.get("skill", 0.6)
    lvl = emp.get("level", 1)
    eff = skill * (1 + (lvl - 1) * BUSINESS_EMP_LEVEL_BONUS)
    # mood & penalty multipliers (clamped)
    eff *= max(0.2, min(1.0, emp.get("mood", 1.0)))
    return min(1.0, max(0.0, eff))


async def create_offer(owner_id: int, target_id: int, role: str,
                       chat_id: int) -> tuple:
    """Owner offers `target_id` a job. Returns (offer_doc, reason)."""
    if role not in BUSINESS_ROLES:
        return None, "bad_role"
    biz = await get_business_by_owner(owner_id)
    if not biz:
        return None, "no_biz"
    if target_id == owner_id:
        return None, "self"
    if str(target_id) in (biz.get("employees") or {}):
        return None, "already_here"
    max_emp = BUSINESS_TYPES[biz["type"]]["max_employees"]
    if len(biz.get("employees") or {}) >= max_emp:
        return None, "full"
    target = await get_user(target_id)
    if target.get("business_job"):
        return None, "employed_elsewhere"
    if await get_business_by_owner(target_id):
        return None, "owns_business"
    db = get_db()
    await db.business_offers.delete_many(
        {"biz_id": biz["_id"], "target_id": target_id, "status": "pending"}
    )
    doc = {
        "biz_id": biz["_id"], "owner_id": owner_id, "target_id": target_id,
        "role": role, "chat_id": chat_id, "status": "pending",
        "created_at": int(time.time()),
    }
    r = await db.business_offers.insert_one(doc)
    doc["_id"] = r.inserted_id
    return doc, "ok"


async def get_offer(offer_id) -> dict:
    try:
        if not isinstance(offer_id, ObjectId):
            offer_id = ObjectId(offer_id)
    except Exception:
        return None
    return await get_db().business_offers.find_one({"_id": offer_id})


async def accept_offer(offer_id, user_id: int) -> tuple:
    """The target accepts a job offer. Returns (ok, reason/info)."""
    db = get_db()
    offer = await get_offer(offer_id)
    if not offer or offer.get("status") != "pending":
        return False, "gone"
    if offer.get("target_id") != user_id:
        return False, "not_yours"
    biz = await get_business(offer["biz_id"])
    if not biz or not biz.get("active"):
        await db.business_offers.update_one({"_id": offer["_id"]}, {"$set": {"status": "void"}})
        return False, "no_biz"
    role = offer["role"]
    if role not in BUSINESS_ROLES:
        return False, "bad_role"
    if str(user_id) in (biz.get("employees") or {}):
        return False, "already_here"
    if len(biz.get("employees") or {}) >= BUSINESS_TYPES[biz["type"]]["max_employees"]:
        return False, "full"
    u = await get_user(user_id)
    if u.get("business_job"):
        return False, "employed_elsewhere"
    if await get_business_by_owner(user_id):
        return False, "owns_business"
    now = int(time.time())
    emp = _fresh_employee(role)
    await db.businesses.update_one(
        {"_id": biz["_id"]}, {"$set": {f"employees.{user_id}": emp}}
    )
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"business_job": {"biz_id": str(biz["_id"]), "role": role, "since": now}}},
    )
    await db.business_offers.update_one({"_id": offer["_id"]}, {"$set": {"status": "accepted"}})
    return True, {"biz": biz, "role": role}


async def decline_offer(offer_id, user_id: int) -> bool:
    offer = await get_offer(offer_id)
    if not offer or offer.get("status") != "pending" or offer.get("target_id") != user_id:
        return False
    await get_db().business_offers.update_one(
        {"_id": offer["_id"]}, {"$set": {"status": "declined"}}
    )
    return True


async def fire_employee(owner_id: int, target_id: int, biz_id=None) -> bool:
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz or str(target_id) not in (biz.get("employees") or {}):
        return False
    db = get_db()
    await db.businesses.update_one(
        {"_id": biz["_id"]}, {"$unset": {f"employees.{target_id}": ""}}
    )
    await db.users.update_one({"_id": target_id}, {"$unset": {"business_job": ""}})
    return True


async def quit_job(user_id: int) -> dict:
    job = await get_user_job(user_id)
    if not job:
        return {"ok": False}
    biz = job["biz"]
    db = get_db()
    await db.businesses.update_one(
        {"_id": biz["_id"]}, {"$unset": {f"employees.{user_id}": ""}}
    )
    await db.users.update_one({"_id": user_id}, {"$unset": {"business_job": ""}})
    return {"ok": True, "biz": biz, "role": job["role"]}


def _level_up_employee(emp: dict, role: dict) -> bool:
    """Apply accumulated XP; returns True if the employee gained a level."""
    leveled = False
    while (emp.get("level", 1) < BUSINESS_EMP_MAX_LEVEL
           and emp.get("xp", 0) >= emp.get("level", 1) * BUSINESS_XP_PER_LEVEL):
        emp["xp"] -= emp.get("level", 1) * BUSINESS_XP_PER_LEVEL
        emp["level"] = emp.get("level", 1) + 1
        leveled = True
    emp["efficiency"] = _recompute_efficiency(emp)
    return leveled


async def promote_employee(owner_id: int, target_id: int, biz_id=None) -> dict:
    """Promote an employee one level (owner pays BUSINESS_PROMOTE_COST)."""
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz or str(target_id) not in (biz.get("employees") or {}):
        return {"ok": False, "reason": "no_emp"}
    emp = biz["employees"][str(target_id)]
    if emp.get("level", 1) >= BUSINESS_EMP_MAX_LEVEL:
        return {"ok": False, "reason": "maxed"}
    db = get_db()
    res = await db.users.update_one(
        {"_id": owner_id, "balance": {"$gte": BUSINESS_PROMOTE_COST}},
        {"$inc": {"balance": -BUSINESS_PROMOTE_COST}},
    )
    if res.modified_count == 0:
        return {"ok": False, "reason": "poor"}
    emp = dict(emp)
    emp["level"] = emp.get("level", 1) + 1
    emp["efficiency"] = _recompute_efficiency(emp)
    await db.businesses.update_one(
        {"_id": biz["_id"]}, {"$set": {f"employees.{target_id}": emp}}
    )
    return {"ok": True, "level": emp["level"], "emp": emp, "biz": biz}


async def demote_employee(owner_id: int, target_id: int, biz_id=None) -> dict:
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz or str(target_id) not in (biz.get("employees") or {}):
        return {"ok": False, "reason": "no_emp"}
    emp = dict(biz["employees"][str(target_id)])
    if emp.get("level", 1) <= 1:
        return {"ok": False, "reason": "min"}
    emp["level"] -= 1
    emp["mood"] = max(0.2, emp.get("mood", 1.0) * (1 - BUSINESS_DEMOTE_PENALTY))
    emp["efficiency"] = _recompute_efficiency(emp)
    await get_db().businesses.update_one(
        {"_id": biz["_id"]}, {"$set": {f"employees.{target_id}": emp}}
    )
    return {"ok": True, "level": emp["level"], "emp": emp, "biz": biz}


async def bonus_employee(owner_id: int, target_id: int, amount: int, biz_id=None) -> dict:
    """Owner gives a one-off bonus from their wallet to an employee."""
    if amount < BUSINESS_BONUS_MIN:
        return {"ok": False, "reason": "min"}
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz or str(target_id) not in (biz.get("employees") or {}):
        return {"ok": False, "reason": "no_emp"}
    db = get_db()
    res = await db.users.update_one(
        {"_id": owner_id, "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount}},
    )
    if res.modified_count == 0:
        return {"ok": False, "reason": "poor"}
    await db.users.update_one({"_id": target_id}, {"$inc": {"balance": amount}})
    await db.businesses.update_one(
        {"_id": biz["_id"]},
        {"$inc": {f"employees.{target_id}.earned": amount,
                  f"employees.{target_id}.bonuses": amount}},
    )
    return {"ok": True, "amount": amount, "biz": biz}


async def penalty_employee(owner_id: int, target_id: int, biz_id=None) -> dict:
    """Owner penalises an employee: efficiency & mood take a hit."""
    biz = await _resolve_owner_biz(owner_id, biz_id)
    if not biz or str(target_id) not in (biz.get("employees") or {}):
        return {"ok": False, "reason": "no_emp"}
    emp = dict(biz["employees"][str(target_id)])
    emp["mood"] = max(0.2, emp.get("mood", 1.0) * (1 - BUSINESS_DEMOTE_PENALTY))
    emp["penalties"] = emp.get("penalties", 0) + 1
    emp["efficiency"] = _recompute_efficiency(emp)
    await get_db().businesses.update_one(
        {"_id": biz["_id"]}, {"$set": {f"employees.{target_id}": emp}}
    )
    return {"ok": True, "emp": emp, "biz": biz}


# ═══════════════════════════════════════════════════════════════════════════
# Investors
# ═══════════════════════════════════════════════════════════════════════════
async def invest(investor_id: int, biz_id, amount: int) -> tuple:
    """Invest coins into a business. Deducts atomically. Returns (ok, reason)."""
    if amount < BUSINESS_INVEST_MIN:
        return False, "min"
    db = get_db()
    biz = await get_business(biz_id)
    if not biz or not biz.get("active"):
        return False, "no_biz"
    if biz["owner_id"] == investor_id:
        return False, "own"
    res = await db.users.update_one(
        {"_id": investor_id, "balance": {"$gte": amount}},
        {"$inc": {"balance": -amount}},
    )
    if res.modified_count == 0:
        return False, "poor"
    uid_s = str(investor_id)
    now = int(time.time())
    if (biz.get("investors") or {}).get(uid_s):
        await db.businesses.update_one(
            {"_id": biz["_id"]},
            {"$inc": {f"investors.{uid_s}.amount": amount, "total_invested": amount}},
        )
    else:
        await db.businesses.update_one(
            {"_id": biz["_id"]},
            {"$set": {f"investors.{uid_s}": {
                "amount": amount, "invested_ts": now, "dividends": 0}},
             "$inc": {"total_invested": amount}},
        )
    fresh = await get_business(biz["_id"])
    count = len(fresh.get("investors") or {})
    if count > (fresh.get("investor_peak", 0) or 0):
        await db.businesses.update_one(
            {"_id": biz["_id"]}, {"$set": {"investor_peak": count,
                                           "valuation": recompute_valuation(fresh)}}
        )
    else:
        await db.businesses.update_one(
            {"_id": biz["_id"]}, {"$set": {"valuation": recompute_valuation(fresh)}}
        )
    return True, {"biz": fresh, "count": count}


async def divest(investor_id: int, biz_id, amount) -> tuple:
    """Pull investment out (an early-exit fee applies, paid to the owner).
    `amount` may be an int or the string 'all'/'max'. Returns (ok, info)."""
    db = get_db()
    biz = await get_business(biz_id)
    if not biz or not biz.get("active"):
        return False, "no_biz"
    uid_s = str(investor_id)
    inv = (biz.get("investors") or {}).get(uid_s)
    if not inv or inv.get("amount", 0) <= 0:
        return False, "none"
    stake = inv["amount"]
    if isinstance(amount, str) and amount.lower() in ("all", "max"):
        amt = stake
    else:
        try:
            amt = int(amount)
        except (TypeError, ValueError):
            return False, "bad_amount"
    if amt <= 0 or amt > stake:
        return False, "bad_amount"
    fee = int(amt * BUSINESS_DIVEST_FEE)
    payout = amt - fee
    remaining = stake - amt
    if remaining <= 0:
        await db.businesses.update_one(
            {"_id": biz["_id"]},
            {"$unset": {f"investors.{uid_s}": ""}, "$inc": {"total_invested": -amt}},
        )
    else:
        await db.businesses.update_one(
            {"_id": biz["_id"]},
            {"$set": {f"investors.{uid_s}.amount": remaining},
             "$inc": {"total_invested": -amt}},
        )
    await db.users.update_one({"_id": investor_id}, {"$inc": {"balance": payout}})
    if fee > 0:
        await db.users.update_one({"_id": biz["owner_id"]}, {"$inc": {"balance": fee}})
    fresh = await get_business(biz["_id"])
    await db.businesses.update_one(
        {"_id": biz["_id"]}, {"$set": {"valuation": recompute_valuation(fresh)}}
    )
    return True, {"payout": payout, "fee": fee, "remaining": remaining, "biz": fresh}


async def list_investments(investor_id: int) -> list:
    """All active businesses this user has invested in, with their stake."""
    uid_s = str(investor_id)
    out = []
    cur = get_db().businesses.find(
        {"active": True, f"investors.{uid_s}": {"$exists": True}}
    )
    async for biz in cur:
        inv = biz["investors"][uid_s]
        out.append({"biz": biz, "amount": inv.get("amount", 0),
                    "dividends": inv.get("dividends", 0)})
    return out


# ═══════════════════════════════════════════════════════════════════════════
# Ratings / reviews
# ═══════════════════════════════════════════════════════════════════════════
async def add_rating(biz_id, stars: int, reviewer_id: int = None) -> dict:
    """Record a 1–5★ customer rating. Updates reputation + nudges popularity.
    Returns the new {avg, count}."""
    biz = await get_business(biz_id)
    if not biz or not biz.get("active"):
        return None
    stars = max(1, min(5, int(stars)))
    now = int(time.time())
    pop_delta = (stars - 3) * 0.6
    await get_db().businesses.update_one(
        {"_id": biz["_id"]},
        {"$inc": {"rating_sum": stars, "rating_count": 1, "popularity": pop_delta},
         "$push": {"history": {"ts": now, "event": "rating",
                               "detail": f"{stars}★ from user {reviewer_id}"}}},
    )
    fresh = await get_business(biz["_id"])
    pop = max(0, min(100, fresh.get("popularity", BUSINESS_POPULARITY_START)))
    if pop != fresh.get("popularity"):
        await get_db().businesses.update_one({"_id": biz["_id"]}, {"$set": {"popularity": pop}})
        fresh["popularity"] = pop
    return {"avg": (fresh.get("rating_sum", 0) or 0) / max(1, fresh.get("rating_count", 0) or 0),
            "count": fresh.get("rating_count", 0) or 0}


# ═══════════════════════════════════════════════════════════════════════════
# Robbery — steal uncollected income left in the till
# ═══════════════════════════════════════════════════════════════════════════
async def rob_business(robber_id: int, biz_id) -> dict:
    """Steal a slice of the target business's uncollected till. Guards reduce
    the take. Atomic: the till is reduced (gated) before the robber is paid, so
    coins are never duplicated. Returns a summary dict."""
    biz = await persist_accrual(biz_id)
    if not biz or not biz.get("active"):
        return {"ok": False, "reason": "no_biz"}
    if biz["owner_id"] == robber_id:
        return {"ok": False, "reason": "own"}
    if str(robber_id) in (biz.get("employees") or {}):
        return {"ok": False, "reason": "employee"}
    till = biz.get("pending_income") or 0
    if till < BUSINESS_ROB_MIN_TILL:
        return {"ok": False, "reason": "empty", "till": till}
    pct = max(0.02, BUSINESS_ROB_PCT - guard_count(biz) * BUSINESS_GUARD_PROTECT)
    steal = min(int(till * pct), BUSINESS_ROB_MAX)
    if steal <= 0:
        return {"ok": False, "reason": "empty", "till": till}
    db = get_db()
    res = await db.businesses.update_one(
        {"_id": biz["_id"], "pending_income": {"$gte": steal}},
        {"$inc": {"pending_income": -steal}},
    )
    if res.modified_count == 0:
        return {"ok": False, "reason": "busy"}
    await db.users.update_one({"_id": robber_id}, {"$inc": {"balance": steal}})
    return {"ok": True, "amount": steal, "biz": biz,
            "guards": guard_count(biz)}


# ═══════════════════════════════════════════════════════════════════════════
# Background maintenance (called from handlers/business.py loop)
# ═══════════════════════════════════════════════════════════════════════════
async def accrue_all() -> int:
    """Bring every active business's till up to date. Returns count processed."""
    db = get_db()
    processed = 0
    async for biz in db.businesses.find({"active": True}, {"_id": 1}):
        await persist_accrual(biz["_id"])
        processed += 1
    return processed


async def pay_due_salaries() -> dict:
    """Pay daily salaries for every business whose salary run is due. Salary is
    taken from the owner's wallet; if the owner can't pay, the employee's unpaid
    counter rises and they auto-resign after BUSINESS_SALARY_UNPAID_MAX days.
    Employees also gain XP and level up. Returns a summary dict."""
    db = get_db()
    now = int(time.time())
    paid_total = 0
    resigned = 0
    leveled = 0
    businesses = 0
    async for biz in db.businesses.find({"active": True, "next_salary_ts": {"$lte": now}}):
        businesses += 1
        owner_id = biz["owner_id"]
        employees = dict(biz.get("employees") or {})
        for uid_s, emp in list(employees.items()):
            role = BUSINESS_ROLES.get(emp.get("role"))
            if not role:
                continue
            salary = role["daily_salary"]
            res = await db.users.update_one(
                {"_id": owner_id, "balance": {"$gte": salary}},
                {"$inc": {"balance": -salary}},
            )
            if res.modified_count == 1:
                try:
                    uid = int(uid_s)
                except (TypeError, ValueError):
                    continue
                new_emp = dict(emp)
                new_emp["xp"] = new_emp.get("xp", 0) + role.get("xp_per_day", 0)
                if _level_up_employee(new_emp, role):
                    leveled += 1
                await db.users.update_one({"_id": uid}, {"$inc": {"balance": salary}})
                await db.businesses.update_one(
                    {"_id": biz["_id"]},
                    {"$set": {f"employees.{uid_s}": new_emp}},
                )
                paid_total += salary
            else:
                unpaid = emp.get("unpaid_days", 0) + 1
                if unpaid >= BUSINESS_SALARY_UNPAID_MAX:
                    await db.businesses.update_one(
                        {"_id": biz["_id"]}, {"$unset": {f"employees.{uid_s}": ""}}
                    )
                    try:
                        await db.users.update_one(
                            {"_id": int(uid_s)}, {"$unset": {"business_job": ""}}
                        )
                    except (TypeError, ValueError):
                        pass
                    resigned += 1
                else:
                    await db.businesses.update_one(
                        {"_id": biz["_id"]},
                        {"$set": {f"employees.{uid_s}.unpaid_days": unpaid}},
                    )
        await db.businesses.update_one(
            {"_id": biz["_id"]}, {"$set": {"next_salary_ts": now + DAY}}
        )
    return {"businesses": businesses, "paid": paid_total,
            "resigned": resigned, "leveled": leveled}
