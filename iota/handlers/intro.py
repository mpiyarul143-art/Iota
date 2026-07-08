"""
Iota /intro System
- /set_intro — Set your introduction
- /intro — Show your intro or replied user's intro
- /intro me (reply) — Introduce yourself to replied user
- /intro myself (reply) — Same
- /del_intro — Delete your intro
- /intro_list — Show all intros in group (premium)
"""
from telegram import Update
from telegram.ext import ContextTypes
from utils.mongo_db import get_db, ensure_user, get_user
from utils.helpers import mention, ts
from utils.fonts import sc

async def _get_intro(uid: int):
    return await get_db().intros.find_one({"_id": uid})

async def _set_intro(uid: int, text: str, name: str, username: str):
    await get_db().intros.update_one(
        {"_id": uid},
        {"$set": {"text": text, "name": name, "username": username, "updated_at": ts()}},
        upsert=True
    )

async def _del_intro(uid: int):
    await get_db().intros.delete_one({"_id": uid})

def _format_intro(intro_doc: dict, mention_str: str) -> str:
    return (
        f"👤 <b>Introduction</b>\n\n"
        f"🌟 {mention_str}\n\n"
        f"📝 {intro_doc['text']}"
    )

# ── /set_intro ────────────────────────────────────────────────────────────────

async def set_intro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user; msg = update.effective_message
    await ensure_user(u.id, u.username or "", u.full_name)

    # Get text from args or reply
    if context.args:
        text = " ".join(context.args)
    elif msg.reply_to_message and msg.reply_to_message.text:
        text = msg.reply_to_message.text
    else:
        current = await _get_intro(u.id)
        if current:
            await msg.reply_html(
                f"📝 <b>Your current intro:</b>\n\n{current['text']}\n\n"
                f"Update: /set_intro &lt;new intro text&gt;\n"
                f"Delete: /del_intro"
            )
        else:
            await msg.reply_html(
                f"📝 <b>Set Your Introduction!</b>\n\n"
                f"Usage: /set_intro &lt;your intro&gt;\n\n"
                f"Example:\n"
                f"/set_intro Hi! I'm a gamer from India 🎮 Love anime and coding! "
                f"Feel free to talk to me anytime 😊"
            )
        return

    if len(text) > 500:
        await msg.reply_html(f"❌ {sc('Intro too long!')} Max 500 characters."); return
    if len(text) < 5:
        await msg.reply_html(f"❌ {sc('Too short!')} Write at least 5 characters."); return

    await _set_intro(u.id, text, u.full_name, u.username or "")
    await msg.reply_html(
        f"✅ <b>Intro Set!</b>\n\n"
        f"📝 {text}\n\n"
        f"Now others can learn about you with /intro (reply to your message)\n"
        f"Introduce yourself: /intro me (reply to someone)"
    )

# ── /intro ─────────────────────────────────────────────────────────────────────

async def intro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    await ensure_user(u.id, u.username or "", u.full_name)
    args = context.args or []
    arg_text = " ".join(args).lower().strip()

    # /intro me or /intro myself → introduce yourself to replied user
    if arg_text in ("me", "myself"):
        if not msg.reply_to_message or not msg.reply_to_message.from_user:
            await msg.reply_html(
                f"❌ Reply to someone to introduce yourself to them!\n"
                f"Usage: /intro me [reply to user]"
            ); return

        target = msg.reply_to_message.from_user
        intro  = await _get_intro(u.id)
        if not intro:
            await msg.reply_html(
                f"❌ You haven't set your intro yet!\n"
                f"Set it first: /set_intro &lt;your intro&gt;"
            ); return

        await msg.reply_html(
            f"👋 {mention(target)}, {sc('Meet')} {mention(u)}!\n\n"
            + _format_intro(intro, mention(u))
        )
        return

    # /intro (with reply) → show replied user's intro
    if msg.reply_to_message and msg.reply_to_message.from_user:
        target = msg.reply_to_message.from_user
        if target.id == u.id:
            # Show own intro
            intro = await _get_intro(u.id)
            if not intro:
                await msg.reply_html(
                    f"📝 You haven't set your intro!\n/set_intro &lt;your intro&gt;"
                ); return
            await msg.reply_html(_format_intro(intro, mention(u)))
        else:
            await ensure_user(target.id, target.username or "", target.full_name)
            intro = await _get_intro(target.id)
            if not intro:
                await msg.reply_html(
                    f"❌ {mention(target)} {sc('has not set their intro yet!')}"
                ); return
            await msg.reply_html(_format_intro(intro, mention(target)))
        return

    # /intro alone → show own intro
    if not args:
        intro = await _get_intro(u.id)
        if not intro:
            await msg.reply_html(
                f"📝 <b>You have no intro set!</b>\n\n"
                f"Set it: /set_intro &lt;your intro text&gt;\n\n"
                f"Then:\n"
                f"• /intro → Show your intro\n"
                f"• /intro me [reply] → Introduce yourself to someone\n"
                f"• /intro [reply] → See someone's intro"
            ); return
        await msg.reply_html(_format_intro(intro, mention(u)))
        return

    # /intro @username or /intro <userid>
    target_arg = args[0].lstrip("@")
    try:
        if target_arg.isdigit():
            uid = int(target_arg)
        else:
            try:
                chat_member = await context.bot.get_chat(f"@{target_arg}")
                uid = chat_member.id
            except Exception:
                # 🔴 FIX: get_chat("@username") fails often even for real,
                # known users. Fall back to our own DB before giving up.
                from utils.mongo_db import get_user_by_username
                du = await get_user_by_username(target_arg)
                if not du:
                    raise
                uid = du["_id"]
        intro = await _get_intro(uid)
        if not intro:
            await msg.reply_html(f"❌ {sc('That user has no intro set!')}"); return
        nm = mention_id_raw(uid, intro.get("name","User"))
        await msg.reply_html(_format_intro(intro, nm))
    except Exception:
        await msg.reply_html("❌ User not found!")

def mention_id_raw(uid, name):
    return f'<a href="tg://user?id={uid}">{name}</a>'

# ── /del_intro ─────────────────────────────────────────────────────────────────

async def del_intro_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    intro = await _get_intro(u.id)
    if not intro:
        await update.message.reply_html(f"❌ {sc('You have no intro to delete!')}"); return
    await _del_intro(u.id)
    await update.message.reply_html(f"✅ {sc('Your intro has been deleted!')}")
