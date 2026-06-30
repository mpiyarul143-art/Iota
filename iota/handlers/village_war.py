"""
Iota Village War System (Riruru-style)
Commands:
  /attack, /defense, /troops, /walls, /build
  /train, /kingdom, /spy, /storage, /collect, /vault
"""
import random
import asyncio
import time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.mongo_db import get_db, ensure_user, get_user, update_user, add_balance
from utils.helpers import mention, mention_id, fmt, ts
from config import TROOP_TYPES, WALL_TYPES, DEFENSE_TYPES, GIFS, MINE_INTERVAL, CITIZEN_START

# ── DB helpers ────────────────────────────────────────────────────────────────

async def _ensure_village(uid: int) -> dict:
    db = get_db()
    v = await db.village.find_one({"_id": uid})
    if not v:
        v = {
            "_id": uid,
            # Resources
            "wood": 0, "stone": 0, "iron": 0,
            # Currency
            "treasury": 0, "vault": 0,
            # Citizens
            "citizens": CITIZEN_START,
            "max_citizens": CITIZEN_START,
            "workers": 0,
            # Troops  {type: count}
            "troops": {},
            # Buildings
            "home_level": 1,
            "camp_level": 1,
            "hut_level": 1,
            "woodyard_level": 1,
            "quarry_level": 1,
            "iron_mine_level": 1,
            # Walls  {type: {"level": 1, "hp": 300, "max_hp": 300}}
            "walls": {},
            # Defense  {type: {"level": 1, "hp": 300, "max_hp": 300, "damage": 20}}
            "defense": {},
            # Storage
            "storage_cap": 2000,
            # Times
            "last_mine": ts(),
            "last_tax": ts(),
            "last_attack": 0,
            # Stage
            "stage": "village",    # village/town/city/empire
            "kingdom_level": 1,
            # Protection
            "protected_until": 0,
        }
        await db.village.insert_one(v)
    return v


async def _get_village(uid: int) -> dict:
    db = get_db()
    v = await db.village.find_one({"_id": uid})
    return v or await _ensure_village(uid)


async def _upd(uid: int, **kw):
    await get_db().village.update_one({"_id": uid}, {"$set": kw}, upsert=True)


MINE_YIELD = {
    "woodyard":  {1: 10, 2: 25, 3: 50, 4: 90, 5: 150},
    "quarry":    {1: 8,  2: 20, 3: 40, 4: 75, 5: 120},
    "iron_mine": {1: 5,  2: 12, 3: 25, 4: 50, 5: 90},
}
BUILD_COSTS = {
    "home":      {2: (500,0,0),  3: (1500,500,0),  4: (3000,1000,500)},
    "camp":      {2: (300,0,0),  3: (1000,300,0),  4: (2500,800,300)},
    "hut":       {2: (200,0,0),  3: (800,200,0),   4: (2000,600,200)},
    "woodyard":  {2: (0,300,0),  3: (0,800,0),     4: (0,2000,500), 5: (0,5000,1000)},
    "quarry":    {2: (300,0,0),  3: (800,0,0),     4: (2000,0,500), 5: (5000,0,1000)},
    "iron_mine": {2: (500,300,0),3: (1200,800,0),  4: (3000,2000,500)},
}


# ═══════════════════════════════════════════════════════
#  /collect — collect all resources from mines
# ═══════════════════════════════════════════════════════

async def collect_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id); now = ts()
    elapsed = now - v["last_mine"]

    if elapsed < 300:  # minimum 5 min
        rem = 300 - elapsed
        await update.message.reply_html(
            f"⏳ {mention(u)}, wait <b>{rem//60}m {rem%60}s</b> before collecting again!"
        ); return

    hours = min(elapsed / 3600, 24)
    wg = int(MINE_YIELD["woodyard"][v["woodyard_level"]]  * hours)
    sg = int(MINE_YIELD["quarry"][v["quarry_level"]]       * hours)
    ig = int(MINE_YIELD["iron_mine"][v["iron_mine_level"]] * hours)

    # Citizen tax
    active_citizens = v["max_citizens"] - len(v.get("troops",{})) - v.get("workers",0)
    active_citizens = max(0, active_citizens)
    coin_gain = int(active_citizens * 2 * hours)

    # Cap at storage
    cap = v["storage_cap"]
    new_wood  = min(v["wood"]  + wg, cap)
    new_stone = min(v["stone"] + sg, cap)
    new_iron  = min(v["iron"]  + ig, cap)
    new_treas = v["treasury"] + coin_gain

    await _upd(u.id, wood=new_wood, stone=new_stone, iron=new_iron,
               treasury=new_treas, last_mine=now)

    await update.message.reply_html(
        f"⛏️ <b>Resources Collected!</b>\n\n"
        f"🪵 +{wg} Wood  (→ {new_wood})\n"
        f"🪨 +{sg} Stone (→ {new_stone})\n"
        f"⚙️ +{ig} Iron  (→ {new_iron})\n"
        f"🪙 +{fmt(coin_gain)} Coins → Treasury\n\n"
        f"⏳ Next collect: available anytime after 5 min"
    )


