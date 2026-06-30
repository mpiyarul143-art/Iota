"""
Iota Font System - Baka-style smallcaps/unicode fonts
"""

# Smallcaps alphabet (like Baka bot)
_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ',
    'i':'ɪ','j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ',
    'q':'Q','r':'ʀ','s':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x',
    'y':'ʏ','z':'ᴢ'
}

def sc(text: str) -> str:
    """Convert text to smallcaps like Baka bot."""
    return ''.join(_SC.get(c.lower(), c) for c in text)

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
