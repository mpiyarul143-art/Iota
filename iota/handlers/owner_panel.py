"""Iota Owner Panel — full control"""
import asyncio, time
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from utils.mongo_db import (get_db, ensure_user, get_user, update_user,
                             add_balance, total_users, log_stars_payment,
                             get_stars_total)
from utils.helpers import mention, fmt
from utils.fonts import sc
from utils.ai_provider import (get_all_models, get_current_models,
                                set_model, save_model_config_db)
from config import OWNER_ID, GLOBAL_COUPONS

def _own(uid): return uid == OWNER_ID

async def owner_panel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _own(update.effective_user.id):
        await update.message.reply_html("❌ Owner only!"); return
    cfg = get_current_models()
    db = get_db()
    tu = await total_users()
    pu = await db.users.count_documents({"is_premium": True})
    stars = await get_stars_total()
    await update.message.reply_html(
        f"👑 <b>Owner Panel — Iota Bot</b>\n\n"
        f"👥 Users: <b>{tu}</b>  |  💓 Premium: <b>{pu}</b>\n"
        f"⭐ Total Stars earned: <b>{stars}</b>\n\n"
        f"🤖 <b>AI Models:</b>\n"
        f"Free: <code>{cfg['free_model']}</code>\n"
        f"Premium: <code>{cfg['premium_model']}</code>\n\n"
        f"<b>Economy:</b>\n"
        f"/addcoins /removecoins /addgems\n"
        f"/addpremium /removepremium /addcoupon\n\n"
        f"<b>Users:</b>\n"
        f"/banuser /unbanuser /broadcast\n"
        f"/announce all|group_id msg\n\n"
        f"<b>AI Models:</b>\n"
        f"/setmodel free|premium <model>\n"
        f"/listmodels\n\n"
        f"<b>Stats:</b>\n"
        f"/botstats /starsstats\n\n"
        f"<b>Scan/Hidden:</b>\n"
        f"/scan <user_id> — Full user scan\n"
        f"/resetuser <user_id> — Reset all data\n"
        f"/giveall <amount> — Give coins to all\n"
        f"/maintenance on|off"
    )

async def addcoins_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    args = context.args
    if len(args)<2: await update.message.reply_html("Usage: /addcoins <uid> <amt>"); return
    try: uid=int(args[0]); amt=int(args[1])
    except: await update.message.reply_html("❌ Invalid!"); return
    await ensure_user(uid); await add_balance(uid, amt)
    d = await get_user(uid)
    await update.message.reply_html(f"✅ Added {fmt(amt)} to <code>{uid}</code>\nNew: {fmt(d['balance'])}")

async def removecoins_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    args = context.args
    if len(args)<2: await update.message.reply_html("Usage: /removecoins <uid> <amt>"); return
    try: uid=int(args[0]); amt=int(args[1])
    except: await update.message.reply_html("❌"); return
    await ensure_user(uid); d=await get_user(uid)
    new=max(0,d["balance"]-amt); await update_user(uid, balance=new)
    await update.message.reply_html(f"✅ Removed {fmt(amt)} from <code>{uid}</code>\nNew: {fmt(new)}")

async def addgems_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    args = context.args
    if len(args)<2: await update.message.reply_html("Usage: /addgems <uid> <amt>"); return
    try: uid=int(args[0]); amt=int(args[1])
    except: await update.message.reply_html("❌"); return
    await ensure_user(uid); d=await get_user(uid)
    await update_user(uid, gems=d.get("gems",0)+amt)
    await update.message.reply_html(f"✅ Added {amt} 💎 to <code>{uid}</code>")

async def addpremium_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    args = context.args
    if not args: await update.message.reply_html("Usage: /addpremium <uid> [days=90]"); return
    try: uid=int(args[0]); days=int(args[1]) if len(args)>1 else 90
    except: await update.message.reply_html("❌"); return
    await ensure_user(uid)
    now=int(time.time()); until=now+days*86400
    await update_user(uid, is_premium=True, premium_until=until)
    exp=time.strftime('%d %b %Y', time.localtime(until))
    await update.message.reply_html(f"💓 <code>{uid}</code> Premium until <b>{exp}</b>!")

