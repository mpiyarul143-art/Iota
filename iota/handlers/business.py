"""
Iota Bot — Business Empire (Enterprise Edition handler module)

A PREMIUM-only "business tycoon / ERP" system, modelled after real-world
business: a premium user opens ONE OR SEVERAL businesses (up to their ownership
tier) across many categories, each with its own cost, income, maintenance,
popularity, customer capacity, tax, license fee and (optionally) a global limit.

The business earns passive income into its till (capped), so the owner must
/bizcollect regularly. Income scales with LEVEL, hired employees (role bonuses +
their skill/level efficiency), pooled investor capital, POPULARITY, REPUTATION
(customer ratings) and whether the minimum staffing requirement is met.
MAINTENANCE and TAXES are deducted on collection, so profit is real.

Every command is gated by @premium_gate (Premium-only) stacked above
@economy_gate, and all coins move through utils/business_store / utils/mongo_db
atomically, so the economy can never desync. Job offers use a pending
`business_offers` collection + callback buttons (decoded via the callback_codec
guard, so the 64-byte limit is never hit).
"""
import asyncio
import functools
import time

from telegram import Update
from telegram.ext import ContextTypes
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from bson import ObjectId

from utils.mongo_db import (
    ensure_user, get_user, get_user_by_username,
)
from utils.business_store import (
    create_business, get_business, get_business_by_owner, get_user_businesses,
    set_active_business, count_user_businesses, list_businesses, rename_business,
    upgrade_business, close_business, persist_accrual, collect_income,
    create_offer, get_offer, accept_offer, decline_offer, fire_employee,
    quit_job, invest, divest, list_investments, rob_business, accrue_all,
    pay_due_salaries, snapshot, analytics, type_meta, max_businesses_for,
    get_type_availability, promote_employee, demote_employee, bonus_employee,
    penalty_employee, add_rating,
)
from utils.helpers import mention, fmt
from utils.fonts import sc
from utils.safe_html import safe_html
from utils.system_gate import economy_gate
from config import (
    BUSINESS_TYPES, BUSINESS_ROLES, BUSINESS_CATEGORIES, BUSINESS_MAX_LEVEL,
    BUSINESS_INVEST_MIN, BUSINESS_INVESTOR_PROFIT_SHARE, BUSINESS_INVEST_BONUS_MAX,
    BUSINESS_ROB_COOLDOWN, BUSINESS_SELL_REFUND, BUSINESS_INVESTOR_MILESTONE,
    BUSINESS_OWNERSHIP_TIERS, BUSINESS_OPEN_COOLDOWN, BUSINESS_MIN_OPEN_COINS,
    BUSINESS_PROMOTE_COST,
)

logger = __import__("logging").getLogger(__name__)


# ── Premium gate (mirrors handlers/banking.py) ──────────────────────────────
def premium_gate(func):
    @functools.wraps(func)
    async def wrapper(update, context, *a, **kw):
        u = update.effective_user
        if not u:
            return
        await ensure_user(u.id, u.username or "", u.full_name)
        d = await get_user(u.id)
        if not d.get("is_premium"):
            try:
                await update.effective_message.reply_html(
                    "🏢 <b>Iota Business Empire is Premium-only!</b>\n\n"
                    "Buy Premium to open a business, hire staff, take investors "
                    "and earn passive income:\n/pay or /fpay"
                )
            except Exception:
                pass
            return
        return await func(update, context, *a, **kw)
    return wrapper


# ── Target resolution (mirrors banking.py bank resolver) ────────────────────
async def _resolve_biz(arg: str):
    arg = (arg or "").strip()
    if not arg:
        return None
    if arg.startswith("@"):
        u = await get_user_by_username(arg.lstrip("@"))
        if not u:
            return None
        return await get_business_by_owner(u["_id"])
    try:
        oid = ObjectId(arg)
        return await get_business(oid)
    except Exception:
        pass
    try:
        uid = int(arg)
        return await get_business_by_owner(uid)
    except (TypeError, ValueError):
        return None


async def _resolve_target(update, context):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user
    if context.args:
        t = context.args[0].lstrip("@")
        if t.isdigit():
            return type("T", (), {"id": int(t), "full_name": f"User {t}"})()
        u = await get_user_by_username(t)
        if u:
            return type("T", (), {"id": u["_id"], "full_name": u.get("full_name", f"User {u['_id']}")})()
    return None


def _parse_amount(raw: str, available: int):
    if not raw:
        return None
    raw = str(raw).lower().strip()
    if raw in ("all", "max"):
        return available
    try:
        amt = int(raw)
    except ValueError:
        return None
    return amt if amt > 0 else None


def _stars(n: float) -> str:
    n = max(0, min(5, round(n, 1)))
    full = int(n)
    half = 1 if (n - full) >= 0.5 else 0
    return "⭐" * full + ("✨" * half) + "▫️" * (5 - full - half)


def _types_text() -> str:
    lines = []
    for key, t in BUSINESS_TYPES.items():
        lim = t.get("global_limit", 0)
        lim_s = f" · {sc('limit')} {lim}" if lim else ""
        lines.append(
            f"{t['emoji']} {t['name']} <code>{key}</code> — "
            f"{sc('open')} {fmt(t['cost']+t.get('license_fee',0))} "
            f"({sc('license')} {fmt(t.get('license_fee',0))}) | "
            f"{fmt(t['income_per_hour'])}/{sc('h')} | "
            f"{sc('maint')} {fmt(t.get('maintenance_per_day',0))}/{sc('day')} "
            f"| {sc('tax')} {int(t.get('tax_rate',0)*100)}%{lim_s}"
        )
    return "\n".join(lines)


def _roles_text() -> str:
    lines = []
    for key, r in BUSINESS_ROLES.items():
        lines.append(
            f"{r['emoji']} {r['name']} <code>{key}</code> — "
            f"{sc('income')} +{int(r['income_bonus']*100)}% · "
            f"{sc('skill')} {int(r.get('skill',0.6)*100)}% · "
            f"{sc('salary')} {fmt(r['daily_salary'])}/{sc('day')}"
        )
    return "\n".join(lines)


