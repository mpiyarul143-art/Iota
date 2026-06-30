import re, time, asyncio
from telegram import Update
from telegram.ext import ContextTypes

def ts(): return int(time.time())

def mention(u) -> str:
    name = (u.full_name or u.first_name or "User").strip()
    return f'<a href="tg://user?id={u.id}">{name}</a>'

def mention_id(uid, name) -> str:
    return f'<a href="tg://user?id={uid}">{name}</a>'

def fmt(n: int) -> str:
    if n >= 1_00_00_000: return f"${n/1_00_00_000:.1f}Cr"
    if n >= 1_00_000:    return f"${n/1_00_000:.1f}L"
    if n >= 1_000:       return f"${n/1_000:.1f}k"
    return f"${n}"

def parse_duration(s: str) -> int:
    if not s: return 0
    m = re.match(r'^(\d+)([smhd])$', s.lower())
    if not m: return 0
    v, u = int(m.group(1)), m.group(2)
    return v * {"s":1,"m":60,"h":3600,"d":86400}[u]

def xp_level(xp: int) -> int:
    from config import XP_PER_LEVEL
    lv = 1
    while xp >= lv * XP_PER_LEVEL:
        xp -= lv * XP_PER_LEVEL; lv += 1
    return lv

def rank_title(lv: int) -> str:
    t = {1:"Rookie",2:"Beginner",3:"Fighter",4:"Warrior",5:"Elite",
         6:"Champion",7:"Legend",8:"Master",9:"GrandMaster",10:"Emperor"}
    return t.get(min(lv,10),"Emperor")

def user_icon(u: dict) -> str:
    if u.get("premium_emoji"): return u["premium_emoji"]
    return "💓" if u.get("is_premium") else "👤"

async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, uid=None) -> bool:
    if uid is None: uid = update.effective_user.id
    try:
        m = await context.bot.get_chat_member(update.effective_chat.id, uid)
        return m.status in ("administrator","creator")
    except Exception:
        return False

async def resolve_target(update: Update, context: ContextTypes.DEFAULT_TYPE, args: list):
    msg = update.effective_message
    if msg.reply_to_message and msg.reply_to_message.from_user:
        u = msg.reply_to_message.from_user
        return u.id, mention(u), args
    if args:
        t = args[0].lstrip("@"); rest = args[1:]
        if t.isdigit():
            uid = int(t)
            try:
                m = await context.bot.get_chat_member(update.effective_chat.id, uid)
                return uid, mention(m.user), rest
            except Exception:
                return uid, f"User {uid}", rest
        else:
            try:
                ch = await context.bot.get_chat(f"@{t}")
                return ch.id, mention_id(ch.id, ch.first_name), rest
            except Exception:
                return None, None, rest
    return None, None, args

async def delete_later(bot, cid, mid, delay=300):
    await asyncio.sleep(delay)
    try: await bot.delete_message(cid, mid)
    except Exception: pass