# ═══════════════════════════════════════════════════════
#  /storage — check resources
# ═══════════════════════════════════════════════════════

async def storage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id); cap = v["storage_cap"]
    await update.message.reply_html(
        f"📦 <b>Storage — {mention(u)}</b>\n\n"
        f"🪵 Wood:  <b>{v['wood']}</b> / {cap}\n"
        f"🪨 Stone: <b>{v['stone']}</b> / {cap}\n"
        f"⚙️ Iron:  <b>{v['iron']}</b> / {cap}\n\n"
        f"🪙 Treasury: <b>{fmt(v['treasury'])}</b>\n"
        f"🏛️ Vault:    <b>{fmt(v['vault'])}</b>\n\n"
        f"Upgrade storage via /build"
    )


# ═══════════════════════════════════════════════════════
#  /vault — check vault + gems + rank
# ═══════════════════════════════════════════════════════

async def vault_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id)
    d = await get_user(u.id)
    # Empire rank
    pipeline = [
        {"$addFields": {"total": {"$add": ["$vault", "$treasury"]}}},
        {"$match": {"total": {"$gt": v["vault"] + v["treasury"]}}},
        {"$count": "rank"}
    ]
    result = await get_db().village.aggregate(pipeline).to_list(1)
    rank = (result[0]["rank"] + 1) if result else 1

    await update.message.reply_html(
        f"🏛️ <b>Vault — {mention(u)}</b>\n\n"
        f"💎 Gems: <b>{d['gems']}</b>\n"
        f"💰 Vault Coins: <b>{fmt(v['vault'])}</b>\n"
        f"🪙 Treasury: <b>{fmt(v['treasury'])}</b>\n\n"
        f"🌍 Empire Rank: <b>#{rank}</b>\n"
        f"🏰 Kingdom Level: <b>{v['kingdom_level']}</b>\n"
        f"🏘️ Stage: <b>{v['stage'].title()}</b>"
    )


# ═══════════════════════════════════════════════════════
#  /mines — mine levels and production
# ═══════════════════════════════════════════════════════

async def mines_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id)
    now = ts(); elapsed = now - v["last_mine"]
    rem = max(0, 300 - elapsed)

    def rate(mine, lv): return MINE_YIELD[mine][min(lv, 5)]

    await update.message.reply_html(
        f"⛏️ <b>Mines — {mention(u)}</b>\n\n"
        f"🪵 Wood Yard   Lv{v['woodyard_level']}  → {rate('woodyard', v['woodyard_level'])}/hr\n"
        f"🪨 Quarry      Lv{v['quarry_level']}  → {rate('quarry', v['quarry_level'])}/hr\n"
        f"⚙️ Iron Mine   Lv{v['iron_mine_level']}  → {rate('iron_mine', v['iron_mine_level'])}/hr\n\n"
        f"⏳ Collect in: <b>{'Ready!' if rem==0 else f'{rem//60}m {rem%60}s'}</b>\n"
        f"Use /collect to harvest!"
    )


# ═══════════════════════════════════════════════════════
#  /build — buildings with inline buttons
# ═══════════════════════════════════════════════════════

async def build_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id); d = await get_user(u.id)

    if not args:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Home",       callback_data=f"build_{u.id}_home"),
             InlineKeyboardButton("⛺ Camp",        callback_data=f"build_{u.id}_camp")],
            [InlineKeyboardButton("🛖 Hut",         callback_data=f"build_{u.id}_hut"),
             InlineKeyboardButton("🪵 Woodyard",    callback_data=f"build_{u.id}_woodyard")],
            [InlineKeyboardButton("🪨 Quarry",      callback_data=f"build_{u.id}_quarry"),
             InlineKeyboardButton("⚙️ Iron Mine",   callback_data=f"build_{u.id}_iron_mine")],
        ])
        await update.message.reply_html(
            f"🏗️ <b>Buildings — {mention(u)}</b>\n\n"
            f"🏠 Home Lv{v['home_level']}  ⛺ Camp Lv{v['camp_level']}  🛖 Hut Lv{v['hut_level']}\n"
            f"🪵 Woodyard Lv{v['woodyard_level']}  🪨 Quarry Lv{v['quarry_level']}  ⚙️ Iron Mine Lv{v['iron_mine_level']}\n\n"
            f"💰 Balance: {fmt(d['balance'])}\n"
            f"🪵 {v['wood']} | 🪨 {v['stone']} | ⚙️ {v['iron']}\n\n"
            f"Tap to upgrade:",
            reply_markup=kb
        )
        return

    bld = args[0].lower().replace("-","_")
    await _do_build(update, context, u.id, bld)


