"""Iota Bot - MongoDB Async Database Layer (motor)"""
import time
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI, DB_NAME

_client = None
_db = None

def get_db():
    global _client, _db
    if _db is None:
        _client = AsyncIOMotorClient(MONGO_URI, serverSelectionTimeoutMS=8000)
        _db = _client[DB_NAME]
    return _db

def now(): return int(time.time())

# ── Users ────────────────────────────────────────────────────────────

async def ensure_user(uid, username="", full_name=""):
    db = get_db()
    u = await db.users.find_one({"_id": uid})
    if not u:
        u = {"_id":uid,"username":username,"full_name":full_name,
             "balance":0,"gems":0,"is_premium":False,"premium_emoji":"",
             "last_daily":0,"kills":0,"daily_kills":0,"last_kill_reset":0,
             "robs":0,"daily_robs":0,"last_rob_reset":0,"xp":0,"level":1,
             "protected_until":0,"dead_until":0,"wallet":0,"is_banned":False,
             "free_gem_claimed":False,"custom_title":"","created_at":now(),
             "name_history":[],"username_history":[]}
        await db.users.insert_one(u)
    else:
        upd = {}
        if username and u.get("username") != username:
            upd["username"] = username
            hist = u.get("username_history", [])
            if username not in hist:
                hist = [username] + hist[:9]
                upd["username_history"] = hist
        if full_name and u.get("full_name") != full_name:
            upd["full_name"] = full_name
            hist = u.get("name_history", [])
            if full_name not in hist:
                hist = [full_name] + hist[:9]
                upd["name_history"] = hist
        if upd:
            await db.users.update_one({"_id":uid},{"$set":upd})
            u.update(upd)
    return u

async def get_user(uid):
    u = await get_db().users.find_one({"_id":uid})
    return u or await ensure_user(uid)

async def update_user(uid, **kw):
    if kw: await get_db().users.update_one({"_id":uid},{"$set":kw})

async def add_balance(uid, amt):
    await get_db().users.update_one({"_id":uid},{"$inc":{"balance":amt}})

async def get_top_rich(n=10):
    return await get_db().users.find(
        {"is_banned":{"$ne":True}},sort=[("balance",-1)],limit=n
    ).to_list(n)

async def get_top_kill(n=10):
    return await get_db().users.find(
        {"is_banned":{"$ne":True}},sort=[("kills",-1)],limit=n
    ).to_list(n)

async def get_user_rank(uid):
    u = await get_user(uid)
    c = await get_db().users.count_documents(
        {"balance":{"$gt":u["balance"]},"is_banned":{"$ne":True}}
    )
    return c + 1

async def total_users():
    return await get_db().users.count_documents({})

# ── Card rank ────────────────────────────────────────────────────────

async def ensure_card_rank(uid):
    db = get_db()
    cr = await db.card_rank.find_one({"_id":uid})
    if not cr:
        cr = {"_id":uid,"wins":0,"losses":0,"won_amount":0,"lost_amount":0,"streak":0,"best_streak":0}
        await db.card_rank.insert_one(cr)
    return cr

async def get_card_rank(uid):
    cr = await get_db().card_rank.find_one({"_id":uid})
    return cr or await ensure_card_rank(uid)

async def update_card_rank(uid, **kw):
    await get_db().card_rank.update_one({"_id":uid},{"$set":kw},upsert=True)

async def get_card_leaders(n=10):
    return await get_db().card_rank.find(sort=[("won_amount",-1)],limit=n).to_list(n)

async def get_card_rank_position(uid):
    cr = await get_card_rank(uid)
    c = await get_db().card_rank.count_documents({"won_amount":{"$gt":cr["won_amount"]}})
    t = await get_db().card_rank.count_documents({})
    return c+1, t

# ── Group economy ────────────────────────────────────────────────────

