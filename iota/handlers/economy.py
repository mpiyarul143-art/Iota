"""Iota Economy — Baka-style fonts, free 1d protect, 600 coin revive, auto daily"""
import random, asyncio, time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.mongo_db import *
from utils.helpers import *
from utils.fonts import sc, bold_sc
from config import *

# ── /daily ────────────────────────────────────────────────────────────────────
async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    d = await get_user(u.id)
    if d.get("is_banned"):
        await update.message.reply_html(f"🚫 {sc('You are banned!')}"); return
    now = ts(); cd = 86400
    if now - d["last_daily"] < cd:
        rem = cd-(now-d["last_daily"]); h,m = divmod(rem//60,60)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("⏰ Remind Me", callback_data=f"remind_daily_{u.id}")
        ]])
        await update.message.reply_html(
            f"⏳ {mention(u)}, {sc('Already Claimed!')}\n"
            f"{sc('Come Back In')} <b>{h}h {m}m</b>",
            reply_markup=kb
        ); return
    reward  = DAILY_PREMIUM if d.get("is_premium") else DAILY_NORMAL
    xp_gain = 100 if d.get("is_premium") else 50
    await update_user(u.id, balance=d["balance"]+reward, last_daily=now,
                      xp=d["xp"]+xp_gain, daily_kills=0, daily_robs=0,
                      last_kill_reset=now, last_rob_reset=now)
    lv = xp_level(d["xp"]+xp_gain)
    await update.message.reply_html(
        f"✅ {mention(u)} {sc('Claimed Daily Reward!')}\n"
        f"💰 +{fmt(reward)}  |  ⚡ +{xp_gain} XP\n"
        f"🎖️ {sc('Level')}: <b>{lv}</b>  |  🏅 {rank_title(lv)}\n"
        f"💼 {sc('Balance')}: <b>{fmt(d['balance']+reward)}</b>"
    )

async def daily_remind_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; u = q.from_user; await q.answer()
    if f"remind_daily_{u.id}" != q.data: return
    d = await get_user(u.id); now = ts()
    rem = 86400-(now-d["last_daily"])
    if rem <= 0:
        await q.answer("Daily is ready! /daily", show_alert=True); return
    asyncio.create_task(_remind_daily(context.bot, u.id, rem))
    await q.answer(f"⏰ Reminder in {rem//3600}h {(rem%3600)//60}m!", show_alert=True)

async def _remind_daily(bot, uid, secs):
    await asyncio.sleep(secs)
    try:
        await bot.send_message(uid,
            f"⏰ {sc('Daily Reward Is Ready!')}\n💰 /daily {sc('To Claim!')}",
            parse_mode="HTML")
    except Exception: pass

# ── AUTO DAILY JOB (background) ───────────────────────────────────────────────
async def auto_daily_job(bot):
    """Every hour, check users whose 24h is up — give them daily automatically."""
    while True:
        try:
            await asyncio.sleep(3600)  # check hourly
            now = ts()
            db = get_db()
            # Find users whose last_daily was 24h+ ago and haven't claimed
            users = await db.users.find(
                {"is_banned": {"$ne": True},
                 "last_daily": {"$lt": now - 86400},
                 "last_daily": {"$gt": 0}},  # exclude new users
            ).to_list(10000)
            for u in users:
                uid = u["_id"]
                reward = DAILY_PREMIUM if u.get("is_premium") else DAILY_NORMAL
                await db.users.update_one({"_id": uid}, {
                    "$inc": {"balance": reward, "xp": 50},
                    "$set": {"last_daily": now, "daily_kills": 0, "daily_robs": 0}
                })
                # Notify user in DM silently
                try:
                    await bot.send_message(
                        uid,
                        f"🎁 {sc('Auto Daily Claimed!')} +{fmt(reward)}\n"
                        f"{sc('Your daily reward was auto-credited!')} 💰",
                        parse_mode="HTML"
                    )
                except Exception:
                    pass
        except Exception:
            pass