async def build_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    parts = q.data.split("_", 2)  # build_<uid>_<building>
    if len(parts) < 3: return
    uid = int(parts[1]); bld = parts[2]
    if q.from_user.id != uid:
        await q.answer("Not your build menu!", show_alert=True); return
    # Create a fake update-like context
    await _do_build_callback(q, context, uid, bld)


async def _do_build(update, context, uid, bld):
    v = await _get_village(uid); d = await get_user(uid)
    lv_map = {
        "home": v["home_level"], "camp": v["camp_level"], "hut": v["hut_level"],
        "woodyard": v["woodyard_level"], "quarry": v["quarry_level"], "iron_mine": v["iron_mine_level"],
    }
    cur = lv_map.get(bld)
    if cur is None:
        await update.message.reply_html("❌ Unknown building! Use /build to see list"); return
    nxt = cur + 1
    costs = BUILD_COSTS.get(bld, {})
    if nxt not in costs:
        await update.message.reply_html(f"✅ <b>{bld}</b> is at max level!"); return
    cw, cs, ci = costs[nxt]
    if v["wood"] < cw or v["stone"] < cs or v["iron"] < ci:
        await update.message.reply_html(
            f"❌ Not enough resources!\nNeed: 🪵{cw} 🪨{cs} ⚙️{ci}\n"
            f"Have: 🪵{v['wood']} 🪨{v['stone']} ⚙️{v['iron']}"
        ); return
    field_map = {
        "home":"home_level","camp":"camp_level","hut":"hut_level",
        "woodyard":"woodyard_level","quarry":"quarry_level","iron_mine":"iron_mine_level"
    }
    await _upd(uid, wood=v["wood"]-cw, stone=v["stone"]-cs, iron=v["iron"]-ci,
               **{field_map[bld]: nxt})
    # Home upgrade increases max citizens
    if bld == "home":
        new_max = v["max_citizens"] + 20
        await _upd(uid, max_citizens=new_max)
    await update.message.reply_html(
        f"🏗️ <b>{bld.replace('_',' ').title()}</b> upgraded to Level <b>{nxt}</b>!\n"
        f"🪵-{cw} 🪨-{cs} ⚙️-{ci}"
    )


async def _do_build_callback(q, context, uid, bld):
    v = await _get_village(uid)
    lv_map = {
        "home": v["home_level"], "camp": v["camp_level"], "hut": v["hut_level"],
        "woodyard": v["woodyard_level"], "quarry": v["quarry_level"], "iron_mine": v["iron_mine_level"],
    }
    cur = lv_map.get(bld)
    if cur is None: await q.edit_message_text("❌ Unknown!"); return
    nxt = cur + 1
    costs = BUILD_COSTS.get(bld, {})
    if nxt not in costs:
        await q.answer(f"✅ {bld} is max level!", show_alert=True); return
    cw, cs, ci = costs[nxt]
    if v["wood"] < cw or v["stone"] < cs or v["iron"] < ci:
        await q.answer(
            f"❌ Need: 🪵{cw} 🪨{cs} ⚙️{ci}\nHave: 🪵{v['wood']} 🪨{v['stone']} ⚙️{v['iron']}",
            show_alert=True
        ); return
    field_map = {
        "home":"home_level","camp":"camp_level","hut":"hut_level",
        "woodyard":"woodyard_level","quarry":"quarry_level","iron_mine":"iron_mine_level"
    }
    await _upd(uid, wood=v["wood"]-cw, stone=v["stone"]-cs, iron=v["iron"]-ci,
               **{field_map[bld]: nxt})
    if bld == "home":
        await _upd(uid, max_citizens=v["max_citizens"]+20)
    await q.answer(f"✅ {bld} → Level {nxt}!", show_alert=True)
    await q.edit_message_text(
        q.message.text + f"\n\n✅ <b>{bld.title()}</b> upgraded to Lv{nxt}!",
        parse_mode="HTML"
    )


# ═══════════════════════════════════════════════════════
#  /walls — build/upgrade walls
# ═══════════════════════════════════════════════════════