def _mention_id(uid) -> str:
    try:
        return f'<a href="tg://user?id={int(uid)}">User {int(uid)}</a>'
    except (TypeError, ValueError):
        return safe_html(str(uid))


# ═══════════════════════════════════════════════════════════════════════════
# /business — own business overview (supports multiple businesses)
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def business_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    owned = await get_user_businesses(u.id)
    if not owned:
        await msg.reply_html(
            f"🏢 <b>{sc('Business Empire')}</b>\n\n"
            f"{sc('You do not own a business yet.')}\n\n"
            f"{sc('Open one')} (need Premium + the type cost + license fee):\n"
            f"/openbusiness &lt;type&gt; &lt;name&gt;\n\n"
            f"{sc('Browse types')}: /biztypes\n"
            f"{sc('Roles')}: /hire (as owner) • /bizjob • /bizinvest"
        )
        return
    tier_max = max_businesses_for(await get_user(u.id))
    head = (f"🏢 <b>{sc('Business Empire')}</b> — you own "
            f"{len(owned)}/{tier_max} business(es)\n")
    if len(owned) > 1:
        for b in owned:
            tt = type_meta(b["type"])
            head += f"  • {tt.get('emoji','')} {safe_html(b['name'])} ({tt.get('name')}) — {fmt(snapshot(b)['valuation'])}\n"
        head += f"{sc('Switch active')}: /bizselect &lt;biz_id&gt;\n\n"
    biz = await get_business_by_owner(u.id)
    t = type_meta(biz["type"])
    s = snapshot(biz)
    employees = biz.get("employees") or {}
    investors = biz.get("investors") or {}
    text = head + (
        f"{t['emoji']} <b>{safe_html(biz['name'])}</b> ({t['name']}) — {sc('Lv')} {biz['level']}\n"
        f"👑 {sc('Owner')}: {mention(u)}\n\n"
        f"💰 {sc('Till (uncollected)')}: {fmt(s['pending'])} / {fmt(s['cap'])}\n"
        f"📈 {sc('Income')}: {fmt(s['rate'])}/{sc('hour')}\n"
        f"   ↳ {sc('level')} ×{s['level_mult']:.2f} · {sc('staff')} +{int(s['emp_bonus']*100)}% · "
        f"{sc('invest')} +{int(s['invest_bonus']*100)}%\n"
        f"📣 {sc('Popularity')}: {int(s['popularity'])}/100 · "
        f"⭐ {sc('Reputation')}: {_stars(s['rating'])} ({s['rating_count']})\n"
        f"👥 {sc('Customers served')}: {fmt(s['customers'])} · "
        f"💎 {sc('Valuation')}: {fmt(s['valuation'])}\n"
        f"💼 {sc('Lifetime earned')}: {fmt(biz.get('total_earned',0))}\n"
        f"👷 {sc('Staff')}: {len(employees)}/{t['max_employees']} · "
        f"💂 {sc('guards')} {s['guards']}\n"
        f"🤝 {sc('Investors')}: {len(investors)} (peak {biz.get('investor_peak',0)}) · "
        f"{sc('pooled')} {fmt(biz.get('total_invested',0))}\n"
    )
    if len(investors) < BUSINESS_INVESTOR_MILESTONE:
        text += f"🎯 {sc('Investors to 100')}: {BUSINESS_INVESTOR_MILESTONE - len(investors)}\n"
    else:
        text += f"🏆 <b>{sc('100-Investor Milestone achieved!')}</b>\n"
    text += (
        f"\n📥 /bizcollect • ⬆️ /bizupgrade ({fmt(s['upgrade_cost'])})\n"
        f"🧑‍💼 /hire • 🔥 /bizfire • 📊 /bizemployees • 📈 /bizstats\n"
        f"🏷️ /bizrename • 🤝 /bizinvest • 💸 /bizdivest • 🚪 /bizclose"
    )
    await msg.reply_html(text)