async def ensure_guser(uid, cid):
    key = f"{uid}_{cid}"
    db = get_db()
    gu = await db.group_economy.find_one({"_id":key})
    if not gu:
        gu = {"_id":key,"user_id":uid,"chat_id":cid,"balance":0,"kills":0,"robs":0,"protected_until":0,"dead_until":0}
        await db.group_economy.insert_one(gu)
    return gu

async def get_guser(uid, cid):
    key = f"{uid}_{cid}"
    gu = await get_db().group_economy.find_one({"_id":key})
    return gu or await ensure_guser(uid, cid)

async def update_guser(uid, cid, **kw):
    if kw: await get_db().group_economy.update_one({"_id":f"{uid}_{cid}"},{"$set":kw},upsert=True)

async def get_granks(cid, n=10):
    return await get_db().group_economy.find(
        {"chat_id":cid},sort=[("balance",-1)],limit=n
    ).to_list(n)

# ── Warnings ─────────────────────────────────────────────────────────

async def add_warning(uid, cid, reason, by):
    await get_db().warnings.insert_one({"user_id":uid,"chat_id":cid,"reason":reason,"warned_by":by,"warned_at":now()})

async def get_warnings(uid, cid):
    return await get_db().warnings.find({"user_id":uid,"chat_id":cid},sort=[("warned_at",-1)]).to_list(50)

async def count_warnings(uid, cid):
    return await get_db().warnings.count_documents({"user_id":uid,"chat_id":cid})

async def remove_last_warning(uid, cid):
    w = await get_db().warnings.find_one({"user_id":uid,"chat_id":cid},sort=[("warned_at",-1)])
    if w:
        await get_db().warnings.delete_one({"_id":w["_id"]}); return True
    return False

# ── Items ─────────────────────────────────────────────────────────────

async def add_item(uid, name, qty=1):
    ex = await get_db().items.find_one({"owner_id":uid,"item_name":name})
    if ex:
        await get_db().items.update_one({"owner_id":uid,"item_name":name},{"$inc":{"quantity":qty}})
    else:
        await get_db().items.insert_one({"owner_id":uid,"item_name":name,"quantity":qty})

async def get_items(uid):
    return await get_db().items.find({"owner_id":uid}).to_list(100)

async def remove_item(uid, name, qty=1):
    it = await get_db().items.find_one({"owner_id":uid,"item_name":name})
    if not it or it["quantity"]<qty: return False
    if it["quantity"]==qty:
        await get_db().items.delete_one({"_id":it["_id"]})
    else:
        await get_db().items.update_one({"_id":it["_id"]},{"$inc":{"quantity":-qty}})
    return True

# ── Village ───────────────────────────────────────────────────────────

async def ensure_village(uid):
    db = get_db()
    v = await db.village.find_one({"_id":uid})
    if not v:
        v = {"_id":uid,"wood":0,"stone":0,"iron":0,"citizens":50,"max_citizens":50,
             "workers":0,"troops":{},"home_level":1,"camp_level":1,"hut_level":1,
             "woodyard_level":1,"quarry_level":1,"iron_mine_level":1,"walls":{},
             "defense":{},"storage_cap":2000,"treasury":0,"vault":0,
             "last_mine":now(),"last_tax":now(),"last_attack":0,
             "stage":"village","kingdom_level":1,"protected_until":0}
        await db.village.insert_one(v)
    return v

async def get_village(uid):
    v = await get_db().village.find_one({"_id":uid})
    return v or await ensure_village(uid)

async def update_village(uid, **kw):
    if kw: await get_db().village.update_one({"_id":uid},{"$set":kw},upsert=True)

async def get_empire_top(n=10):
    pipeline = [{"$addFields":{"total":{"$add":["$vault","$treasury"]}}},
                {"$sort":{"total":-1}},{"$limit":n}]
    return await get_db().village.aggregate(pipeline).to_list(n)

# ── Coupons ───────────────────────────────────────────────────────────

async def use_global_coupon(uid, code):
    try:
        await get_db().global_used_coupons.insert_one({"user_id":uid,"coupon":code}); return True
    except Exception: return False