async def walls_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id)
    walls = v.get("walls", {})

    if not args:
        text = f"🧱 <b>Walls — {mention(u)}</b>\n\n"
        for wtype, wdata in WALL_TYPES.items():
            if wtype in walls:
                w = walls[wtype]
                text += f"🧱 {wtype.title()} Wall Lv{w.get('level',1)} — HP: {w['hp']}/{w['max_hp']}\n"
            else:
                text += f"🔓 {wtype.title()} Wall — Not built\n"
        text += "\nBuild: /walls <wood/stone/iron>"
        for wtype, wdata in WALL_TYPES.items():
            if wtype == "wood":   text += f"\n  /walls wood  (🪵 {wdata['cost_wood']})"
            elif wtype == "stone": text += f"\n  /walls stone (🪨 {wdata['cost_stone']})"
            else:                  text += f"\n  /walls iron  (⚙️ {wdata['cost_iron']})"
        await update.message.reply_html(text); return

    wtype = args[0].lower()
    if wtype not in WALL_TYPES:
        await update.message.reply_html("❌ Wall types: wood / stone / iron"); return

    wdata = WALL_TYPES[wtype]
    existing = walls.get(wtype)
    if existing:
        lv = existing.get("level", 1); nxt = lv + 1
        cost_mult = nxt
        cw = wdata.get("cost_wood", 0) * cost_mult
        cs = wdata.get("cost_stone", 0) * cost_mult
        ci = wdata.get("cost_iron", 0) * cost_mult
        new_hp = wdata["hp"] * nxt
        if v["wood"] < cw or v["stone"] < cs or v["iron"] < ci:
            await update.message.reply_html(
                f"❌ Need: 🪵{cw} 🪨{cs} ⚙️{ci}"
            ); return
        walls[wtype] = {"level": nxt, "hp": new_hp, "max_hp": new_hp}
        action = f"upgraded to Lv{nxt}! HP: {new_hp}"
    else:
        cw = wdata.get("cost_wood", 0); cs = wdata.get("cost_stone", 0); ci = wdata.get("cost_iron", 0)
        if v["wood"] < cw or v["stone"] < cs or v["iron"] < ci:
            await update.message.reply_html(f"❌ Need: 🪵{cw} 🪨{cs} ⚙️{ci}"); return
        walls[wtype] = {"level": 1, "hp": wdata["hp"], "max_hp": wdata["hp"]}
        action = f"built! HP: {wdata['hp']}"

    await _upd(u.id, walls=walls, wood=v["wood"]-cw, stone=v["stone"]-cs, iron=v["iron"]-ci)
    await update.message.reply_html(
        f"🧱 <b>{wtype.title()} Wall</b> {action}!\n"
        f"🪵-{cw} 🪨-{cs} ⚙️-{ci}"
    )


# ═══════════════════════════════════════════════════════
#  /defense — build defense structures
# ═══════════════════════════════════════════════════════

async def defense_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id)
    defs = v.get("defense", {})
    d = await get_user(u.id)

    if not args:
        text = f"🛡️ <b>Defense — {mention(u)}</b>\n\n"
        for dtype, ddata in DEFENSE_TYPES.items():
            if dtype in defs:
                df = defs[dtype]
                text += f"🛡️ {dtype.replace('_',' ').title()} Lv{df.get('level',1)} — HP:{df['hp']}/{df['max_hp']} DMG:{df['damage']}\n"
            else:
                text += f"🔓 {dtype.replace('_',' ').title()} — Not built (Cost: {fmt(ddata['cost_coins'])})\n"
        text += f"\n💰 Your Balance: {fmt(d['balance'])}"
        text += "\nBuild: /defense <archer_tower/cannon>"
        await update.message.reply_html(text); return

    dtype = args[0].lower()
    if dtype not in DEFENSE_TYPES:
        await update.message.reply_html("❌ Types: archer_tower / cannon"); return

    ddata = DEFENSE_TYPES[dtype]
    existing = defs.get(dtype)
    if existing:
        lv = existing.get("level",1); nxt = lv+1
        cost = ddata["cost_coins"] * nxt
        new_hp = ddata["hp"] * nxt; new_dmg = ddata["damage"] + (nxt-1)*5
        if d["balance"] < cost:
            await update.message.reply_html(f"❌ Need {fmt(cost)} coins!"); return
        defs[dtype] = {"level":nxt,"hp":new_hp,"max_hp":new_hp,"damage":new_dmg}
        action = f"upgraded to Lv{nxt}! HP:{new_hp} DMG:{new_dmg}"
    else:
        cost = ddata["cost_coins"]
        if d["balance"] < cost:
            await update.message.reply_html(f"❌ Need {fmt(cost)} coins!"); return
        defs[dtype] = {"level":1,"hp":ddata["hp"],"max_hp":ddata["hp"],"damage":ddata["damage"]}
        action = f"built! HP:{ddata['hp']} DMG:{ddata['damage']}"

    await get_user.__self__ if False else None
    from utils.mongo_db import update_user as _upd_user
    await _upd_user(uid=u.id, **{})  # dummy
    from utils.mongo_db import get_db as _gdb
    await _gdb().users.update_one({"_id": u.id}, {"$inc": {"balance": -cost}})
    await _upd(u.id, defense=defs)
    await update.message.reply_html(
        f"🛡️ <b>{dtype.replace('_',' ').title()}</b> {action}!\n💰 -{fmt(cost)}"
    )