async def removepremium_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    if not context.args: await update.message.reply_html("Usage: /removepremium <uid>"); return
    try: uid=int(context.args[0])
    except: await update.message.reply_html("❌"); return
    await update_user(uid, is_premium=False, premium_until=0)
    await update.message.reply_html(f"❌ Premium removed from <code>{uid}</code>")

async def addcoupon_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    args=context.args
    if len(args)<2: await update.message.reply_html("Usage: /addcoupon <code> <amt>"); return
    code=args[0].lower()
    try: amt=int(args[1])
    except: await update.message.reply_html("❌"); return
    GLOBAL_COUPONS[code]=amt
    await update.message.reply_html(f"🎟️ Coupon <b>{code}</b> = {fmt(amt)} added!")

async def ban_user_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    if not context.args: await update.message.reply_html("Usage: /banuser <uid>"); return
    try: uid=int(context.args[0])
    except: await update.message.reply_html("❌"); return
    await ensure_user(uid); await update_user(uid, is_banned=True, balance=0, is_premium=False)
    await update.message.reply_html(f"🔨 <code>{uid}</code> banned!")

async def unban_user_cmd_owner(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    if not context.args: await update.message.reply_html("Usage: /unbanuser <uid>"); return
    try: uid=int(context.args[0])
    except: await update.message.reply_html("❌"); return
    await update_user(uid, is_banned=False)
    await update.message.reply_html(f"✅ <code>{uid}</code> unbanned!")

async def broadcast_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    if not context.args: await update.message.reply_html("Usage: /broadcast <msg>"); return
    text=" ".join(context.args); db=get_db()
    users=await db.users.find({},{"_id":1}).to_list(100000)
    total=len(users); sent=0; failed=0
    status=await update.message.reply_html(f"📢 Sending to {total} users...")
    for u in users:
        try:
            await context.bot.send_message(u["_id"],
                f"📢 <b>Announcement — Iota Bot</b>\n\n{text}", parse_mode="HTML")
            sent+=1; await asyncio.sleep(0.05)
        except: failed+=1
    await status.edit_text(
        f"📢 Done!\n✅ Sent: {sent}\n❌ Failed: {failed}", parse_mode="HTML")

async def announce_cmd(update, context):
    """Send message to all groups or a specific group."""
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    args=context.args
    if len(args)<2:
        await update.message.reply_html(
            "📢 <b>Announce</b>\n\n"
            "/announce all <msg> — All groups\n"
            "/announce <group_id> <msg> — Specific group\n\n"
            "Example:\n"
            "/announce all 🎉 New update launched!\n\n"
            "For styled announce:\n"
            "/announce all 𝙁𝙍𝙄𝙀𝙉𝘿𝙎 𝙐𝙋𝙓\nᴊᴏɪɴ ᴏᴜʀ ɢʀᴏᴜᴘ..."
        ); return
    target=args[0].lower(); message=" ".join(args[1:])
    full_msg=f"{message}\n\n— Iota Bot (@Boobies_00)"
    if target=="all":
        db=get_db(); chats=await db.group_settings.find({},{"_id":1}).to_list(10000)
        sent=0; failed=0
        status=await update.message.reply_html(f"📢 Sending to {len(chats)} groups...")
        for ch in chats:
            try:
                await context.bot.send_message(ch["_id"], full_msg, parse_mode="HTML")
                sent+=1; await asyncio.sleep(0.1)
            except: failed+=1
        await status.edit_text(f"📢 Done!\n✅ {sent}\n❌ {failed}", parse_mode="HTML")
    else:
        try:
            cid=int(target)
            await context.bot.send_message(cid, full_msg, parse_mode="HTML")
            await update.message.reply_html(f"✅ Sent to <code>{cid}</code>!")
        except Exception as e:
            await update.message.reply_html(f"❌ Failed: {e}")

async def stats_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    db=get_db(); tu=await total_users()
    pu=await db.users.count_documents({"is_premium":True})
    bu=await db.users.count_documents({"is_banned":True})
    pipeline=[{"$group":{"_id":None,"total":{"$sum":"$balance"},"kills":{"$sum":"$kills"},"robs":{"$sum":"$robs"}}}]
    agg=await db.users.aggregate(pipeline).to_list(1)
    r=agg[0] if agg else {}
    cfg=get_current_models()
    await update.message.reply_html(
        f"📊 <b>Iota Bot Stats</b>\n\n"
        f"👥 Total Users: <b>{tu}</b>\n"
        f"💓 Premium: <b>{pu}</b>\n"
        f"🔨 Banned: <b>{bu}</b>\n\n"
        f"💰 Total Coins: <b>{fmt(r.get('total',0))}</b>\n"
        f"💀 Total Kills: <b>{r.get('kills',0)}</b>\n"
        f"🔫 Total Robs: <b>{r.get('robs',0)}</b>\n\n"
        f"🤖 Free Model: <code>{cfg['free_model']}</code>\n"
        f"🤖 Premium Model: <code>{cfg['premium_model']}</code>\n\n"
        f"👑 Owner: @Boobies_00"
    )

async def stars_stats_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    db=get_db()
    total_stars=await get_stars_total()
    count=await db.stars_payments.count_documents({})
    cursor=db.stars_payments.find(sort=[("created_at",-1)],limit=5)
    recent=await cursor.to_list(5)
    text=f"⭐ <b>Stars Stats</b>\n\n"
    text+=f"Total Stars: <b>{total_stars}</b>\n"
    text+=f"Total Payments: <b>{count}</b>\n\n"
    text+="Recent:\n"
    for r in recent:
        t=time.strftime('%d/%m %H:%M', time.localtime(r.get("created_at",0)))
        text+=f"• {r.get('full_name','?')} — ⭐{r.get('stars',0)} ({t})\n"
    await update.message.reply_html(text)

# ── /setmodel ─────────────────────────────────────────────────────────────────

async def setmodel_cmd(update, context):
    """Owner: /setmodel free|premium <model_name>"""
    if not _own(update.effective_user.id): await update.message.reply_html("❌ Owner only!"); return
    args=context.args
    if len(args)<2:
        cfg=get_current_models(); models=get_all_models()
        text=(f"🤖 <b>AI Model Settings</b>\n\n"
              f"Current free: <code>{cfg['free_model']}</code>\n"
              f"Current premium: <code>{cfg['premium_model']}</code>\n\n"
              f"<b>Free models (Kilo.ai):</b>\n")
        for m in models["free"]: text+=f"• <code>{m}</code>\n"
        text+=f"\n<b>Premium models (x666.me):</b>\n"
        for m in models["premium"]: text+=f"• <code>{m}</code>\n"
        text+="\nUsage: /setmodel free|premium <model>"
        await update.message.reply_html(text); return
    tier=args[0].lower(); model=" ".join(args[1:])
    if tier not in ("free","premium"):
        await update.message.reply_html("❌ Use: /setmodel free|premium <model>"); return
    set_model(tier, model)
    await save_model_config_db()
    await update.message.reply_html(f"✅ {tier.title()} model set to:\n<code>{model}</code>")

async def listmodels_cmd(update, context):
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    cfg=get_current_models(); models=get_all_models()
    text=(f"🤖 <b>Available AI Models</b>\n\n"
          f"✅ Active free: <code>{cfg['free_model']}</code>\n"
          f"✅ Active premium: <code>{cfg['premium_model']}</code>\n\n"
          f"<b>🆓 Free (Kilo.ai):</b>\n")
    for m in models["free"]: text+=f"• <code>{m}</code>\n"
    text+=f"\n<b>💓 Premium (x666.me):</b>\n"
    for m in models["premium"]: text+=f"• <code>{m}</code>\n"
    await update.message.reply_html(text)

# ── /scan — hidden owner command ───────────────────────────────────────────────

async def scan_cmd(update, context):
    """Full user scan — owner only secret command."""
    if not _own(update.effective_user.id): return  # Silent fail for hidden cmd
    if not context.args: await update.message.reply_html("Usage: /scan <uid>"); return
    try: uid=int(context.args[0])
    except: await update.message.reply_html("❌ Invalid uid!"); return
    d=await get_user(uid)
    if not d: await update.message.reply_html("❌ User not found!"); return
    from utils.mongo_db import get_card_rank, get_user_rank
    cr=await get_card_rank(uid); rank=await get_user_rank(uid)
    now=int(time.time())
    prem_until=d.get("premium_until",0)
    prem_exp=time.strftime('%d/%m/%Y',time.localtime(prem_until)) if prem_until>now else "Expired"
    await update.message.reply_html(
        f"🔍 <b>Full Scan — User <code>{uid}</code></b>\n\n"
        f"👤 Name: {d.get('full_name','?')}\n"
        f"📛 Username: @{d.get('username','none')}\n"
        f"💰 Balance: {fmt(d.get('balance',0))}\n"
        f"🏦 Wallet: {fmt(d.get('wallet',0))}\n"
        f"💎 Gems: {d.get('gems',0)}\n"
        f"💓 Premium: {d.get('is_premium',False)} (Until: {prem_exp})\n"
        f"🚫 Banned: {d.get('is_banned',False)}\n"
        f"💀 Kills: {d.get('kills',0)} | Robs: {d.get('robs',0)}\n"
        f"⚡ XP: {d.get('xp',0)} | Level: {d.get('level',1)}\n"
        f"🌍 Rank: #{rank}\n"
        f"🃏 Card W:{cr.get('wins',0)} L:{cr.get('losses',0)} "
        f"Won:{fmt(cr.get('won_amount',0))}\n"
        f"🛡️ Protected until: {time.strftime('%d/%m %H:%M',time.localtime(d.get('protected_until',0)))}\n"
        f"💀 Dead until: {time.strftime('%d/%m %H:%M',time.localtime(d.get('dead_until',0)))}\n"
        f"📅 Joined: {time.strftime('%d/%m/%Y',time.localtime(d.get('created_at',0)))}\n\n"
        f"📝 Name History: {', '.join(d.get('name_history',[])[:5])}\n"
        f"📛 Username History: {', '.join(d.get('username_history',[])[:5])}"
    )

async def resetuser_cmd(update, context):
    if not _own(update.effective_user.id): return
    if not context.args: await update.message.reply_html("Usage: /resetuser <uid>"); return
    try: uid=int(context.args[0])
    except: await update.message.reply_html("❌"); return
    await update_user(uid, balance=0, gems=0, kills=0, robs=0, xp=0,
                      is_premium=False, premium_until=0, wallet=0,
                      dead_until=0, protected_until=0)
    await update.message.reply_html(f"✅ User <code>{uid}</code> reset!")

async def giveall_cmd(update, context):
    """Give coins to ALL users."""
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    if not context.args: await update.message.reply_html("Usage: /giveall <amount>"); return
    try: amt=int(context.args[0])
    except: await update.message.reply_html("❌"); return
    db=get_db()
    result=await db.users.update_many({"is_banned":{"$ne":True}},{"$inc":{"balance":amt}})
    await update.message.reply_html(
        f"💰 Gave {fmt(amt)} to <b>{result.modified_count}</b> users!")

_maintenance = False
async def maintenance_cmd(update, context):
    global _maintenance
    if not _own(update.effective_user.id): await update.message.reply_html("❌"); return
    args=context.args
    if not args: await update.message.reply_html(f"🔧 Maintenance: {'ON' if _maintenance else 'OFF'}"); return
    _maintenance = args[0].lower()=="on"
    await update.message.reply_html(f"🔧 Maintenance: <b>{'ON' if _maintenance else 'OFF'}</b>!")

def is_maintenance(): return _maintenance