# ── /bal ──────────────────────────────────────────────────────────────────────
async def bal_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if msg.reply_to_message and msg.reply_to_message.from_user:
        tu = msg.reply_to_message.from_user
        await ensure_user(tu.id, tu.username or "", tu.full_name)
        d = await get_user(tu.id)
    else:
        await ensure_user(u.id, u.username or "", u.full_name)
        d = await get_user(u.id); tu = u
    rank = await get_user_rank(d["_id"])
    lv   = xp_level(d["xp"]); xp_in_lv = d["xp"] % (lv * XP_PER_LEVEL)
    now  = ts()
    if d["dead_until"] > now:
        rem = d["dead_until"]-now
        status = f"💀 {sc('Dead')} ({rem//3600}h {(rem%3600)//60}m)"
    elif d["protected_until"] > now:
        rem = d["protected_until"]-now
        status = f"🛡️ {sc('Protected')} ({rem//3600}h {(rem%3600)//60}m)"
    else:
        status = f"✅ {sc('Alive')}"
    await msg.reply_html(
        f"👤 {bold_sc('Name')}: {mention(tu)}\n"
        f"💰 {bold_sc('Balance')}: {fmt(d['balance'])}\n"
        f"🏆 {bold_sc('Global Rank')}: #{rank}\n"
        f"🛡️ {bold_sc('Status')}: {status}\n"
        f"⚔️ {bold_sc('Kills')}: {d['kills']}\n"
        f"🟤 {bold_sc(f'Level {lv}')}: {xp_in_lv}/{lv*XP_PER_LEVEL}"
    )