# ═══════════════════════════════════════════════════════
#  /train — train troops/workers
# ═══════════════════════════════════════════════════════

async def train_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id); d = await get_user(u.id)

    if not args:
        text = (
            f"⚔️ <b>Train — {mention(u)}</b>\n\n"
            f"Citizens: {v['max_citizens'] - len(v.get('troops',{})) - v.get('workers',0)}/{v['max_citizens']}\n"
            f"Workers: {v.get('workers',0)}\n\n"
            "Train troops:\n"
        )
        for ttype, tdata in TROOP_TYPES.items():
            text += f"/train {ttype} <n>  — {fmt(tdata['cost_coins'])} each\n"
        text += "\n/train workers <n>  — Speeds up construction"
        await update.message.reply_html(text); return

    if len(args) < 2:
        await update.message.reply_html("❌ Usage: /train <troop_type> <count>"); return

    ttype = args[0].lower()
    try: count = int(args[1])
    except: await update.message.reply_html("❌ Invalid count!"); return
    if count <= 0: await update.message.reply_html("❌ Count must be positive!"); return

    troops = v.get("troops", {})
    active_citizens = v["max_citizens"] - sum(troops.values()) - v.get("workers", 0)

    if ttype == "workers":
        if count > active_citizens:
            await update.message.reply_html(
                f"❌ Only {active_citizens} citizens available!"
            ); return
        await _upd(u.id, workers=v.get("workers",0)+count)
        await update.message.reply_html(
            f"👷 Trained <b>{count} workers</b>!\n"
            f"Workers speed up building construction."
        ); return

    if ttype not in TROOP_TYPES:
        await update.message.reply_html(
            f"❌ Unknown troop! Types: {', '.join(TROOP_TYPES.keys())}"
        ); return

    tdata = TROOP_TYPES[ttype]
    cost = tdata["cost_coins"] * count
    if d["balance"] < cost:
        await update.message.reply_html(
            f"❌ Need {fmt(cost)} coins! You have {fmt(d['balance'])}"
        ); return
    if count > active_citizens:
        await update.message.reply_html(
            f"❌ Only {active_citizens} citizens available to train!"
        ); return

    # Max camp check
    total_troops = sum(troops.values()) + count
    max_troops = v["camp_level"] * 20
    if total_troops > max_troops:
        await update.message.reply_html(
            f"❌ Camp can only hold {max_troops} troops! Upgrade camp."
        ); return

    troops[ttype] = troops.get(ttype, 0) + count
    from utils.mongo_db import get_db as _gdb2
    await _gdb2().users.update_one({"_id": u.id}, {"$inc": {"balance": -cost}})
    await _upd(u.id, troops=troops)

    await update.message.reply_html(
        f"⚔️ Trained <b>{count} {ttype}</b>!\n"
        f"HP: {tdata['hp']} each | DMG: {tdata['damage']}/hit\n"
        f"💰 -{fmt(cost)}"
    )


# ═══════════════════════════════════════════════════════
#  /troops — show your army
# ═══════════════════════════════════════════════════════

async def troops_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id)
    troops = v.get("troops", {})

    if not troops:
        await update.message.reply_html(
            f"⚔️ <b>Troops — {mention(u)}</b>\n\n"
            f"No troops! Train them: /train warriors 10"
        ); return

    text = f"⚔️ <b>Your Army — {mention(u)}</b>\n\n"
    total_hp = 0; total_dmg = 0
    for ttype, count in troops.items():
        if count <= 0: continue
        td = TROOP_TYPES.get(ttype, {})
        hp = td.get("hp", 50) * count
        dmg = td.get("damage", 15) * count
        total_hp += hp; total_dmg += dmg
        text += f"⚔️ {ttype.title()}: {count} units | HP:{hp} DMG:{dmg}/hit\n"

    text += (
        f"\n💪 Total Army HP: <b>{total_hp}</b>\n"
        f"⚔️ Total Damage/hit: <b>{total_dmg}</b>\n\n"
        f"👷 Workers: {v.get('workers',0)}\n"
        f"👥 Free Citizens: {v['max_citizens'] - sum(troops.values()) - v.get('workers',0)}"
    )
    await update.message.reply_html(text)