async def get_group_coupon(cid):
    return await get_db().group_coupons.find_one({"_id":cid})

async def set_group_coupon(cid, code, amount, by):
    await get_db().group_coupons.update_one({"_id":cid},
        {"$set":{"code":code,"amount":amount,"created_by":by,"created_at":now()}},upsert=True)

async def delete_group_coupon(cid):
    await get_db().group_coupons.delete_one({"_id":cid})
    await get_db().group_coupon_used.delete_many({"chat_id":cid})

async def use_group_coupon(uid, cid):
    try:
        await get_db().group_coupon_used.insert_one({"user_id":uid,"chat_id":cid}); return True
    except Exception: return False

# ── Valentines ────────────────────────────────────────────────────────

async def get_valentine(uid):
    return await get_db().valentines.find_one({"_id":uid})

async def set_valentine(uid, gender, c1, c2, c3):
    await get_db().valentines.update_one({"_id":uid},
        {"$set":{"gender":gender,"choice1":c1,"choice2":c2,"choice3":c3}},upsert=True)

async def delete_valentine(uid):
    await get_db().valentines.delete_one({"_id":uid})

async def count_valentines():
    t = await get_db().valentines.count_documents({})
    m = await get_db().valentines.count_documents({"gender":"male"})
    f = await get_db().valentines.count_documents({"gender":"female"})
    return {"t":t,"m":m,"f":f}

# ── Card games (in-memory handled in games.py) ────────────────────────

async def get_card_game_db(gid):
    return await get_db().card_games.find_one({"_id":gid})

async def save_card_game(gid, data):
    await get_db().card_games.update_one({"_id":gid},{"$set":data},upsert=True)

async def delete_card_game_db(gid):
    await get_db().card_games.delete_one({"_id":gid})

# ── Admin promotions ──────────────────────────────────────────────────

async def track_promotion(uid, cid, by):
    await get_db().admin_promotions.update_one({"_id":f"{uid}_{cid}"},
        {"$set":{"user_id":uid,"chat_id":cid,"promoted_by":by}},upsert=True)

async def get_bot_promotions(cid):
    return await get_db().admin_promotions.find({"chat_id":cid}).to_list(100)

async def remove_promotion(uid, cid):
    await get_db().admin_promotions.delete_one({"_id":f"{uid}_{cid}"})

# ── Welcome ───────────────────────────────────────────────────────────

async def get_welcome_settings(cid):
    ws = await get_db().welcome_settings.find_one({"_id":cid})
    return ws or {"_id":cid,"enabled":True,"custom_msg":"","send_gif":True}

async def set_welcome_settings(cid, **kw):
    await get_db().welcome_settings.update_one({"_id":cid},{"$set":kw},upsert=True)

# ── Group protection ──────────────────────────────────────────────────

async def get_prot(cid):
    p = await get_db().group_protection.find_one({"_id":cid})
    if not p:
        p = {"_id":cid,"enabled":True,"anti_spam":True,"anti_link":True,
             "anti_arabic":False,"anti_forward":False,"anti_bot":True,
             "anti_flood":True,"flood_limit":5,"flood_window":5,
             "anti_raid":True,"raid_threshold":10,"raid_window":30,
             "profanity_filter":False,"log_channel":0}
        await get_db().group_protection.insert_one(p)
    return p

async def update_prot(cid, **kw):
    await get_db().group_protection.update_one({"_id":cid},{"$set":kw},upsert=True)

# ── Reports ───────────────────────────────────────────────────────────

async def add_report(cid, reporter, reported, reason, msg_text=""):
    await get_db().reports.insert_one({"chat_id":cid,"reporter_id":reporter,
        "reported_id":reported,"reason":reason,"msg_text":msg_text,"status":"pending","created_at":now()})

async def get_reports(cid, status="pending"):
    return await get_db().reports.find({"chat_id":cid,"status":status},sort=[("created_at",-1)],limit=20).to_list(20)

async def get_report_count(cid):
    return await get_db().reports.count_documents({"chat_id":cid,"status":"pending"})