# ── /rob ──────────────────────────────────────────────────────────────────────
async def rob_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; msg = update.effective_message
    await ensure_user(u.id, u.username or "", u.full_name)
    robber = await get_user(u.id); now = ts()
    if robber.get("is_banned"): await msg.reply_html("🚫 Banned!"); return
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(f"⚠️ {sc('Usage')}: /rob <{sc('reply to user')}>"); return
    vu = msg.reply_to_message.from_user
    if vu.id == u.id or vu.is_bot: await msg.reply_html("❌ Invalid!"); return
    if msg.reply_to_message.date:
        age = now - int(msg.reply_to_message.date.timestamp())
        if age > 30*86400:
            await msg.reply_html(f"⏳ {sc('That Message Is Too Old (30+ Days)!')}"); return
    dr_max = DAILY_ROBS_PREMIUM if robber.get("is_premium") else DAILY_ROBS_NORMAL
    if now - robber.get("last_rob_reset",0) > 86400:
        await update_user(u.id, daily_robs=0, last_rob_reset=now); robber["daily_robs"]=0
    if robber.get("daily_robs",0) >= dr_max:
        await msg.reply_html(f"⛔ {sc('Daily Rob Limit Reached!')} ({dr_max}/day)"); return
    await ensure_user(vu.id, vu.username or "", vu.full_name)
    victim = await get_user(vu.id)
    if victim["protected_until"] > now:
        rem = victim["protected_until"]-now
        await msg.reply_html(f"🛡️ {mention(vu)} {sc('Is Protected For')} <b>{rem//3600}h {(rem%3600)//60}m</b>!"); return
    if victim["dead_until"] > now:
        await msg.reply_html(f"💀 {mention(vu)} {sc('Is Already Dead!')}"); return
    max_rob = ROB_MAX_PREMIUM if robber.get("is_premium") else ROB_MAX_NORMAL
    tax     = TAX_PREMIUM     if robber.get("is_premium") else TAX_NORMAL
    rob_amt = min(random.randint(100, max_rob), victim["balance"])
    if rob_amt <= 0:
        await msg.reply_html(
            f"👤 {mention(vu)} {sc('Rᴏʙʙᴇᴅ')} $0 {sc('Fʀᴏᴍ')} {mention(vu)}\n"
            f"💸 {mention(vu)} {sc('Has No Money!')}"
        ); return
    fee = int(rob_amt*tax); net = rob_amt-fee
    xp_gain = max(1, rob_amt//1000*XP_ROB_PER_1K)
    await update_user(vu.id, balance=victim["balance"]-rob_amt)
    await update_user(u.id, balance=robber["balance"]+net, robs=robber["robs"]+1,
                      daily_robs=robber.get("daily_robs",0)+1, xp=robber["xp"]+xp_gain)
    await msg.reply_html(
        f"👤 {mention(u)} {sc('Rᴏʙʙᴇᴅ')} {fmt(rob_amt)} {sc('Fʀᴏᴍ')} {mention(vu)}\n"
        f"💰 {sc('Gᴀɪɴᴇᴅ')} {fmt(net)}, +{xp_gain} {sc('Xᴘ Aꜰᴛᴇʀ')} {int(tax*100)}% {sc('Dᴇᴅᴜᴄᴛɪᴏɴ')}."
    )

# ── /kill ─────────────────────────────────────────────────────────────────────
async def kill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; msg = update.effective_message
    await ensure_user(u.id, u.username or "", u.full_name)
    killer = await get_user(u.id); now = ts()
    if killer.get("is_banned"): await msg.reply_html("🚫 Banned!"); return
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(f"⚠️ {sc('Reply To Someone To Kill Them.')}"); return
    vu = msg.reply_to_message.from_user
    if vu.id == u.id or vu.is_bot: await msg.reply_html("❌ Invalid!"); return
    if msg.reply_to_message.date:
        if now - int(msg.reply_to_message.date.timestamp()) > 30*86400:
            await msg.reply_html(f"⏳ {sc('Message Too Old!')}"); return
    dk_max = DAILY_KILLS_PREMIUM if killer.get("is_premium") else DAILY_KILLS_NORMAL
    if now - killer.get("last_kill_reset",0) > 86400:
        await update_user(u.id, daily_kills=0, last_kill_reset=now); killer["daily_kills"]=0
    if killer.get("daily_kills",0) >= dk_max:
        await msg.reply_html(f"⛔ {sc('Daily Kill Limit!')} ({dk_max}/day)"); return
    await ensure_user(vu.id, vu.username or "", vu.full_name)
    victim = await get_user(vu.id)
    if victim["protected_until"] > now:
        rem = victim["protected_until"]-now
        await msg.reply_html(f"🛡️ {mention(vu)} {sc('Is Protected For')} <b>{rem//3600}h {(rem%3600)//60}m</b>!"); return
    if victim["dead_until"] > now:
        await msg.reply_html(f"💀 {mention(vu)} {sc('Is Already Dead!')}"); return
    rng  = KILL_REWARD_PREMIUM if killer.get("is_premium") else KILL_REWARD_NORMAL
    xrng = XP_KILL_PREMIUM     if killer.get("is_premium") else XP_KILL_NORMAL
    reward  = random.randint(*rng); xp_gain = random.randint(*xrng)
    await update_user(vu.id, dead_until=now+3600)
    await update_user(u.id, balance=killer["balance"]+reward, kills=killer["kills"]+1,
                      daily_kills=killer.get("daily_kills",0)+1, xp=killer["xp"]+xp_gain)
    await msg.reply_html(
        f"💀 <b>{sc('Kill!')}</b>\n⚔️ {mention(u)} {sc('Killed')} {mention(vu)}\n"
        f"💰 {sc('Reward')}: <b>{fmt(reward)}</b>  |  ⚡ +{xp_gain} XP\n"
        f"🕐 {mention(vu)} {sc('Dead For')} <b>1h</b>"
    )

# ── /revive — 600 coins cost ──────────────────────────────────────────────────
async def revive_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user; now = ts()
    await ensure_user(u.id, u.username or "", u.full_name)
    payer = await get_user(u.id)
    if msg.reply_to_message and msg.reply_to_message.from_user:
        tu = msg.reply_to_message.from_user
        await ensure_user(tu.id, tu.username or "", tu.full_name)
        td = await get_user(tu.id)
    else:
        tu = u; td = payer
    if td["dead_until"] <= now:
        await msg.reply_html(f"✅ {mention(tu)} {sc('Is Already Alive.')}"); return
    cost = REVIVE_COST  # 600 coins
    if payer["balance"] < cost:
        await msg.reply_html(
            f"❌ {sc('Need')} {fmt(cost)} {sc('coins to revive!')}\n"
            f"{sc('Your balance')}: {fmt(payer['balance'])}"
        ); return
    await update_user(u.id, balance=payer["balance"]-cost)
    await update_user(tu.id, dead_until=0)
    if tu.id == u.id:
        await msg.reply_html(
            f"❤️ {sc('You Revived Yourself.')} -{fmt(cost)}"
        )
    else:
        await msg.reply_html(
            f"💚 {mention(u)} {sc('Revived')} {mention(tu)}! -{fmt(cost)}"
        )

# ── /protect — 1d FREE, 2d premium ───────────────────────────────────────────
async def protect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    await ensure_user(u.id, u.username or "", u.full_name)
    d = await get_user(u.id); now = ts()
    # Already protected?
    if d["protected_until"] > now:
        rem = d["protected_until"]-now
        dy=rem//86400; hr=(rem%86400)//3600; mn=(rem%3600)//60; sc2=rem%60
        await update.message.reply_html(
            f"🛡️ {sc('You Are Already Protected.')}\n"
            f"⏳ {bold_sc('Remaining')}: {dy}d {hr}h {mn}m {sc2}s"
        ); return
    dm = {"1d":1,"2d":2}
    if not args or args[0].lower() not in dm:
        await update.message.reply_html(
            f"⚠️ {sc('Usage')}: /protect 1d/2d\n"
            f"🆓 1d = <b>FREE</b> for all\n"
            f"💓 2d = Premium only ({fmt(PROTECT_2D_COST)} coins)"
        ); return
    days = dm[args[0].lower()]
    if days == 2:
        if not d.get("is_premium"):
            await update.message.reply_html(
                f"💓 2d {sc('Protection Is Premium Only!')}\n/pay"
            ); return
        cost = PROTECT_2D_COST
        if d["balance"] < cost:
            await update.message.reply_html(
                f"❌ {sc('Need')} {fmt(cost)}, {sc('you have')} {fmt(d['balance'])}"
            ); return
        await update_user(u.id, balance=d["balance"]-cost)
    else:
        cost = 0  # 1d is FREE
    until = now + days*86400
    await update_user(u.id, protected_until=until)
    dead_note = f"\n🔄 {sc('But Your Status Is Still Dead Until Revive.')}" if d["dead_until"] > now else ""
    await update.message.reply_html(
        f"🛡️ {sc('You Are Now Protected For')} <b>{days}d</b>"
        + (f" (-{fmt(cost)})" if cost else " 🆓")
        + dead_note
    )

# ── /give ─────────────────────────────────────────────────────────────────────
async def give_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name); giver = await get_user(u.id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(f"💸 {sc('Reply To A User To Give Balance.')}"); return
    if not context.args: await msg.reply_html("❌ Usage: /give [reply] <amount>"); return
    try: amount = int(context.args[0])
    except: await msg.reply_html("❌ Invalid amount!"); return
    if amount <= 0: await msg.reply_html("❌ Positive only!"); return
    tax = TAX_PREMIUM if giver.get("is_premium") else TAX_NORMAL
    total = amount + int(amount*tax)
    if giver["balance"] < total:
        await msg.reply_html(f"❌ {sc('Need')} {fmt(total)} (incl. {int(tax*100)}% tax)"); return
    ru = msg.reply_to_message.from_user
    if ru.id == u.id: await msg.reply_html("😂 Can't give to yourself!"); return
    await ensure_user(ru.id, ru.username or "", ru.full_name)
    await update_user(u.id, balance=giver["balance"]-total)
    await add_balance(ru.id, amount)
    await msg.reply_html(
        f"💸 {mention(u)} {sc('Gave')} {mention(ru)} <b>{fmt(amount)}</b>\n"
        f"({sc('Tax')}: {fmt(int(amount*tax))})"
    )

# ── /toprich ──────────────────────────────────────────────────────────────────
async def toprich_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await get_top_rich(10)
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text = f"🏆 <b>{sc('Top 10 Richest Users')}:</b>\n\n"
    for i, r in enumerate(rows):
        icon = r.get("premium_emoji") or ("💓" if r.get("is_premium") else "👤")
        name = r.get("full_name") or r.get("username") or "User"
        text += f"{medals[i]} {icon} {mention_id(r['_id'],name)}: <b>{fmt(r['balance'])}</b>\n"
    text += f"\n💓 = {sc('Premium')} • 👤 = {sc('Normal')}\n✅ {sc('Upgrade To Premium')}: /pay"
    await update.message.reply_html(text)

async def topkill_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await get_top_kill(10)
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text = f"💀 <b>{sc('Top 10 Killers')}:</b>\n\n"
    for i, r in enumerate(rows):
        icon = r.get("premium_emoji") or ("💓" if r.get("is_premium") else "👤")
        name = r.get("full_name") or r.get("username") or "User"
        text += f"{medals[i]} {icon} {mention_id(r['_id'],name)}: <b>{r['kills']} kills</b>\n"
    await update.message.reply_html(text)

# ── /wallet ───────────────────────────────────────────────────────────────────
async def wallet_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name); d = await get_user(u.id)
    if not d.get("is_premium"):
        await update.message.reply_html(
            f"❗️ {sc('Only Premium Users Can Use Wallet.')}\n/pay"
        ); return
    args = context.args
    if not args:
        await update.message.reply_html(
            f"💼 <b>{sc('Wallet')} — {mention(u)}</b>\n\n"
            f"💰 {sc('Balance')}: {fmt(d['balance'])}\n"
            f"🏦 {sc('Wallet')}: {fmt(d.get('wallet',0))}\n\n"
            "/wallet deposit <amount>\n/wallet withdraw <amount>"
        ); return
    action = args[0].lower()
    try: amount = int(args[1]) if len(args)>1 else 0
    except: await update.message.reply_html("❌ Invalid!"); return
    if amount <= 0: await update.message.reply_html("❌ Positive only!"); return
    if action == "deposit":
        if d["balance"] < amount: await update.message.reply_html("❌ Not enough!"); return
        await update_user(u.id, balance=d["balance"]-amount, wallet=d.get("wallet",0)+amount)
        await update.message.reply_html(f"✅ {sc('Deposited')} {fmt(amount)} {sc('To Wallet!')} 🏦")
    elif action == "withdraw":
        if d.get("wallet",0) < amount: await update.message.reply_html("❌ Not enough in wallet!"); return
        await update_user(u.id, wallet=d.get("wallet",0)-amount, balance=d["balance"]+amount)
        await update.message.reply_html(f"✅ {sc('Withdrew')} {fmt(amount)} {sc('From Wallet!')} 💰")
    else:
        await update.message.reply_html("❌ Use: /wallet deposit/withdraw <amount>")