# ═══════════════════════════════════════════════════════════════════════════
# /openbusiness <type> <name>
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def openbusiness_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if not context.args or len(context.args) < 2:
        await msg.reply_html(
            f"🏢 {sc('Open a Business')}\n\n"
            f"{sc('Usage')}: /openbusiness &lt;type&gt; &lt;name&gt;\n\n"
            f"{sc('Browse types')}: /biztypes\n\n"
            f"💓 {sc('Requires Premium + the type cost + license fee.')}\n"
            f"🎫 {sc('Max businesses by tier')}: "
            + ", ".join(f"{k}={v}" for k, v in BUSINESS_OWNERSHIP_TIERS.items())
            + f"\n⏳ {sc('Cooldown between opens')}: {BUSINESS_OPEN_COOLDOWN//3600}h"
        )
        return
    btype = context.args[0].lower()
    name = " ".join(context.args[1:]).strip()
    if btype not in BUSINESS_TYPES:
        await msg.reply_html(
            f"❌ {sc('Unknown business type.')}\n\n/biztypes"
        )
        return
    t = BUSINESS_TYPES[btype]
    doc, reason = await create_business(u.id, btype, name)
    if doc is None:
        if reason == "not_premium":
            await msg.reply_html("❌ " + sc("This is a Premium-only feature. /pay"))
        elif reason == "exists":
            await msg.reply_html(f"❌ {sc('You already own a business. /bizclose')}")
        elif reason == "employed":
            await msg.reply_html(f"❌ {sc('You are employed at another business. /bizquit first.')}")
        elif reason == "poor":
            bal = (await get_user(u.id)).get("balance", 0)
            need = t["cost"] + t.get("license_fee", 0)
            await msg.reply_html(
                f"❌ {sc('Need')} {fmt(need)} {sc('to open a')} {t['name']} "
                f"({sc('cost')} {fmt(t['cost'])} + {sc('license')} {fmt(t.get('license_fee',0))}).\n"
                f"{sc('You have')}: {fmt(bal)}"
            )
        elif reason == "max_businesses":
            owned = await count_user_businesses(u.id)
            tier = (await get_user(u.id)).get("premium_tier", "premium")
            await msg.reply_html(
                f"❌ {sc('Ownership limit reached')} ({owned}/"
                f"{BUSINESS_OWNERSHIP_TIERS.get(tier, BUSINESS_OWNERSHIP_TIERS['premium'])}). "
                f"{sc('Upgrade your Premium tier to own more.')}"
            )
        elif reason == "limited":
            await msg.reply_html(
                f"❌ {sc('All')} {t['name']} {sc('slots are taken')} "
                f"({sc('global limit')} {t.get('global_limit')})."
            )
        elif reason == "cooldown":
            last = (await get_user(u.id)).get("last_business_action_ts", 0) or 0
            left = (BUSINESS_OPEN_COOLDOWN - (time.time() - last)) / 3600
            await msg.reply_html(f"⏳ {sc('Business cooldown')}: {left:.1f}h {sc('left')}.")
        else:
            await msg.reply_html("❌ " + sc("Could not open the business."))
        return
    await set_active_business(u.id, doc["_id"])
    await msg.reply_html(
        f"{t['emoji']}🎉 <b>{sc('Business Opened!')}</b>\n\n"
        f"🏢 {sc('Name')}: {safe_html(doc['name'])} ({t['name']})\n"
        f"💰 {sc('Setup cost')}: {fmt(t['cost'])} + {sc('license')} {fmt(t.get('license_fee',0))}\n"
        f"📈 {sc('Income')}: {fmt(t['income_per_hour'])}/{sc('hour')} (Lv 1)\n"
        f"🛠️ {sc('Maintenance')}: {fmt(t.get('maintenance_per_day',0))}/{sc('day')} · "
        f"📊 {sc('Tax')}: {int(t.get('tax_rate',0)*100)}%\n"
        f"👷 {sc('Max staff')}: {t['max_employees']} · {sc('min')} {t.get('min_employees',0)}\n\n"
        f"{sc('Collect income')} (/bizcollect), {sc('hire staff')} (/hire), "
        f"{sc('take investors')} (/bizinvest).\n"
        f"⚠️ {sc('Your till fills automatically — collect before a rival')} /robbiz {sc('grabs it!')}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizcollect
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizcollect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    res = await collect_income(u.id)
    if not res.get("ok"):
        if res.get("reason") == "none":
            await msg.reply_html("❌ " + sc("You don't own a business. /openbusiness"))
        else:
            await msg.reply_html("⚠️ " + sc("Till is busy, try again in a moment."))
        return
    collected = res.get("collected", 0)
    if collected <= 0:
        await msg.reply_html(f"🪙 {sc('Till is empty — nothing to collect yet.')}")
        return
    text = (
        f"💰 <b>{sc('Income Collected!')}</b>\n\n"
        f"🧾 {sc('Gross collected')}: {fmt(collected)}\n"
        f"🏛️ {sc('Business tax')}: -{fmt(res.get('tax',0))}\n"
        f"🛠️ {sc('Maintenance')}: -{fmt(res.get('maintenance',0))}\n"
        f"📊 {sc('Net profit')}: {fmt(res.get('profit',0))}\n"
    )
    if res.get("dividends", 0) > 0:
        text += f"🤝 {sc('Investor dividends paid')}: {fmt(res['dividends'])}\n"
        text += f"💼 {sc('Your share')}: {fmt(res['owner_share'])}\n"
    else:
        text += f"💼 {sc('Your share')}: {fmt(res['owner_share'])}\n"
    text += f"\n📈 {sc('Next income accrues every hour — /bizcollect again later.')}"
    await msg.reply_html(text)


# ═══════════════════════════════════════════════════════════════════════════
# /bizupgrade
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizupgrade_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    res = await upgrade_business(u.id)
    if not res.get("ok"):
        if res.get("reason") == "none":
            await msg.reply_html("❌ " + sc("You don't own a business."))
        elif res.get("reason") == "maxed":
            await msg.reply_html(f"🏆 {sc('Your business is already at max level')} ({BUSINESS_MAX_LEVEL}).")
        elif res.get("reason") == "poor":
            await msg.reply_html(
                f"❌ {sc('Need')} {fmt(res.get('cost',0))} {sc('to upgrade.')}"
            )
        else:
            await msg.reply_html("❌ " + sc("Could not upgrade."))
        return
    s = snapshot(res["biz"])
    await msg.reply_html(
        f"⬆️🎉 <b>{sc('Business Upgraded!')}</b> → {sc('Level')} {res['level']}\n\n"
        f"💰 {sc('Cost')}: {fmt(res['cost'])}\n"
        f"📈 {sc('Income now')}: {fmt(s['rate'])}/{sc('hour')}\n"
        f"🪙 {sc('Till cap')}: {fmt(s['cap'])}\n"
        f"💎 {sc('Valuation')}: {fmt(s['valuation'])}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizinfo [@owner|biz_id]
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizinfo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if not context.args:
        await msg.reply_html("🏢 " + sc("Usage: /bizinfo <@owner|biz_id>"))
        return
    biz = await _resolve_biz(context.args[0])
    if not biz or not biz.get("active"):
        await msg.reply_html("❌ " + sc("Business not found."))
        return
    t = type_meta(biz["type"])
    s = snapshot(biz)
    owner = await get_user(biz["owner_id"])
    employees = biz.get("employees") or {}
    investors = biz.get("investors") or {}
    lim = t.get("global_limit", 0)
    text = (
        f"{t['emoji']} <b>{safe_html(biz['name'])}</b> ({t['name']}) — {sc('Lv')} {biz['level']}\n"
        f"👑 {sc('Owner')}: {mention(owner) if owner else '?'}\n\n"
        f"📈 {sc('Income')}: {fmt(s['rate'])}/{sc('hour')}\n"
        f"💰 {sc('Till')}: {fmt(s['pending'])} / {fmt(s['cap'])}\n"
        f"📣 {sc('Popularity')}: {int(s['popularity'])}/100 · "
        f"⭐ {sc('Reputation')}: {_stars(s['rating'])} ({s['rating_count']})\n"
        f"👥 {sc('Customers')}: {fmt(s['customers'])} · 💎 {sc('Valuation')}: {fmt(s['valuation'])}\n"
        f"👷 {sc('Staff')}: {len(employees)}/{t['max_employees']} · 💂 {sc('guards')} {s['guards']}\n"
        f"🤝 {sc('Investors')}: {len(investors)} · {sc('pooled')} {fmt(biz.get('total_invested',0))}\n"
        f"💼 {sc('Lifetime earned')}: {fmt(biz.get('total_earned',0))}"
    )
    if lim:
        av = await get_type_availability(biz["type"])
        text += f"\n🔒 {sc('Global limit')}: {av['taken']}/{lim} {sc('taken')}"
        if biz["owner_id"] == u.id:
            text += f" — {sc('this is yours')} ✅"
    if len(investors) >= BUSINESS_INVESTOR_MILESTONE:
        text += f"\n🏆 {sc('100-Investor Milestone!')}"
    text += f"\n\n🤝 {sc('Invest')}: /bizinvest {biz['_id']} &lt;amt&gt;\n"
    if biz["owner_id"] != u.id:
        text += f"🥷 {sc('Rob the till')}: /robbiz {biz['_id']}\n"
        text += f"⭐ {sc('Rate it')}: /bizrate {biz['_id']} &lt;1-5&gt;"
    await msg.reply_html(text)


# ═══════════════════════════════════════════════════════════════════════════
# /businesses — leaderboard (by valuation)
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def businesses_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    rows = await list_businesses(10)
    if not rows:
        await msg.reply_html(f"🏢 {sc('No businesses open yet. Be the first!')} /openbusiness")
        return
    rows.sort(key=lambda b: snapshot(b)["valuation"], reverse=True)
    lines = [f"🏢 <b>{sc('Iota Business Empire — Top by Valuation')}</b>\n"]
    for i, b in enumerate(rows, 1):
        t = type_meta(b["type"])
        owner = await get_user(b["owner_id"])
        s = snapshot(b)
        oname = mention(owner) if owner else _mention_id(b["owner_id"])
        lines.append(
            f"{i}. {t['emoji']} {safe_html(b['name'])} — {oname}\n"
            f"   {sc('Lv')} {b['level']} · 💎 {fmt(s['valuation'])} · "
            f"📈 {fmt(s['rate'])}/h · 👷 {len(b.get('employees') or {})} · 🤝 {len(b.get('investors') or {})}"
        )
    lines.append(f"\n🏢 {sc('Open yours')}: /openbusiness")
    await msg.reply_html("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# /hire <reply|@user> <role>
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def hire_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    biz = await get_business_by_owner(u.id)
    if not biz:
        await msg.reply_html("❌ " + sc("You don't own a business. /openbusiness"))
        return
    if len(context.args) < 2:
        await msg.reply_html(
            f"🧑‍💼 {sc('Hire staff')}\n\n"
            f"{sc('Usage')}: /hire &lt;reply|@user&gt; &lt;role&gt;\n\n"
            f"{sc('Roles')}:\n{_roles_text()}"
        )
        return
    role = None
    target_token = None
    for a in context.args:
        al = a.lower()
        if al in BUSINESS_ROLES and role is None:
            role = al
        else:
            target_token = a
    if role is None:
        await msg.reply_html(f"❌ {sc('Unknown role.')}\n\n{_roles_text()}")
        return
    if target_token is None:
        await msg.reply_html("❌ " + sc("Reply to a user or use @username."))
        return
    fake_ctx = type("C", (), {"args": [target_token.lstrip("@")]})()
    target = await _resolve_target(update, fake_ctx)
    if not target or target.id == u.id:
        await msg.reply_html("❌ " + sc("Reply to a user or use @username to hire."))
        return
    offer, reason = await create_offer(u.id, target.id, role, msg.chat_id)
    if offer is None:
        if reason == "full":
            await msg.reply_html(
                f"❌ {sc('Your business is full')} ({BUSINESS_TYPES[biz['type']]['max_employees']} staff)."
            )
        elif reason == "already_here":
            await msg.reply_html("❌ " + sc("That user already works for you."))
        elif reason == "employed_elsewhere":
            await msg.reply_html("❌ " + sc("That user already has a job."))
        elif reason == "owns_business":
            await msg.reply_html("❌ " + sc("That user owns a business (can't be hired)."))
        else:
            await msg.reply_html("❌ " + sc("Could not send the offer."))
        return
    r = BUSINESS_ROLES[role]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(sc("✅ Accept"), callback_data=f"bizacc:{offer['_id']}"),
         InlineKeyboardButton(sc("❌ Decline"), callback_data=f"bizdec:{offer['_id']}")],
    ])
    try:
        await context.bot.send_message(
            chat_id=target.id,
            text=(
                f"🧑‍💼 <b>{sc('Job Offer!')}</b>\n\n"
                f"{mention(u)} {sc('offers you a job at')} {safe_html(biz['name'])} "
                f"({type_meta(biz['type'])['name']})!\n\n"
                f"{r['emoji']} {sc('Role')}: {r['name']}\n"
                f"💰 {sc('Salary')}: {fmt(r['daily_salary'])}/{sc('day')}\n"
                f"📈 {sc('Income bonus')}: +{int(r['income_bonus']*100)}% · "
                f"{sc('Skill')}: {int(r.get('skill',0.6)*100)}%\n\n"
                f"{sc('Accept to start earning.')}"
            ),
            parse_mode="HTML", reply_markup=kb,
        )
    except Exception:
        await msg.reply_html(
            f"⚠️ {sc('Could not DM the offer (user may have blocked the bot).')} "
            f"{sc('They can still accept via')} /bizjob."
        )
        return
    await msg.reply_html(
        f"📨 {sc('Job offer sent to')} {mention(target)}:\n"
        f"{r['emoji']} {r['name']} — {fmt(r['daily_salary'])}/{sc('day')}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizfire <@user|reply>
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizfire_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    biz = await get_business_by_owner(u.id)
    if not biz:
        await msg.reply_html("❌ " + sc("You don't own a business."))
        return
    if not context.args and not msg.reply_to_message:
        await msg.reply_html("🔥 " + sc("Usage: /bizfire <@user|reply>"))
        return
    target = await _resolve_target(update, context)
    if not target:
        await msg.reply_html("❌ " + sc("Reply to a user or use @username."))
        return
    if str(target.id) not in (biz.get("employees") or {}):
        await msg.reply_html("❌ " + sc("That user does not work for you."))
        return
    if await fire_employee(u.id, target.id):
        await msg.reply_html(f"🔥 {sc('Fired')} {mention(target)} {sc('from')} {safe_html(biz['name'])}.")
    else:
        await msg.reply_html("❌ " + sc("Could not fire that employee."))


# ═══════════════════════════════════════════════════════════════════════════
# /bizjob — view / accept your employment
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizjob_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    job = await get_user_job(u.id)
    if not job:
        await msg.reply_html(
            f"🧑‍💼 {sc('You are not employed.')}\n\n"
            f"{sc('Get hired by a business owner (they use')} /hire{sc('), or invest instead')}: /bizinvest"
        )
        return
    biz = job["biz"]
    r = BUSINESS_ROLES.get(job["role"], {})
    emp = job["emp"]
    await msg.reply_html(
        f"{r.get('emoji','')} <b>{sc('Your Job')}</b>\n\n"
        f"🏢 {safe_html(biz['name'])} ({type_meta(biz['type'])['name']})\n"
        f"💼 {sc('Role')}: {r.get('name', job['role'])} · {sc('Lv')} {emp.get('level',1)}\n"
        f"📈 {sc('Efficiency')}: {int(emp.get('efficiency',0)*100)}%\n"
        f"💰 {sc('Salary')}: {fmt(r.get('daily_salary',0))}/{sc('day')}\n"
        f"💵 {sc('Earned so far')}: {fmt(emp.get('earned',0))}\n"
        f"🎁 {sc('Bonuses')}: {fmt(emp.get('bonuses',0))} · ⚠️ {sc('Penalties')}: {emp.get('penalties',0)}\n"
        f"⚠️ {sc('Unpaid days')}: {emp.get('unpaid_days',0)}\n\n"
        f"🚪 {sc('Quit')}: /bizquit"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizquit — leave your job
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizquit_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    res = await quit_job(u.id)
    if not res.get("ok"):
        await msg.reply_html("❌ " + sc("You don't have a job."))
        return
    await msg.reply_html(
        f"🚪 {sc('You quit')} {safe_html(res['biz']['name'])} "
        f"({sc(res['role'])}). {sc('Thanks for the work!')}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizinvest <@owner|biz_id> <amount|all>
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizinvest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if len(context.args) < 2:
        await msg.reply_html(
            f"🤝 {sc('Invest in a business')}\n\n"
            f"{sc('Usage')}: /bizinvest &lt;@owner|biz_id&gt; &lt;amount|all&gt;\n"
            f"{sc('Min')}: {fmt(BUSINESS_INVEST_MIN)} · {sc('Profit share')} "
            f"{int(BUSINESS_INVESTOR_PROFIT_SHARE*100)}% · "
            f"{sc('bonus cap')} +{int(BUSINESS_INVEST_BONUS_MAX*100)}%"
        )
        return
    biz = await _resolve_biz(context.args[0])
    if not biz or not biz.get("active"):
        await msg.reply_html("❌ " + sc("Business not found."))
        return
    d = await get_user(u.id)
    amt = _parse_amount(context.args[1], d.get("balance", 0))
    if amt is None or amt <= 0:
        await msg.reply_html("❌ " + sc("Invalid amount."))
        return
    if amt < BUSINESS_INVEST_MIN:
        await msg.reply_html(f"❌ {sc('Minimum investment')}: {fmt(BUSINESS_INVEST_MIN)}")
        return
    if amt > d.get("balance", 0):
        await msg.reply_html(f"❌ {sc('You only have')} {fmt(d.get('balance',0))}")
        return
    ok, info = await invest(u.id, biz["_id"], amt)
    if not ok:
        if info == "own":
            await msg.reply_html("❌ " + sc("You can't invest in your own business."))
        elif info == "poor":
            await msg.reply_html("❌ " + sc("Insufficient balance."))
        else:
            await msg.reply_html("❌ " + sc("Could not invest."))
        return
    note = ""
    if info.get("count", 0) == BUSINESS_INVESTOR_MILESTONE:
        note = f"\n🏆 {sc('100-Investor Milestone reached!')}"
    await msg.reply_html(
        f"🤝 {sc('Invested')} {fmt(amt)} {sc('into')} {safe_html(biz['name'])}!\n"
        f"📊 {sc('Investors now')}: {info.get('count',0)}\n"
        f"💸 {sc('Collect dividends on every')} /bizcollect {sc('via the owner.')}"
        f"{note}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizdivest <@owner|biz_id> <amount|all>
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizdivest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if len(context.args) < 2:
        await msg.reply_html("💸 " + sc("Usage: /bizdivest <@owner|biz_id> <amount|all>"))
        return
    biz = await _resolve_biz(context.args[0])
    if not biz or not biz.get("active"):
        await msg.reply_html("❌ " + sc("Business not found."))
        return
    ok, info = await divest(u.id, biz["_id"], context.args[1])
    if not ok:
        if info in ("none", "no_biz"):
            await msg.reply_html("❌ " + sc("You have no investment in this business."))
        elif info == "bad_amount":
            await msg.reply_html("❌ " + sc("Invalid amount."))
        else:
            await msg.reply_html("❌ " + sc("Could not divest."))
        return
    await msg.reply_html(
        f"💸 {sc('Pulled')} {fmt(info['payout'])} {sc('out of')} {safe_html(biz['name'])} "
        f"({sc('fee')} {fmt(info['fee'])}).\n"
        f"📊 {sc('Remaining stake')}: {fmt(info.get('remaining',0))}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizinvestments — your stakes
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizinvestments_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    rows = await list_investments(u.id)
    if not rows:
        await msg.reply_html(
            f"🤝 {sc('You have no investments.')}\n\n"
            f"{sc('Invest')}: /bizinvest &lt;@owner|biz_id&gt; &lt;amount&gt;"
        )
        return
    lines = [f"🤝 <b>{sc('Your Investments')}</b>\n"]
    for r in rows:
        biz = r["biz"]
        lines.append(
            f"{type_meta(biz['type'])['emoji']} {safe_html(biz['name'])}\n"
            f"   💰 {sc('stake')} {fmt(r['amount'])} · 💵 {sc('dividends')} {fmt(r['dividends'])}"
        )
    lines.append(f"\n💸 {sc('Pull out')}: /bizdivest &lt;@owner|biz_id&gt; &lt;amt|all&gt;")
    await msg.reply_html("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# /robbiz <@owner|biz_id>
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def robbiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if not context.args:
        await msg.reply_html("🥷 " + sc("Usage: /robbiz <@owner|biz_id>"))
        return
    biz = await _resolve_biz(context.args[0])
    if not biz or not biz.get("active"):
        await msg.reply_html("❌ " + sc("Business not found."))
        return
    if biz["owner_id"] == u.id:
        await msg.reply_html("❌ " + sc("You can't rob your own business."))
        return
    d = await get_user(u.id)
    if d.get("business_job") and d["business_job"].get("biz_id") == str(biz["_id"]):
        await msg.reply_html("❌ " + sc("Employees can't rob their own workplace."))
        return
    last = d.get("last_bizrob", 0) or 0
    if time.time() - last < BUSINESS_ROB_COOLDOWN:
        left = (BUSINESS_ROB_COOLDOWN - (time.time() - last)) / 3600
        await msg.reply_html(f"⏳ {sc('Rob cooldown')}: {left:.1f}h {sc('left')}.")
        return
    res = await rob_business(u.id, biz["_id"])
    if not res.get("ok"):
        if res.get("reason") == "empty":
            await msg.reply_html(
                f"🪙 {sc('The till is nearly empty')} ({fmt(res.get('till',0))}). {sc('Nothing worth robbing.')}"
            )
        elif res.get("reason") == "employee":
            await msg.reply_html("❌ " + sc("You work there — can't rob it."))
        elif res.get("reason") == "busy":
            await msg.reply_html("⚠️ " + sc("Rob failed (busy). Try again."))
        else:
            await msg.reply_html("❌ " + sc("Could not rob that business."))
        return
    await update_user_last_bizrob(u.id)
    guards = res.get("guards", 0)
    guard_txt = f" 💂({guards})" if guards else ""
    await msg.reply_html(
        f"🥷💰 {sc('You robbed')} {fmt(res['amount'])} {sc('from')} "
        f"{safe_html(biz['name'])}'{guard_txt} {sc('till!')}"
    )


async def update_user_last_bizrob(uid: int):
    from utils.mongo_db import get_db
    await get_db().users.update_one({"_id": uid}, {"$set": {"last_bizrob": int(time.time())}})


# ═══════════════════════════════════════════════════════════════════════════
# /bizrename <new name>  and  /bizclose
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizrename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    name = " ".join(context.args).strip()
    if not name:
        await msg.reply_html("🏷️ " + sc("Usage: /bizrename <new name>"))
        return
    if await rename_business(u.id, name):
        await msg.reply_html(f"✅ {sc('Business renamed to')} {safe_html(name)}")
    else:
        await msg.reply_html("❌ " + sc("You don't own a business."))


@premium_gate
@economy_gate
async def bizclose_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    res = await close_business(u.id)
    if not res.get("ok"):
        await msg.reply_html("❌ " + sc("You don't own a business."))
        return
    await msg.reply_html(
        f"🚪 {sc('Business closed.')}\n"
        f"💰 {sc('Till returned')}: {fmt(res.get('till',0))}\n"
        f"🏷️ {sc('Premises refund')}: {fmt(res.get('refund',0))} "
        f"({int(BUSINESS_SELL_REFUND*100)}%)\n"
        f"🤝 {sc('Investors refunded')}: {fmt(res.get('returned',0))}\n"
        f"📦 {sc('Total to you')}: {fmt(res.get('owner_payout',0))}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /biztypes — full catalogue (categories, costs, license, limits)
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def biztypes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    lines = [f"🏢 <b>{sc('Business Catalogue')}</b> ({len(BUSINESS_TYPES)} types)\n"]
    by_cat = {}
    for key, t in BUSINESS_TYPES.items():
        by_cat.setdefault(t.get("category", "other"), []).append((key, t))
    for cat, items in BUSINESS_CATEGORIES.items():
        if cat not in by_cat:
            continue
        lines.append(f"\n{items}")
        for key, t in by_cat[cat]:
            lim = t.get("global_limit", 0)
            if lim:
                av = await get_type_availability(key)
                lim_s = f" 🔒{av['taken']}/{lim}"
            else:
                lim_s = ""
            lines.append(
                f"  {t['emoji']} <code>{key}</code> — {fmt(t['cost']+t.get('license_fee',0))}"
                f" ({sc('inc')} {fmt(t['income_per_hour'])}/h){lim_s}"
            )
    lines.append(f"\n📖 {sc('Open')}: /openbusiness &lt;type&gt; &lt;name&gt;")
    await msg.reply_html("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# /bizstats — analytics dashboard
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizstats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    biz = await _resolve_biz(context.args[0]) if context.args else await get_business_by_owner(u.id)
    if not biz or not biz.get("active"):
        await msg.reply_html("❌ " + sc("Business not found."))
        return
    if biz["owner_id"] != u.id and context.args:
        # viewing someone else's public stats is allowed (read-only)
        pass
    a = analytics(biz)
    t = type_meta(biz["type"])
    text = (
        f"📊 <b>{sc('Business Analytics')}</b> — {safe_html(biz['name'])} ({t['name']})\n\n"
        f"💼 {sc('Gross revenue')}: {fmt(a['gross_revenue'])}\n"
        f"🛠️ {sc('Maintenance')}: -{fmt(a['maintenance_expenses'])}\n"
        f"🏛️ {sc('Taxes paid')}: -{fmt(a['taxes_paid'])}\n"
        f"📈 {sc('Net profit')}: {fmt(a['net_profit'])}\n\n"
        f"📣 {sc('Popularity')}: {int(a['popularity'])}/100\n"
        f"⭐ {sc('Reputation')}: {_stars(a['rating'])} ({a['rating_count']})\n"
        f"👥 {sc('Customers served')}: {fmt(a['customers'])}\n"
        f"👷 {sc('Employees')}: {a['employees']} · 🤝 {sc('Investors')}: {a['investors']}\n"
        f"💎 {sc('Valuation')}: {fmt(a['valuation'])} · 💰 {sc('Till')}: {fmt(a['pending'])}\n"
    )
    await msg.reply_html(text)


# ═══════════════════════════════════════════════════════════════════════════
# /bizemployees — roster with progression
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizemployees_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    biz = await get_business_by_owner(u.id)
    if not biz:
        await msg.reply_html("❌ " + sc("You don't own a business."))
        return
    emps = biz.get("employees") or {}
    if not emps:
        await msg.reply_html(f"👷 {sc('No employees yet. Hire with')} /hire")
        return
    lines = [f"👷 <b>{sc('Employees')}</b> — {safe_html(biz['name'])}\n"]
    for uid_s, emp in emps.items():
        r = BUSINESS_ROLES.get(emp.get("role"), {})
        lines.append(
            f"{r.get('emoji','')} {_mention_id(uid_s)} — {r.get('name', emp.get('role'))} "
            f"{sc('Lv')}{emp.get('level',1)} · 📈{int(emp.get('efficiency',0)*100)}% · "
            f"💵{fmt(emp.get('earned',0))} · 🎁{fmt(emp.get('bonuses',0))}"
        )
    lines.append(
        f"\n⬆️ /bizpromote • ⬇️ /bizdemote • 🎁 /bizbonus • ⚠️ /bizpenalty "
        f"({sc('<@user|reply>')})"
    )
    await msg.reply_html("\n".join(lines))


# ═══════════════════════════════════════════════════════════════════════════
# /bizpromote / /bizdemote / /bizbonus / /bizpenalty
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizpromote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if not context.args and not msg.reply_to_message:
        await msg.reply_html("⬆️ " + sc("Usage: /bizpromote <@user|reply>"))
        return
    target = await _resolve_target(update, context)
    if not target:
        await msg.reply_html("❌ " + sc("Reply to a user or use @username."))
        return
    res = await promote_employee(u.id, target.id)
    if not res.get("ok"):
        if res.get("reason") == "no_emp":
            await msg.reply_html("❌ " + sc("That user doesn't work for you."))
        elif res.get("reason") == "maxed":
            await msg.reply_html("❌ " + sc("Employee is already at max level."))
        elif res.get("reason") == "poor":
            await msg.reply_html(f"❌ {sc('Need')} {fmt(BUSINESS_PROMOTE_COST)} {sc('to promote (fee).')}")
        else:
            await msg.reply_html("❌ " + sc("Could not promote."))
        return
    r = BUSINESS_ROLES.get(res["emp"].get("role"), {})
    await msg.reply_html(
        f"⬆️ {mention(target)} {sc('promoted to')} {r.get('name')} "
        f"{sc('Lv')}{res['level']} — 📈 {int(res['emp'].get('efficiency',0)*100)}%"
    )


@premium_gate
@economy_gate
async def bizdemote_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if not context.args and not msg.reply_to_message:
        await msg.reply_html("⬇️ " + sc("Usage: /bizdemote <@user|reply>"))
        return
    target = await _resolve_target(update, context)
    if not target:
        await msg.reply_html("❌ " + sc("Reply to a user or use @username."))
        return
    res = await demote_employee(u.id, target.id)
    if not res.get("ok"):
        if res.get("reason") == "no_emp":
            await msg.reply_html("❌ " + sc("That user doesn't work for you."))
        elif res.get("reason") == "min":
            await msg.reply_html("❌ " + sc("Employee is already at level 1."))
        else:
            await msg.reply_html("❌ " + sc("Could not demote."))
        return
    await msg.reply_html(
        f"⬇️ {mention(target)} {sc('demoted to')} {sc('Lv')}{res['level']} — "
        f"📈 {int(res['emp'].get('efficiency',0)*100)}%"
    )


@premium_gate
@economy_gate
async def bizbonus_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if (not context.args and not msg.reply_to_message) or len(context.args) < (2 if context.args else 1):
        await msg.reply_html("🎁 " + sc("Usage: /bizbonus <@user|reply> <amount>"))
        return
    target = await _resolve_target(update, context)
    if not target:
        await msg.reply_html("❌ " + sc("Reply to a user or use @username."))
        return
    amt = _parse_amount(context.args[-1], (await get_user(u.id)).get("balance", 0))
    if amt is None or amt < 1000:
        await msg.reply_html(f"❌ {sc('Minimum bonus')}: 1,000")
        return
    res = await bonus_employee(u.id, target.id, amt)
    if not res.get("ok"):
        if res.get("reason") == "no_emp":
            await msg.reply_html("❌ " + sc("That user doesn't work for you."))
        elif res.get("reason") == "poor":
            await msg.reply_html(f"❌ {sc('You only have')} {fmt((await get_user(u.id)).get('balance',0))}")
        else:
            await msg.reply_html("❌ " + sc("Could not bonus."))
        return
    await msg.reply_html(f"🎁 {sc('Gave')} {fmt(amt)} {sc('bonus to')} {mention(target)}.")


@premium_gate
@economy_gate
async def bizpenalty_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if not context.args and not msg.reply_to_message:
        await msg.reply_html("⚠️ " + sc("Usage: /bizpenalty <@user|reply>"))
        return
    target = await _resolve_target(update, context)
    if not target:
        await msg.reply_html("❌ " + sc("Reply to a user or use @username."))
        return
    res = await penalty_employee(u.id, target.id)
    if not res.get("ok"):
        if res.get("reason") == "no_emp":
            await msg.reply_html("❌ " + sc("That user doesn't work for you."))
        else:
            await msg.reply_html("❌ " + sc("Could not penalise."))
        return
    await msg.reply_html(
        f"⚠️ {mention(target)} {sc('penalised')} — 📈 {int(res['emp'].get('efficiency',0)*100)}%"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizrate <@owner|biz_id> <1-5> — leave a customer rating
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizrate_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if len(context.args) < 2:
        await msg.reply_html("⭐ " + sc("Usage: /bizrate <@owner|biz_id> <1-5>"))
        return
    biz = await _resolve_biz(context.args[0])
    if not biz or not biz.get("active"):
        await msg.reply_html("❌ " + sc("Business not found."))
        return
    if biz["owner_id"] == u.id:
        await msg.reply_html("❌ " + sc("You can't rate your own business."))
        return
    if str(u.id) in (biz.get("employees") or {}):
        await msg.reply_html("❌ " + sc("Employees can't rate their workplace."))
        return
    try:
        stars = int(context.args[1])
    except ValueError:
        await msg.reply_html("❌ " + sc("Rating must be 1–5."))
        return
    if stars < 1 or stars > 5:
        await msg.reply_html("❌ " + sc("Rating must be 1–5."))
        return
    res = await add_rating(biz["_id"], stars, u.id)
    if not res:
        await msg.reply_html("❌ " + sc("Could not rate that business."))
        return
    await msg.reply_html(
        f"⭐ {sc('You rated')} {safe_html(biz['name'])} {stars}/5 — "
        f"{sc('new average')} {res['avg']:.2f} ({res['count']} {sc('ratings')})"
    )


# ═══════════════════════════════════════════════════════════════════════════
# /bizselect <biz_id> — switch active business (multi-ownership)
# ═══════════════════════════════════════════════════════════════════════════
@premium_gate
@economy_gate
async def bizselect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if not context.args:
        owned = await get_user_businesses(u.id)
        if not owned:
            await msg.reply_html("❌ " + sc("You don't own a business."))
            return
        lines = [f"🏢 {sc('Your businesses')}:\n"]
        for b in owned:
            tt = type_meta(b["type"])
            lines.append(f"  • <code>{b['_id']}</code> {tt.get('emoji','')} {safe_html(b['name'])}")
        lines.append(f"\n{sc('Switch')}: /bizselect &lt;biz_id&gt;")
        await msg.reply_html("\n".join(lines))
        return
    try:
        oid = ObjectId(context.args[0])
    except Exception:
        await msg.reply_html("❌ " + sc("Invalid business id."))
        return
    if await set_active_business(u.id, oid):
        await msg.reply_html("✅ " + sc("Active business updated."))
    else:
        await msg.reply_html("❌ " + sc("You don't own that business."))


# ═══════════════════════════════════════════════════════════════════════════
# Job-offer callback (Accept / Decline) — mailbox style
# ═══════════════════════════════════════════════════════════════════════════
async def biz_offer_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        data = query.data or ""
        if data.startswith("bizacc:"):
            action, oid = "accept", data[len("bizacc:"):]
        elif data.startswith("bizdec:"):
            action, oid = "decline", data[len("bizdec:"):]
        else:
            return
        user = update.effective_user
        await ensure_user(user.id, user.username or "", user.full_name)
        offer = await get_offer(oid)
        if not offer or offer.get("status") != "pending" or offer.get("target_id") != user.id:
            try:
                await query.edit_message_text("❌ " + sc("This job offer is no longer available."))
            except Exception:
                pass
            return
        if action == "accept":
            ok, info = await accept_offer(oid, user.id)
            if ok:
                r = BUSINESS_ROLES.get(info["role"], {})
                try:
                    await query.edit_message_text(
                        f"✅ {sc('You are now the')} {r.get('name', info['role'])} "
                        f"{r.get('emoji','')} {sc('at')} {safe_html(info['biz']['name'])}!\n"
                        f"💰 {sc('Salary')}: {fmt(r.get('daily_salary',0))}/{sc('day')} — /bizjob",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
                owner = await get_user(offer["owner_id"])
                if owner:
                    try:
                        await context.bot.send_message(
                            chat_id=owner["_id"],
                            text=f"🧑‍💼 {mention(user)} {sc('accepted your job offer at')} "
                                 f"{safe_html(info['biz']['name'])} ({r.get('name', info['role'])}).",
                            parse_mode="HTML",
                        )
                    except Exception:
                        pass
            else:
                why = {
                    "already_here": sc("You already work there."),
                    "full": sc("That business is now full."),
                    "employed_elsewhere": sc("You already have a job."),
                    "owns_business": sc("You own a business (can't be hired)."),
                    "bad_role": sc("Invalid role."),
                    "no_biz": sc("That business closed."),
                }.get(info, sc("Could not accept (try again)."))
                try:
                    await query.edit_message_text("❌ " + why, parse_mode="HTML")
                except Exception:
                    pass
        else:
            await decline_offer(oid, user.id)
            try:
                await query.edit_message_text("🚫 " + sc("You declined the job offer."), parse_mode="HTML")
            except Exception:
                pass
    except Exception as e:
        logger.exception("biz_offer_callback error: %s", e)
        try:
            await query.edit_message_text("⚠️ " + sc("Something went wrong with that offer."))
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# Background maintenance (launched once from bot.py post_init)
# ═══════════════════════════════════════════════════════════════════════════
async def business_maintenance_loop(bot):
    """Runs forever. Every hour it:
      • accrues every active business's till (capped),
      • pays daily employee salaries (auto, from owner wallet; auto-resign
        after too many unpaid days; employees gain XP & level up).
    Mirrors the repo's other background loops (e.g. banking_maintenance_loop)."""
    while True:
        try:
            await asyncio.sleep(3600)
            accrued = await accrue_all()
            salaries = await pay_due_salaries()
            logger.info(
                f"🏢 business maintenance: accrued→{accrued}, "
                f"salary_businesses→{salaries.get('businesses')}, "
                f"paid→{salaries.get('paid')}, "
                f"resigned→{salaries.get('resigned')}, "
                f"leveled→{salaries.get('leveled')}"
            )
        except Exception:
            logger.exception("business_maintenance_loop error")