# ── Bad words ─────────────────────────────────────────────────────────

async def get_bad_words(cid):
    doc = await get_db().bad_words.find_one({"_id":cid})
    return doc.get("words",[]) if doc else []

async def add_bad_word(cid, word):
    await get_db().bad_words.update_one({"_id":cid},{"$addToSet":{"words":word.lower()}},upsert=True)

async def remove_bad_word(cid, word):
    await get_db().bad_words.update_one({"_id":cid},{"$pull":{"words":word.lower()}})

# ── Misc ──────────────────────────────────────────────────────────────

async def get_sticker_pack(uid):
    return await get_db().sticker_packs.find_one({"_id":uid})

async def set_sticker_pack(uid, pack_name, pack_title):
    await get_db().sticker_packs.update_one({"_id":uid},
        {"$set":{"pack_name":pack_name,"pack_title":pack_title}},upsert=True)

async def set_top_group(rank, uid, name, link):
    await get_db().top_groups.update_one({"_id":rank},
        {"$set":{"user_id":uid,"group_name":name,"group_link":link}},upsert=True)

async def get_top_groups():
    return await get_db().top_groups.find(sort=[("_id",1)]).to_list(5)

async def is_gaming_open(cid):
    doc = await get_db().gaming_status.find_one({"_id":cid})
    return doc.get("is_open",True) if doc else True

async def set_gaming_status(cid, status):
    await get_db().gaming_status.update_one({"_id":cid},{"$set":{"is_open":status}},upsert=True)

# ── Stars payments tracking ────────────────────────────────────────────

async def log_stars_payment(uid, payload, stars, full_name=""):
    await get_db().stars_payments.insert_one({
        "user_id":uid,"payload":payload,"stars":stars,
        "full_name":full_name,"created_at":now()
    })

async def get_stars_total():
    pipeline = [{"$group":{"_id":None,"total":{"$sum":"$stars"}}}]
    r = await get_db().stars_payments.aggregate(pipeline).to_list(1)
    return r[0]["total"] if r else 0

# ── Promoter system ───────────────────────────────────────────────────

async def add_promoter(uid, ref_code):
    await get_db().promoters.update_one({"_id":uid},
        {"$set":{"ref_code":ref_code,"referred":[],"earnings":0,"created_at":now()}},upsert=True)

async def get_promoter(uid):
    return await get_db().promoters.find_one({"_id":uid})

async def get_promoter_by_code(code):
    return await get_db().promoters.find_one({"ref_code":code})

async def add_referral(promoter_uid, referred_uid, reward):
    await get_db().promoters.update_one({"_id":promoter_uid},{
        "$addToSet":{"referred":referred_uid},
        "$inc":{"earnings":reward}
    })

# ── Last seen ─────────────────────────────────────────────────────────

async def update_last_seen(uid, username="", full_name=""):
    await get_db().last_seen.update_one({"_id":uid},{
        "$set":{"username":username,"full_name":full_name,"last_seen":now()}
    },upsert=True)

async def get_last_seen(uid):
    return await get_db().last_seen.find_one({"_id":uid})

# ── Indexes ───────────────────────────────────────────────────────────

async def create_indexes():
    db = get_db()
    await db.users.create_index([("balance",-1)])
    await db.users.create_index([("kills",-1)])
    await db.group_economy.create_index([("chat_id",1),("balance",-1)])
    await db.warnings.create_index([("user_id",1),("chat_id",1)])
    await db.card_rank.create_index([("won_amount",-1)])
    await db.reports.create_index([("chat_id",1),("status",1)])
    await db.last_seen.create_index([("last_seen",-1)])
    try:
        await db.global_used_coupons.create_index([("user_id",1),("coupon",1)],unique=True)
        await db.group_coupon_used.create_index([("user_id",1),("chat_id",1)],unique=True)
        await db.stars_payments.create_index([("user_id",1)])
    except Exception: pass
    print("✅ MongoDB indexes created")
