import random
from telegram import Update
from telegram.ext import ContextTypes
from utils.db import (ensure_user, get_valentine, set_valentine,
                      delete_valentine, count_valentines)
from utils.helpers import mention

TRUTH_LIST = [
    "Kabhi apni crush ko propose kiya h? and if yes then reject hue ho ya accept?",
    "Do you have secret crush on someone in this group?",
    "Aaj tak kisi ko cheat kiya hai? 👀",
    "Teri life ka sabse embarrassing moment kya hai?",
    "Pehli baar kiss kab kiya? Kaise tha? 😳",
    "Kuch aisa bata jo tumne kisi ko nahi bataya...",
    "Group mein kisi ke saath date pe jaana chahoge?",
    "Apni ex/crush ke baare mein kya sochte ho aajkal?",
    "Kabhi kisi ki copy ki hai exam mein? 😂",
    "Zindagi mein sabse bada jhooth kya bola?",
]

DARE_LIST = [
    "Type the most embarrassing childhood moment you remember.",
    "Write a 2-line poem for the last person who sent a message in the group.",
    "Send a voice message singing a song! 🎵",
    "Change your bio for 1 hour and share screenshot!",
    "Text your crush right now! Share reply 👀",
    "Call someone by their full name for the next 5 messages.",
    "Speak only in rhymes for the next 3 messages!",
    "Write a love letter to the person above you!",
    "Put a funny sticker as your profile pic for 30 mins!",
    "Admit your biggest weakness in the group!",
]

PUZZLE_LIST = [
    ("Main kabhi girta nahi, par hamesha girta dikhta hu. Kaun hu main?", "Barish (Rain)"),
    ("Jitna liya utna chhoda, kya hai ye?", "Kadam (Footsteps)"),
    ("Har roz bante hain, koi khaata nahi. Kya hain?", "Sapne (Dreams)"),
    ("I have keys but no locks, space but no room. What am I?", "A keyboard"),
    ("What gets wetter as it dries?", "A towel"),
    ("The more you take, the more you leave behind.", "Footsteps"),
    ("What has hands but cannot clap?", "A clock"),
    ("I speak without mouth, hear without ears.", "An echo"),
    ("What has a head, tail, but no body?", "A coin"),
    ("Forward I am heavy, backward I am not. What am I?", "Ton"),
]

# GIF URLs for actions
ACTION_GIFS = {
    "slap":  "https://media.giphy.com/media/uqSU9IEYEKAbS/giphy.gif",
    "punch": "https://media.giphy.com/media/xT8qBvH1pAhtfSx52U/giphy.gif",
    "kiss":  "https://media.giphy.com/media/G3va31oEEnIkM/giphy.gif",
    "hug":   "https://media.giphy.com/media/od5H3PmEG5EVq/giphy.gif",
    "bite":  "https://media.giphy.com/media/l2R013yx6S7K9YqMM/giphy.gif",
    "murder":"https://media.giphy.com/media/l2RsnnJ4pFNTXMwKc/giphy.gif",
}

_valentine_state: dict = {}   # exported for ai_chat.py


def _group_only(chat):
    return chat.type == "private"


async def _action(update, target_u, action_text, gif_key=None):
    msg = update.effective_message
    u   = update.effective_user
    if gif_key and gif_key in ACTION_GIFS:
        try:
            await msg.reply_animation(
                ACTION_GIFS[gif_key],
                caption=action_text,
                parse_mode="HTML"
            )
            return
        except Exception:
            pass
    await msg.reply_html(action_text)


# ─── Fun commands ─────────────────────────────────────────────────────────────