# ═══════════════════════════════════════════════════════
#  /kingdom — spy on target's kingdom
# ═══════════════════════════════════════════════════════

async def kingdom_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(
            "🏰 Usage: Reply to a user + /kingdom\n"
            "Shows their resources and defenses for attack planning!"
        ); return

    target = msg.reply_to_message.from_user
    if target.id == u.id:
        await msg.reply_html("😂 Use /vault to check your own kingdom!"); return

    await ensure_user(target.id, target.username or "", target.full_name)
    tv = await _get_village(target.id)
    now = ts()

    protected = tv.get("protected_until", 0) > now
    walls = tv.get("walls", {})
    defs  = tv.get("defense", {})

    # Loot calculation (50% of storage)
    loot_wood  = tv["wood"]  // 2
    loot_stone = tv["stone"] // 2
    loot_iron  = tv["iron"]  // 2

    wall_text = "\n".join(
        f"  🧱 {wt.title()} Lv{w['level']} HP:{w['hp']}"
        for wt, w in walls.items()
    ) or "  No walls"

    def_text = "\n".join(
        f"  🛡️ {dt.replace('_',' ').title()} Lv{d['level']} HP:{d['hp']} DMG:{d['damage']}"
        for dt, d in defs.items()
    ) or "  No defense"

    await msg.reply_html(
        f"🔍 <b>Kingdom Report — {mention(target)}</b>\n\n"
        f"🏰 Level: <b>{tv['kingdom_level']}</b>  |  Stage: <b>{tv['stage'].title()}</b>\n"
        f"🛡️ Protection: <b>{'✅ YES — cannot attack!' if protected else '❌ None'}</b>\n\n"
        f"💎 <b>Available Loot (50%):</b>\n"
        f"  🪵 {loot_wood} Wood\n"
        f"  🪨 {loot_stone} Stone\n"
        f"  ⚙️ {loot_iron} Iron\n\n"
        f"🧱 <b>Walls:</b>\n{wall_text}\n\n"
        f"🛡️ <b>Defense:</b>\n{def_text}\n\n"
        f"⚔️ Attack: /attack warriors <n> (reply to them)"
    )


# ═══════════════════════════════════════════════════════
#  /spy — check user's available loot (quick)
# ═══════════════════════════════════════════════════════

async def spy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("🔍 Reply to someone to spy on them!"); return
    target = msg.reply_to_message.from_user
    await ensure_user(target.id, target.username or "", target.full_name)
    tv = await _get_village(target.id)
    now = ts(); prot = tv.get("protected_until", 0) > now
    await msg.reply_html(
        f"🔍 <b>Spy Report — {mention(target)}</b>\n\n"
        f"🪵 Wood: {tv['wood']}  🪨 Stone: {tv['stone']}  ⚙️ Iron: {tv['iron']}\n"
        f"🪙 Treasury: {fmt(tv['treasury'])}\n"
        f"🏛️ Vault: {fmt(tv['vault'])}\n\n"
        f"{'🛡️ PROTECTED — do not attack!' if prot else '🎯 No protection — safe to attack!'}"
    )


# ═══════════════════════════════════════════════════════
#  /attack — MAIN WAR COMMAND
# ═══════════════════════════════════════════════════════

