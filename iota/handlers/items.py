from telegram import Update
from telegram.ext import ContextTypes
from utils.db import ensure_user, get_user, update_user, add_item, get_items, remove_item
from utils.helpers import mention, fmt
from config import ITEMS

async def items_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "📦 <b>Aᴠᴀɪʟᴀʙʟᴇ Gɪꜰᴛ Iᴛᴇᴍꜱ:</b>\n\n"
    for name,(emoji,price) in ITEMS.items():
        text += f"{emoji} {name.replace('_',' ').title()} — {fmt(price)}\n"
    text += "\nUse: /gift <item_name> (reply to someone)"
    await update.message.reply_html(text)

async def item_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    tu  = msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else update.effective_user
    ensure_user(tu.id, tu.username or "", tu.full_name)
    rows = get_items(tu.id)
    if not rows:
        await msg.reply_html(f"👀 {mention(tu)} Hᴀꜱ Nᴏ Iᴛᴇᴍꜱ Yᴇᴛ."); return
    text = f"🎁 <b>{mention(tu)}'s Items</b>\n\n"
    for r in rows:
        emoji, _ = ITEMS.get(r["item_name"], ("🎁", 0))
        text += f"{emoji} {r['item_name'].replace('_',' ').title()} × {r['quantity']}\n"
    await msg.reply_html(text)

async def gift_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    ensure_user(u.id, u.username or "", u.full_name); giver = get_user(u.id)
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("⚠️ Rᴇᴘʟʏ Tᴏ Tʜᴇ Uꜱᴇʀ Yᴏᴜ Wᴀɴᴛ Tᴏ Gɪꜰᴛ."); return
    if not context.args:
        await msg.reply_html("❌ Usage: /gift <item_name> (reply)\nSee /items"); return
    item_name = context.args[0].lower()
    if item_name not in ITEMS:
        await msg.reply_html(f"❌ Unknown item! See /items"); return
    emoji, price = ITEMS[item_name]
    ru = msg.reply_to_message.from_user
    if ru.id == u.id: await msg.reply_html("😂 Can't gift yourself!"); return
    if giver["balance"] < price:
        await msg.reply_html(f"❌ Need {fmt(price)}, you have {fmt(giver['balance'])}"); return
    ensure_user(ru.id, ru.username or "", ru.full_name)
    update_user(u.id, balance=giver["balance"]-price)
    add_item(ru.id, item_name)
    await msg.reply_html(
        f"{emoji} {mention(u)} gifted <b>{item_name.replace('_',' ').title()}</b> to {mention(ru)}!\n"
        f"💰 Cost: {fmt(price)}"
    )
