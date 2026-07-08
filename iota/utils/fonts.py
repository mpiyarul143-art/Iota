"""
Iota Font System - Iota-style smallcaps/unicode fonts
"""

# Smallcaps alphabet (Iota style)
_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ',
    'i':'ɪ','j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ',
    'q':'ǫ','r':'ʀ','s':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x',
    'y':'ʏ','z':'ᴢ'
}

def sc(text: str) -> str:
    """
    Convert text to Iota-style smallcaps — matching the exact visual
    style used by other bots (e.g. "𝐁ᴀᴋᴀ" / "Aʟʟ Eᴄᴏɴᴏᴍʏ Cᴏᴍᴍᴀɴᴅꜱ"):
    the FIRST letter of each word stays a normal, full-size capital,
    and every letter after it becomes a small-caps glyph. Previously
    this converted every single letter uniformly (including the first
    letter of each word), which didn't match that look at all — every
    word came out looking fully lowercase-small-caps instead of having
    that bold-capital-then-small-caps punch.
    Non-letter characters (spaces, punctuation, digits, emoji, HTML)
    pass through completely untouched.
    """
    words = text.split(" ")
    out = []
    for w in words:
        if not w:
            out.append(w)
            continue
        first, rest = w[0], w[1:]
        out.append(first + "".join(_SC.get(c.lower(), c) for c in rest))
    return " ".join(out)

def bold_sc(text: str) -> str:
    """Smallcaps wrapped in HTML bold."""
    return f"<b>{sc(text)}</b>"

def header(text: str) -> str:
    """Bold smallcaps header."""
    return f"<b>{sc(text.upper())}</b>"

# Preset styled texts
PROTECTED    = "🛡️ " + sc("You Are Now Protected")
ALREADY_PROT = "🛡️ " + sc("You Are Already Protected")
DEAD_STATUS  = "💀 " + sc("Dead")
ALIVE_STATUS = "✅ " + sc("Alive")
BALANCE_HDR  = "💰 " + sc("Balance")
RANK_HDR     = "🏆 " + sc("Global Rank")
KILLS_HDR    = "⚔️ " + sc("Kills")
STATUS_HDR   = "🛡️ " + sc("Status")
NAME_HDR     = "👤 " + sc("Name")
LEVEL_HDR    = "🟤 " + sc("Level")
REMAINING    = "⏳ " + sc("Remaining")
ALERT        = "⚠️  " + sc("Alert!")