async def attack_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user; now = ts()
    await ensure_user(u.id, u.username or "", u.full_name)

    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html(
            "⚔️ <b>Attack!</b>\n\n"
            "Usage: Reply to target + /attack <troop_type> <count>\n"
            "Example: /attack warriors 20\n\n"
            "Scout first with /kingdom"
        ); return

    target = msg.reply_to_message.from_user
    if target.id == u.id:
        await msg.reply_html("😂 Can't attack yourself!"); return
    if target.is_bot:
        await msg.reply_html("🤖 Can't attack a bot!"); return

    args = context.args
    if len(args) < 2:
        await msg.reply_html("❌ Usage: /attack <troop_type> <count>"); return

    ttype = args[0].lower()
    try: count = int(args[1])
    except: await msg.reply_html("❌ Invalid count!"); return
    if count <= 0: await msg.reply_html("❌ Count must be positive!"); return

    # Attacker village
    av = await _get_village(u.id)
    if ttype not in av.get("troops", {}):
        await msg.reply_html(f"❌ You don't have {ttype}! Train them: /train {ttype} <n>"); return
    if av["troops"].get(ttype, 0) < count:
        await msg.reply_html(
            f"❌ You only have {av['troops'].get(ttype,0)} {ttype}!"
        ); return

    # Attack cooldown (5 min)
    if now - av.get("last_attack", 0) < 300:
        rem = 300 - (now - av.get("last_attack", 0))
        await msg.reply_html(f"⏳ Attack cooldown: <b>{rem//60}m {rem%60}s</b>"); return

    # Defender village
    await ensure_user(target.id, target.username or "", target.full_name)
    dv = await _get_village(target.id)

    # Protection check
    if dv.get("protected_until", 0) > now:
        rem = dv["protected_until"] - now
        await msg.reply_html(
            f"🛡️ {mention(target)} is protected for <b>{rem//3600}h {(rem%3600)//60}m</b>!"
        ); return

    # ── War simulation ────────────────────────────────────────────────
    td = TROOP_TYPES.get(ttype, {"hp": 50, "damage": 15})
    total_troop_hp  = td["hp"]     * count
    total_troop_dmg = td["damage"] * count

    # Defender total HP and damage
    walls    = dv.get("walls", {})
    defs     = dv.get("defense", {})
    total_def_hp  = sum(w["hp"] for w in walls.values()) + sum(d["hp"] for d in defs.values())
    total_def_dmg = sum(d["damage"] for d in defs.values())
    if not total_def_hp: total_def_hp = 50  # bare minimum

    # Simple simulation: who survives?
    # Troops deal damage to defense, defense damages troops simultaneously
    rounds = 0
    atk_hp = total_troop_hp
    def_hp = total_def_hp
    while atk_hp > 0 and def_hp > 0 and rounds < 100:
        def_hp -= total_troop_dmg
        atk_hp -= total_def_dmg
        rounds += 1

    attacker_wins = atk_hp > 0

    # Update attacker troops (lose some regardless)
    troops_lost = min(count, max(1, int(count * (total_def_dmg / max(total_troop_hp, 1)))))
    new_troops = av["troops"].copy()
    new_troops[ttype] = max(0, new_troops[ttype] - troops_lost)
    await _upd(u.id, troops=new_troops, last_attack=now)

    if attacker_wins:
        # Loot 50%
        loot_w = dv["wood"]  // 2
        loot_s = dv["stone"] // 2
        loot_i = dv["iron"]  // 2

        # Transfer loot
        await _upd(u.id,
                   wood=av["wood"]+loot_w,
                   stone=av["stone"]+loot_s,
                   iron=av["iron"]+loot_i)
        await _upd(target.id,
                   wood=dv["wood"]-loot_w,
                   stone=dv["stone"]-loot_s,
                   iron=dv["iron"]-loot_i,
                   protected_until=now+3600)  # 1hr shield after being raided

        result = (
            f"⚔️ <b>VICTORY!</b> 🏆\n\n"
            f"👑 {mention(u)} defeated {mention(target)}!\n\n"
            f"💎 <b>Loot:</b>\n"
            f"🪵 +{loot_w} Wood\n"
            f"🪨 +{loot_s} Stone\n"
            f"⚙️ +{loot_i} Iron\n\n"
            f"💀 Troops lost: {troops_lost} {ttype}\n"
            f"🛡️ {mention(target)} gets 1hr protection"
        )
        gif = GIFS.get("attack_win")
        try:
            await context.bot.send_animation(
                msg.chat_id, animation=gif, caption=result, parse_mode="HTML"
            )
        except Exception:
            await msg.reply_html(result)

        # Notify defender
        try:
            await context.bot.send_message(
                target.id,
                f"🚨 <b>You were attacked!</b>\n\n"
                f"⚔️ {mention(u)} raided your kingdom!\n"
                f"💸 Lost: 🪵{loot_w} 🪨{loot_s} ⚙️{loot_i}\n"
                f"🛡️ You have 1 hour of protection now.",
                parse_mode="HTML"
            )
        except Exception:
            pass
    else:
        result = (
            f"⚔️ <b>DEFEAT!</b> 😢\n\n"
            f"{mention(u)} attacked {mention(target)} but failed!\n\n"
            f"💀 All {troops_lost} {ttype} lost\n"
            f"💪 {mention(target)}'s defenses held!\n\n"
            f"Scout with /kingdom before attacking"
        )
        await msg.reply_html(result)


# ═══════════════════════════════════════════════════════
#  /emperors — top vault holders
# ═══════════════════════════════════════════════════════

async def emperors_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pipeline = [
        {"$addFields": {"total": {"$add": ["$vault", "$treasury"]}}},
        {"$sort": {"total": -1}},
        {"$limit": 10}
    ]
    rows = await get_db().village.aggregate(pipeline).to_list(10)
    medals = ["🥇","🥈","🥉","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟"]
    text = "👑 <b>Top 10 Emperors</b>\n\n"
    for i, r in enumerate(rows):
        try:
            u = await context.bot.get_chat(r["_id"])
            name = u.first_name
        except Exception:
            name = str(r["_id"])
        text += f"{medals[i]} <b>{name}</b> — {fmt(r['total'])}\n"
    if not rows:
        text += "No emperors yet! Start building: /guide"
    await update.message.reply_html(text)


