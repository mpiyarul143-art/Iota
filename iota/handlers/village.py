import time
from telegram import Update
from telegram.ext import ContextTypes
from utils.db import ensure_user, get_user, update_user, add_balance, get_village, update_village, get_empire_top
from utils.helpers import mention, mention_id, fmt

MINE_INTERVAL = 3600
MINE_YIELD = {
    "woodyard":  {1:10,2:25,3:50,4:90,5:150},
    "quarry":    {1:8, 2:20,3:40,4:75,5:120},
    "iron_mine": {1:5, 2:12,3:25,4:50,5:90},
}
BUILDING_COSTS = {
    "woodyard":  {2:500, 3:1500,4:3000,5:6000},
    "quarry":    {2:600, 3:1800,4:3500,5:7000},
    "iron_mine": {2:800, 3:2000,4:4000,5:8000},
}
CONVERT_RATE = {"wood":5,"stone":8,"iron":12}

async def mines_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username or "", u.full_name)
    v = get_village(u.id); now = int(time.time()); elapsed = now - v["last_mine"]
    if elapsed < MINE_INTERVAL:
        rem = MINE_INTERVAL - elapsed
        await update.message.reply_html(
            f"⛏️ <b>Mines — {mention(u)}</b>\n\n"
            f"🪵 Wood: <b>{v['wood']}</b>\n🪨 Stone: <b>{v['stone']}</b>\n⚙️ Iron: <b>{v['iron']}</b>\n\n"
            f"⏳ Next: <b>{rem//3600}h {(rem%3600)//60}m</b>\n"
            f"Levels: 🪵{v['woodyard_level']} | 🪨{v['quarry_level']} | ⚙️{v['iron_mine_level']}"
        ); return
    hours = min(elapsed // MINE_INTERVAL, 24)
    wg = MINE_YIELD["woodyard"][v["woodyard_level"]] * hours
    sg = MINE_YIELD["quarry"][v["quarry_level"]] * hours
    ig = MINE_YIELD["iron_mine"][v["iron_mine_level"]] * hours
    update_village(u.id, wood=v["wood"]+wg, stone=v["stone"]+sg, iron=v["iron"]+ig, last_mine=now)
    await update.message.reply_html(
        f"⛏️ <b>Collected!</b>\n🪵 +{wg} Wood | 🪨 +{sg} Stone | ⚙️ +{ig} Iron\n⏳ Next: 1 hour"
    )

async def build_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    ensure_user(u.id, u.username or "", u.full_name)
    if not args:
        await update.message.reply_html(
            "🏗️ <b>Build Menu</b>\n\nUsage: /build <building>\n\n"
            "🪵 <code>woodyard</code>  🪨 <code>quarry</code>  ⚙️ <code>iron_mine</code>"
        ); return
    bld = args[0].lower()
    if bld not in BUILDING_COSTS:
        await update.message.reply_html("❌ Unknown building!"); return
    v = get_village(u.id); d = get_user(u.id)
    lv_map = {"woodyard":v["woodyard_level"],"quarry":v["quarry_level"],"iron_mine":v["iron_mine_level"]}
    cur = lv_map.get(bld, 1); nxt = cur + 1
    if nxt not in BUILDING_COSTS[bld]:
        await update.message.reply_html(f"✅ <b>{bld}</b> is at max level!"); return
    cost = BUILDING_COSTS[bld][nxt]
    if d["balance"] < cost:
        await update.message.reply_html(f"❌ Need {fmt(cost)}, you have {fmt(d['balance'])}"); return
    update_user(u.id, balance=d["balance"]-cost)
    field = {"woodyard":"woodyard_level","quarry":"quarry_level","iron_mine":"iron_mine_level"}
    update_village(u.id, **{field[bld]: nxt})
    await update.message.reply_html(f"🏗️ <b>{bld}</b> → Level <b>{nxt}</b>! Cost: {fmt(cost)}")

async def settle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    ensure_user(u.id, u.username or "", u.full_name); v = get_village(u.id)
    if not args or len(args)<2:
        await update.message.reply_html(
            f"🏦 Vault: {fmt(v['vault'])}  |  Treasury: {fmt(v['treasury'])}\n"
            "/settle vault <amount> — Treasury→Vault\n/settle treasury <amount> — Vault→Treasury"
        ); return
    d = args[0].lower()
    try: amt = int(args[1])
    except: await update.message.reply_html("❌ Invalid amount!"); return
    if d=="vault":
        if v["treasury"]<amt: await update.message.reply_html("❌ Not enough treasury!"); return
        update_village(u.id, treasury=v["treasury"]-amt, vault=v["vault"]+amt)
        await update.message.reply_html(f"✅ Moved {fmt(amt)} Treasury→Vault!")
    elif d=="treasury":
        if v["vault"]<amt: await update.message.reply_html("❌ Not enough vault!"); return
        update_village(u.id, vault=v["vault"]-amt, treasury=v["treasury"]+amt)
        await update.message.reply_html(f"✅ Moved {fmt(amt)} Vault→Treasury!")

async def convert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    ensure_user(u.id, u.username or "", u.full_name); v = get_village(u.id)
    if not args or len(args)<2:
        await update.message.reply_html(
            f"💱 Resources:\n🪵 Wood: {v['wood']} (×{CONVERT_RATE['wood']})\n"
            f"🪨 Stone: {v['stone']} (×{CONVERT_RATE['stone']})\n"
            f"⚙️ Iron: {v['iron']} (×{CONVERT_RATE['iron']})\n\n"
            "Usage: /convert <wood/stone/iron> <amount>"
        ); return
    res = args[0].lower()
    if res not in CONVERT_RATE: await update.message.reply_html("❌ Use wood/stone/iron"); return
    try: amt = int(args[1])
    except: await update.message.reply_html("❌ Invalid amount!"); return
    stock = {"wood":v["wood"],"stone":v["stone"],"iron":v["iron"]}[res]
    if stock < amt: await update.message.reply_html(f"❌ Only {stock} {res} available!"); return
    coins = amt * CONVERT_RATE[res]
    update_village(u.id, **{res: stock-amt}); add_balance(u.id, coins)
    await update.message.reply_html(f"💱 {amt} {res} → <b>{fmt(coins)}</b>!")

async def emperors_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = get_empire_top(10); medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text = "👑 <b>Top 10 Emperors</b>\n\n"
    for i,r in enumerate(rows):
        name = r["full_name"] or r["username"] or "User"
        text += f"{medals[i]} {mention_id(r['user_id'],name)} — {fmt(r['total'])}\n"
    await update.message.reply_html(text)

async def guide_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "📖 <b>Village/Empire Guide</b>\n\n"
        "⛏️ /mines — Collect wood/stone/iron every hour\n"
        "🏗️ /build — Upgrade mines to produce more\n"
        "💱 /convert — Resources→Coins\n"
        "🏦 /settle — Move between Vault & Treasury\n"
        "👑 /emperors — Top 10 by total wealth\n\n"
        "🌍 Stages: Village → Town → City → Empire!"
    )