# ── /rank ─────────────────────────────────────────────────────────────────────
async def rank_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    tu = msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else update.effective_user
    await ensure_user(tu.id, tu.username or "", tu.full_name)
    cr = await get_card_rank(tu.id)
    pos, total = await get_card_rank_position(tu.id)
    await msg.reply_html(
        f"🃏 <b>{sc('Card Rank')}</b>\n\n"
        f"👤 {mention(tu)}\n"
        f"👉 {sc('Wins')}: {cr['wins']} || {sc('Losses')}: {cr['losses']}\n"
        f"💰 {sc('Amount Won')}: {fmt(cr['won_amount'])}\n"
        f"💸 {sc('Amount Lost')}: {fmt(cr['lost_amount'])}\n"
        f"🔥 {sc('Streak')}: {cr['streak']} / {cr['best_streak']}\n"
        f"🎖️ {sc('Rank')}: {pos} / {total}"
    )

async def pfp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    tu = msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else update.effective_user
    await ensure_user(tu.id, tu.username or "", tu.full_name)
    d = await get_user(tu.id); now = ts()
    dk_max = DAILY_KILLS_PREMIUM if d.get("is_premium") else DAILY_KILLS_NORMAL
    dr_max = DAILY_ROBS_PREMIUM  if d.get("is_premium") else DAILY_ROBS_NORMAL
    await msg.reply_html(
        f"📊 <b>{sc('Stats')} — {mention(tu)}</b>\n\n"
        f"☠️ {sc('Daily Kills')}: {d.get('daily_kills',0)}/{dk_max}\n"
        f"🔪 {sc('Daily Robs')}: {d.get('daily_robs',0)}/{dr_max}\n"
        f"💎 {sc('Gems')}: {d.get('gems',0)}\n"
        f"💼 {sc('Wallet')}: {fmt(d.get('wallet',0))}"
    )