# ═══════════════════════════════════════════════════════
#  /settle — move coins between vault and treasury
# ═══════════════════════════════════════════════════════

async def settle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id)
    if not args or len(args) < 2:
        await update.message.reply_html(
            f"🏦 <b>Settle — {mention(u)}</b>\n\n"
            f"🪙 Treasury: {fmt(v['treasury'])}\n"
            f"🏛️ Vault: {fmt(v['vault'])}\n\n"
            "/settle vault <amount> — Treasury→Vault\n"
            "/settle treasury <amount> — Vault→Treasury"
        ); return
    direction = args[0].lower()
    try: amt = int(args[1])
    except: await update.message.reply_html("❌ Invalid amount!"); return
    if amt <= 0: await update.message.reply_html("❌ Amount must be positive!"); return
    if direction == "vault":
        if v["treasury"] < amt: await update.message.reply_html("❌ Not enough in treasury!"); return
        await _upd(u.id, treasury=v["treasury"]-amt, vault=v["vault"]+amt)
        await update.message.reply_html(f"✅ Moved {fmt(amt)} → Vault! Total: {fmt(v['vault']+amt)}")
    elif direction == "treasury":
        if v["vault"] < amt: await update.message.reply_html("❌ Not enough in vault!"); return
        await _upd(u.id, vault=v["vault"]-amt, treasury=v["treasury"]+amt)
        await update.message.reply_html(f"✅ Moved {fmt(amt)} → Treasury!")
    else:
        await update.message.reply_html("❌ Use: /settle vault/treasury <amount>")


# ═══════════════════════════════════════════════════════
#  /convert — resources to coins
# ═══════════════════════════════════════════════════════

async def convert_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; args = context.args
    await ensure_user(u.id, u.username or "", u.full_name)
    v = await _get_village(u.id)
    RATES = {"wood": 5, "stone": 8, "iron": 12}
    if not args or len(args) < 2:
        await update.message.reply_html(
            f"💱 <b>Convert Resources → Coins</b>\n\n"
            f"🪵 Wood: {v['wood']}  (rate: {RATES['wood']} coins each)\n"
            f"🪨 Stone: {v['stone']}  (rate: {RATES['stone']} coins each)\n"
            f"⚙️ Iron: {v['iron']}  (rate: {RATES['iron']} coins each)\n\n"
            "Usage: /convert <wood/stone/iron> <amount>\n"
            "Note: Cannot convert back to resources!"
        ); return
    res = args[0].lower()
    if res not in RATES: await update.message.reply_html("❌ Use: wood / stone / iron"); return
    try: amt = int(args[1])
    except: await update.message.reply_html("❌ Invalid amount!"); return
    stock = {"wood":v["wood"],"stone":v["stone"],"iron":v["iron"]}[res]
    if stock < amt: await update.message.reply_html(f"❌ Only have {stock} {res}!"); return
    coins = amt * RATES[res]
    await _upd(u.id, **{res: stock-amt}, vault=v["vault"]+coins)
    await update.message.reply_html(
        f"💱 Converted {amt} {res} → <b>{fmt(coins)}</b> (added to Vault)!"
    )


# ═══════════════════════════════════════════════════════
#  /guide — village game guide
# ═══════════════════════════════════════════════════════

async def guide_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "📖 <b>Iota Village Guide</b>\n\n"
        "🏰 <b>Goal:</b> Build your empire from Village → Town → City → Empire!\n\n"
        "📋 <b>Daily Routine:</b>\n"
        "1️⃣ /daily — Free resources + coins\n"
        "2️⃣ /collect — Harvest mine output\n"
        "3️⃣ /build — Upgrade buildings\n"
        "4️⃣ /train — Train your army\n"
        "5️⃣ /attack — Raid other players!\n\n"
        "⚔️ <b>War System:</b>\n"
        "• /spy — Quick scout of target\n"
        "• /kingdom — Detailed attack plan\n"
        "• /attack warriors 20 — Launch raid\n\n"
        "🏦 <b>Economy:</b>\n"
        "• /settle vault 1000 — Move to vault\n"
        "• /convert wood 200 — Resources → Coins\n"
        "• /vault — Check your rank\n\n"
        "👑 /emperors — Global leaderboard\n\n"
        "💡 <b>Tips:</b>\n"
        "• Upgrade Home first (more citizens!)\n"
        "• Always have walls before attacking\n"
        "• Scout with /kingdom before attack\n"
        "• Keep coins in vault for leaderboard"
    )