async def couples_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if _group_only(chat):
        await update.message.reply_html("🚫 Yᴏᴜ Cᴀɴ Uꜱᴇ Tʜɪꜱ Cᴏᴍᴍᴀɴᴅ Iɴ Gʀᴏᴜᴘꜱ Oɴʟʏ."); return
    try:
        admins = await context.bot.get_chat_administrators(chat.id)
        members = [a.user for a in admins if not a.user.is_bot]
    except Exception:
        members = []
    if len(members) < 2:
        await update.message.reply_html("❌ Not enough members!"); return
    p1, p2 = random.sample(members, 2)
    await update.message.reply_html(
        f"💕 <b>Today's Couple!</b>\n\n"
        f"{mention(p1)} ❤️ {mention(p2)}\n\n"
        f"Compatibility: <b>{random.randint(60, 100)}%</b> 💘"
    )


async def crush_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if _group_only(update.effective_chat):
        await update.message.reply_html("🚫 Yᴏᴜ Cᴀɴ Uꜱᴇ Tʜɪꜱ Cᴏᴍᴍᴀɴᴅ Iɴ Gʀᴏᴜᴘꜱ Oɴʟʏ."); return
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("🚫 Yᴏᴜ Cᴀɴ Uꜱᴇ Tʜɪꜱ Cᴏᴍᴍᴀɴᴅ Iɴ Gʀᴏᴜᴘꜱ Oɴʟʏ."); return
    t = msg.reply_to_message.from_user
    await msg.reply_html(
        f"💗 {mention(u)} has a crush on {mention(t)}! 🥺\n"
        f"Crush meter: <b>{random.randint(50,100)}%</b> 💕"
    )


async def love_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("Reply to someone!"); return
    t   = msg.reply_to_message.from_user
    pct = random.randint(0, 100)
    heart = "💔" if pct<30 else ("💛" if pct<60 else ("❤️" if pct<85 else "💘"))
    await msg.reply_html(f"{heart} {mention(u)} + {mention(t)} = <b>{pct}%</b> {heart}")


async def look_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("Rᴇᴘʟʏ Tᴏ Sᴏᴍᴇᴏɴᴇ."); return
    t = msg.reply_to_message.from_user
    await msg.reply_html(f"👀 {mention(u)} is looking at {mention(t)}... {random.randint(60,100)}/100 😍")


async def brain_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    t   = msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else update.effective_user
    pct = random.randint(1, 200)
    txt = "🤯 Genius!" if pct>150 else (" 😐 Average" if pct>80 else " 😂 LOL")
    await msg.reply_html(f"🧠 {mention(t)}'s brain: <b>{pct}%</b>{txt}")


async def stupid_meter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    t   = msg.reply_to_message.from_user if (msg.reply_to_message and msg.reply_to_message.from_user) else update.effective_user
    await msg.reply_html(f"🤪 {mention(t)}: <b>{random.randint(0,100)}%</b> stupid 😂")


async def murder_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("🔪 Rᴇᴘʟʏ Tᴏ Sᴏᴍᴇᴏɴᴇ Tᴏ Mᴜʀᴅᴇʀ Tʜᴇᴍ!"); return
    t = msg.reply_to_message.from_user
    weapons = ["🔪 knife","🔫 gun","☠️ poison","💣 bomb","🪓 axe","🏹 arrow"]
    await _action(update, t,
                  f"💀 {mention(u)} murdered {mention(t)} with a {random.choice(weapons)}!",
                  "murder")


async def slap_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("Rᴇᴘʟʏ Tᴏ Sᴏᴍᴇᴏɴᴇ."); return
    t = msg.reply_to_message.from_user
    await _action(update, t, f"👋 {mention(u)} slapped {mention(t)} hard! 💥", "slap")


async def punch_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("Rᴇᴘʟʏ Tᴏ Sᴏᴍᴇᴏɴᴇ."); return
    t = msg.reply_to_message.from_user
    await _action(update, t, f"👊 {mention(u)} punched {mention(t)}! 💢", "punch")


async def bite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("Rᴇᴘʟʏ Tᴏ Sᴏᴍᴇᴏɴᴇ."); return
    t = msg.reply_to_message.from_user
    await _action(update, t, f"😬 {mention(u)} bit {mention(t)}! 🦷", "bite")