async def gems_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name); d = await get_user(u.id)
    prem = d.get("is_premium", False)
    status = f"💓 {sc('Premium')}" if prem else f"⚠️ {sc('Normal')}"
    if not prem:
        await update.message.reply_html(
            f"💎 <b>{sc('Iota Gems Store')}</b>\n\n"
            f"{sc('Only Premium Users Can Use Gems.')}\n\n"
            f"💎 1 {sc('Gem')} = {fmt(GEMS_PRICE_COINS)}\n"
            f"👑 {sc('Your Status')}: {status}\n"
            f"👉 {sc('Buy Premium')}: /pay | /fpay\n"
            f"👉 {sc('Check Your ID')}: /id"
        ); return
    await update.message.reply_html(
        f"💎 <b>{sc('Gems')} — {mention(u)}</b>\n\n"
        f"💎 {sc('Gems')}: <b>{d.get('gems',0)}</b> = {fmt(d.get('gems',0)*GEMS_PRICE_COINS)}\n"
        f"👑 {sc('Your Status')}: {status}\n"
        f"/fgems — {sc('Buy with Telegram Stars')}"
    )

async def claim_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; u = update.effective_user
    if chat.type == "private":
        await update.message.reply_html(f"🚫 {sc('This Command Works Only In Groups.')}"); return
    await ensure_user(u.id, u.username or "", u.full_name)
    try: count = await context.bot.get_chat_member_count(chat.id)
    except: count = 0
    if count < 500:
        await update.message.reply_html(
            f"❌ {sc('Group Needs 500+ Members!')} {sc('Currently')}: <b>{count}</b>"
        ); return
    reward = 10000 + (count//100)*500
    await add_balance(u.id, reward)
    await update.message.reply_html(
        f"✅ {mention(u)} {sc('Claimed')} {fmt(reward)}!\n"
        f"👥 {sc('Members')}: <b>{count}</b>"
    )

async def coupons_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_html(
            f"🎟 <b>{sc('Iota Cutie Coupons Guide')}</b> 🎟\n\n"
            f"🔹 /create_coupon — {sc('Create Coupon Code For Ur Gc')}\n"
            f"🔹 /coupon <code> — {sc('Claim Coupon')}\n"
            f"🔹 /del_coupon — {sc('Delete The Coupon Code')}\n"
            f"🔹 /status — {sc('Check Status Of Coupon Code')}\n\n"
            f"🥀 {sc('You Cant Create 2 Coupons For Same Group.')}\n\n"
            f"{sc('Redeem global coupon')}: /coupon <code>"
        ); return
    code = args[0].lower(); u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if code in GLOBAL_COUPONS:
        if not await use_global_coupon(u.id, code):
            await update.message.reply_html(f"❌ {sc('Already Used!')}"); return
        reward = GLOBAL_COUPONS[code]; await add_balance(u.id, reward)
        await update.message.reply_html(
            f"🎟️ {mention(u)} {sc('Redeemed')} <b>{code}</b>!\n💰 +{fmt(reward)}"
        )
    else:
        await update.message.reply_html(f"❌ {sc('Invalid Coupon Code!')}")

async def coupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    if chat.type == "private":
        args = context.args
        if not args: await update.message.reply_html(f"🚫 {sc('Use In A Group Or')}: /coupon <code>"); return
        code = args[0].lower()
        if code in GLOBAL_COUPONS:
            if not await use_global_coupon(u.id, code):
                await update.message.reply_html(f"❌ {sc('Already Used!')}"); return
            await add_balance(u.id, GLOBAL_COUPONS[code])
            await update.message.reply_html(f"✅ +{fmt(GLOBAL_COUPONS[code])}")
        else:
            await update.message.reply_html(f"❌ {sc('Invalid!')}")
        return
    gc = await get_group_coupon(chat.id)
    if not gc: await update.message.reply_html(f"❌ {sc('No Active Coupon!')}"); return
    if not await use_group_coupon(u.id, chat.id):
        await update.message.reply_html(f"❌ {sc('Already Claimed!')}"); return
    await add_balance(u.id, gc["amount"])
    await update.message.reply_html(
        f"🎟️ {mention(u)} {sc('Claimed')}!\n💰 +{fmt(gc['amount'])}"
    )

async def create_coupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; u = update.effective_user
    if chat.type == "private": await update.message.reply_html(f"🚫 {sc('Group Only!')}"); return
    from utils.helpers import is_admin
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    args = context.args
    if len(args) < 2: await update.message.reply_html("Usage: /create_coupon <code> <amount>"); return
    if await get_group_coupon(chat.id):
        await update.message.reply_html(f"❌ {sc('Already Have A Coupon!')} /del_coupon"); return
    code = args[0].lower()
    try: amount = int(args[1])
    except: await update.message.reply_html("❌ Invalid amount!"); return
    await set_group_coupon(chat.id, code, amount, u.id)
    await update.message.reply_html(
        f"🎟️ {sc('Coupon Created!')}\n"
        f"{sc('Code')}: <b>{code}</b> | {sc('Reward')}: {fmt(amount)}\n"
        f"{sc('Claim')}: /coupon {code}"
    )

async def del_coupon_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type == "private": await update.message.reply_html(f"🚫 {sc('Group Only!')}"); return
    from utils.helpers import is_admin
    if not await is_admin(update, context): await update.message.reply_html("❌ Admins only!"); return
    if not await get_group_coupon(chat.id):
        await update.message.reply_html(f"❌ {sc('No Coupon!')}"); return
    await delete_group_coupon(chat.id)
    await update.message.reply_html(f"✅ {sc('Coupon Deleted!')}")

async def coupon_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat; gc = await get_group_coupon(chat.id)
    if not gc: await update.message.reply_html(f"❌ {sc('No Active Coupon!')}"); return
    await update.message.reply_html(
        f"🎟️ {sc('Code')}: <b>{gc['code']}</b> | {sc('Reward')}: {fmt(gc['amount'])}"
    )

async def economy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📖 View Economy Guide", callback_data="eco_guide")]])
    await update.message.reply_html(
        f"🎮 {sc('Click The Button Below To Know About Iota Economy Game.')}",
        reply_markup=kb
    )

async def eco_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    if q.data == "eco_guide":
        await q.edit_message_text(
            f"💰 <b>{sc('Economy Guide')}</b>\n\n"
            f"👤 {sc('Normal')}: {sc('Daily')} {fmt(DAILY_NORMAL)} | {sc('Rob')} {fmt(ROB_MAX_NORMAL)} | {sc('Tax')} {int(TAX_NORMAL*100)}%\n"
            f"💓 {sc('Premium')}: {sc('Daily')} {fmt(DAILY_PREMIUM)} | {sc('Rob')} {fmt(ROB_MAX_PREMIUM)} | {sc('Tax')} {int(TAX_PREMIUM*100)}%\n\n"
            f"💀 {sc('Revive Cost')}: {fmt(REVIVE_COST)} coins\n"
            f"🛡️ 1d {sc('Protection')}: <b>FREE</b>\n"
            f"🛡️ 2d {sc('Protection')}: {fmt(PROTECT_2D_COST)} (Premium)\n"
            f"💎 1 {sc('Gem')} = {fmt(GEMS_PRICE_COINS)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("« Back", callback_data="eco_back")]])
        )
    elif q.data == "eco_back":
        await q.edit_message_text(
            f"🎮 {sc('Click The Button Below To Know About Iota Economy Game.')}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("📖 View Economy Guide", callback_data="eco_guide")]])
        )

# ── Group economy stubs ───────────────────────────────────────────────────────
async def gbal_cmd(update, context):
    u=update.effective_user; chat=update.effective_chat
    if chat.type=="private": await update.message.reply_html(f"🚫 {sc('Group Only!')}"); return
    await ensure_user(u.id); g=await get_guser(u.id,chat.id)
    await update.message.reply_html(
        f"🏘️ <b>{sc('Group Balance')} — {mention(u)}</b>\n"
        f"💰 {fmt(g['balance'])} | 💀 {g['kills']} | 🔫 {g['robs']}"
    )

async def gkill_cmd(update, context):
    u=update.effective_user; msg=update.effective_message; chat=update.effective_chat; now=ts()
    if chat.type=="private": await msg.reply_html(f"🚫 {sc('Group Only!')}"); return
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(f"❌ {sc('Reply To Someone!')}"); return
    vu=msg.reply_to_message.from_user
    if vu.id==u.id or vu.is_bot: await msg.reply_html("❌ Invalid!"); return
    await ensure_user(u.id); await ensure_user(vu.id)
    gv=await get_guser(vu.id,chat.id); gk=await get_guser(u.id,chat.id)
    if gv["dead_until"]>now: await msg.reply_html(f"💀 {mention(vu)} {sc('Already Dead!')}"); return
    if gv["protected_until"]>now: await msg.reply_html(f"🛡️ {mention(vu)} {sc('Protected!')}"); return
    r=random.randint(100,300)
    await update_guser(vu.id,chat.id,dead_until=now+3600)
    await update_guser(u.id,chat.id,balance=gk["balance"]+r,kills=gk["kills"]+1)
    await msg.reply_html(f"💀 {mention(u)} {sc('Killed')} {mention(vu)}!\n💰 +{fmt(r)}")

async def grob_cmd(update, context):
    u=update.effective_user; msg=update.effective_message; chat=update.effective_chat; now=ts()
    if chat.type=="private": await msg.reply_html(f"🚫 {sc('Group Only!')}"); return
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(f"❌ {sc('Reply To Someone!')}"); return
    vu=msg.reply_to_message.from_user
    if vu.id==u.id or vu.is_bot: await msg.reply_html("❌ Invalid!"); return
    await ensure_user(u.id); await ensure_user(vu.id)
    gv=await get_guser(vu.id,chat.id); gr=await get_guser(u.id,chat.id)
    if gv["protected_until"]>now: await msg.reply_html(f"🛡️ {sc('Protected!')}"); return
    if gv["dead_until"]>now: await msg.reply_html(f"💀 {sc('Dead!')}"); return
    amt=min(random.randint(100,5000),gv["balance"])
    if amt<=0: await msg.reply_html(f"💸 {sc('No Coins!')}"); return
    await update_guser(vu.id,chat.id,balance=gv["balance"]-amt)
    await update_guser(u.id,chat.id,balance=gr["balance"]+amt,robs=gr["robs"]+1)
    await msg.reply_html(f"🔫 {mention(u)} {sc('Robbed')} {mention(vu)}!\n💰 +{fmt(amt)}")

async def grevive_cmd(update, context):
    u=update.effective_user; msg=update.effective_message; chat=update.effective_chat; now=ts()
    if chat.type=="private": await msg.reply_html(f"🚫 {sc('Group Only!')}"); return
    tu=msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else u
    await ensure_user(tu.id); g=await get_guser(tu.id,chat.id)
    if g["dead_until"]<=now: await msg.reply_html(f"❓ {sc('Not Dead!')}"); return
    await update_guser(tu.id,chat.id,dead_until=0)
    await msg.reply_html(f"💚 {mention(u)} {sc('Revived')} {mention(tu)}!")

async def gprotect_cmd(update, context):
    u=update.effective_user; chat=update.effective_chat; now=ts()
    if chat.type=="private": await update.message.reply_html(f"🚫 {sc('Group Only!')}"); return
    await ensure_user(u.id); g=await get_guser(u.id,chat.id)
    if g["balance"]<400: await update.message.reply_html(f"❌ {sc('Need 400 group coins!')}"); return
    await update_guser(u.id,chat.id,balance=g["balance"]-400,protected_until=now+86400)
    await update.message.reply_html(f"🛡️ {mention(u)} {sc('Protected In Group For 1 Day!')}")

async def gcheck_cmd(update, context):
    msg=update.effective_message; chat=update.effective_chat; now=ts()
    tu=msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else update.effective_user
    await ensure_user(tu.id); g=await get_guser(tu.id,chat.id)
    if g["protected_until"]>now:
        rem=g["protected_until"]-now
        await msg.reply_html(f"🛡️ {mention(tu)} {sc('Protected')} {rem//3600}h {(rem%3600)//60}m")
    else:
        await msg.reply_html(f"❌ {sc('No Group Protection')}")

async def granks_cmd(update, context):
    chat=update.effective_chat
    if chat.type=="private": await update.message.reply_html(f"🚫 {sc('Group Only!')}"); return
    rows=await get_granks(chat.id)
    if not rows: await update.message.reply_html(f"📊 {sc('No Data Yet!')}"); return
    medals=["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text=f"🏆 <b>{sc('Group Ranks')} — {chat.title}</b>\n\n"
    for i,r in enumerate(rows):
        name=r.get("full_name") or r.get("username") or "User"
        text+=f"{medals[i]} {mention_id(r['user_id'],name)} — {fmt(r['balance'])}\n"
    await update.message.reply_html(text)

async def auto_delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg=update.effective_message
    if msg and update.effective_chat.type!="private":
        asyncio.create_task(delete_later(context.bot,msg.chat_id,msg.message_id,300))