async def kiss_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("Rᴇᴘʟʏ Tᴏ Sᴏᴍᴇᴏɴᴇ."); return
    t = msg.reply_to_message.from_user
    await _action(update, t, f"😘 {mention(u)} kissed {mention(t)}! 💋", "kiss")


async def hug_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message; u = update.effective_user
    if not msg.reply_to_message or not msg.reply_to_message.from_user:
        await msg.reply_html("Rᴇᴘʟʏ Tᴏ Sᴏᴍᴇᴏɴᴇ."); return
    t = msg.reply_to_message.from_user
    await _action(update, t, f"🤗 {mention(u)} hugged {mention(t)} tightly! 💞", "hug")


async def truth_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(f"🤔 <b>Truth:</b>\n\n{random.choice(TRUTH_LIST)}")


async def dare_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(f"😈 <b>Dare:</b>\n\n{random.choice(DARE_LIST)}")


async def puzzle_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q, a = random.choice(PUZZLE_LIST)
    sent = await update.message.reply_html(
        f"🧠 <b>Puzzle:</b>\n\n{q}\n\n<spoiler>{a}</spoiler>"
    )


# ── Valentine ─────────────────────────────────────────────────────────────────

async def valentine_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    ensure_user(u.id, u.username or "", u.full_name)
    if get_valentine(u.id):
        await update.message.reply_html(
            "💌 Already registered!\nUse /valentine_delete to re-register."
        ); return
    _valentine_state[u.id] = {"step": "gender"}
    await update.message.reply_html(
        "💌 <b>Valentine Event!</b>\n\n"
        "Step 1/4: What is your gender?\n"
        "Reply: <code>male</code> or <code>female</code>"
    )


async def valentine_cancel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _valentine_state.pop(update.effective_user.id, None)
    await update.message.reply_html("❌ Valentine form cancelled!")


async def valentine_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    row = count_valentines()
    await update.message.reply_html(
        f"🎀 <b>Valentine Event Stats</b>\n\n"
        f"👥 Total: <b>{row['t'] or 0}</b>\n"
        f"👨 Male: <b>{row['m'] or 0}</b>\n"
        f"👩 Female: <b>{row['f'] or 0}</b>"
    )


async def valentine_delete_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    delete_valentine(update.effective_user.id)
    await update.message.reply_html("✅ Deleted! Use /valentine to re-register.")


async def valentine_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u    = update.effective_user
    text = (update.message.text or "").strip()
    st   = _valentine_state.get(u.id)
    if not st: return

    step = st.get("step")
    if step == "gender":
        if text.lower() not in ("male", "female"):
            await update.message.reply_html("❌ Reply <code>male</code> or <code>female</code>"); return
        st["gender"] = text.lower(); st["step"] = "choice1"
        await update.message.reply_html(
            "💌 Step 2/4: Enter <b>User ID</b> of your 1st choice\n"
            "Use /id to get ID. Or type <code>skip</code>"
        )
    elif step == "choice1":
        st["choice1"] = int(text) if text.isdigit() else 0
        st["step"] = "choice2"
        await update.message.reply_html("💌 Step 3/4: 2nd choice User ID (or <code>skip</code>)")
    elif step == "choice2":
        st["choice2"] = int(text) if text.isdigit() else 0
        st["step"] = "choice3"
        await update.message.reply_html("💌 Step 4/4: 3rd choice User ID (or <code>skip</code>)")
    elif step == "choice3":
        c3 = int(text) if text.isdigit() else 0
        _valentine_state.pop(u.id, None)
        set_valentine(u.id, st["gender"], st.get("choice1",0), st.get("choice2",0), c3)
        await update.message.reply_html(
            f"✅ <b>Valentine registered!</b>\n\n"
            f"Gender: {st['gender']}\n"
            f"Choices: {st.get('choice1',0)} | {st.get('choice2',0)} | {c3}\n\n"
            f"Results declared soon! 💌"
        )
