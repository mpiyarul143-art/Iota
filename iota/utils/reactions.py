"""
Iota Bot — Message Reactions

Lets Iota react to a message with a single emoji (like a human tapping
the reaction picker), using Telegram's native message-reaction feature
(Bot API `setMessageReaction`, exposed in PTB 21+ as
`bot.set_message_reaction`). Works identically in DMs and groups — no
special permissions needed for a bot to REACT (only to RECEIVE reaction
updates from others would need admin, which isn't used here).

WHEN IOTA REACTS
─────────────────
Not every message — that would be spammy and defeat the point. Iota
reacts only when a message clearly calls for it: strong emotion,
achievements/wins, sad news, something funny, a compliment to her, or a
big milestone in a game (e.g. a Ludo win, a rob/kill success). This is a
lightweight keyword/sentiment heuristic — deliberately NOT another AI
call — so it stays fast and free, and never blocks or delays the actual
reply.

USAGE
──────
    from utils.reactions import maybe_react
    await maybe_react(context.bot, update.effective_message)

Safe to call on every incoming message — it internally decides whether a
reaction actually fits, and silently does nothing (no exception, no
delay) if Telegram's reaction API isn't available for that message type
(e.g. some service messages can't be reacted to) or the call fails for
any other reason (never blocks the caller's own reply).
"""
import logging
import random
import re

from telegram import ReactionTypeEmoji
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

# Telegram only allows a specific whitelist of emoji for bot/user
# reactions (not arbitrary Unicode) — this list is Telegram's documented
# supported reaction set as of the current Bot API.
_ALLOWED = {
    "👍", "👎", "❤", "🔥", "🥰", "👏", "😁", "🤔", "🤯", "😱",
    "🤬", "😢", "🎉", "🤩", "🙏", "👌", "🕊", "🤡", "🥱", "🥴",
    "😍", "🐳", "🌚", "🌭", "💯", "🤣", "⚡", "🍌", "🏆",
    "💔", "🤨", "😐", "🍓", "🍾", "💋", "🖕", "😈", "😴", "😭",
    "🤓", "👻", "👀", "🎃", "🙈", "😇", "😨", "🤝", "✍",
    "🤗", "🫡", "🎅", "🎄", "☃", "💅", "🤪", "🗿", "🆒", "💘",
    "🙉", "🦄", "😘", "💊", "🙊", "😎", "👾", "🤷", "😡",
}
# 🔴 FIX: removed a handful of ZWJ-sequence emoji (❤‍🔥, 👨‍💻, 🤷‍♂, 🤷‍♀)
# that aren't in Telegram's actual documented reaction whitelist — using
# them would silently fail (caught by the try/except below, so it never
# crashed, but those reactions just never actually appeared). Kept the
# base non-gendered 🤷 which IS on the real list.

# Pattern -> weighted emoji choices. Checked in order; first match wins
# (so more specific patterns should come before general ones).
_RULES: list[tuple[re.Pattern, list[str]]] = [
    # Wins / big achievements (games, /rob, /kill, /ludo, etc.)
    (re.compile(r'\b(jeet gaya|jeet liya|won|winner|i won|maine jeet)\b', re.I), ["🏆", "🎉", "🔥"]),
    # Funny
    (re.compile(r'\b(lol|lmao|rofl|haha+|hehe+|😂+)\b', re.I), ["🤣", "😁"]),
    # Sad / bad news
    (re.compile(r'\b(sad|dukhi|ro raha|roya|dead|died|mar gaya|upset|depressed)\b', re.I), ["😢", "💔"]),
    # Love / romantic
    (re.compile(r'\b(love you|i love|pyaar|ishq|shaadi|marry)\b', re.I), ["🥰", "❤"]),
    # Compliments to Iota
    (re.compile(r'\b(you\'?re (so )?(cute|smart|amazing|best|great)|tum (kitni|bahut) (cute|pyari|achi))\b', re.I), ["🥰", "😍"]),
    # Shock / surprise
    (re.compile(r'\b(what+|kya+|omg|oh my god|wtf|shocking)[\?!]', re.I), ["😱", "🤯"]),
    # Fire / hype
    (re.compile(r'\b(fire|lit|awesome|epic|goated|insane|op)\b', re.I), ["🔥", "🤩"]),
    # Anger
    (re.compile(r'\b(angry|gussa|irritating|annoying|pissed)\b', re.I), ["😡", "🤬"]),
    # Birthday / celebration
    (re.compile(r'\b(happy birthday|hbd|congrats|congratulations|badhai)\b', re.I), ["🎉", "🥳" if "🥳" in _ALLOWED else "🎉"]),
]

# Overall chance to react even when a rule matches — keeps it feeling
# natural/occasional rather than mechanical every single time.
_REACT_PROBABILITY = 0.5


async def maybe_react(bot, message) -> bool:
    """
    Looks at `message.text` (or caption) and, if it clearly calls for a
    reaction, sets one via Telegram's native reaction feature. Returns
    True if a reaction was set, False otherwise. Never raises.
    """
    try:
        text = (getattr(message, "text", None) or getattr(message, "caption", None) or "").strip()
        if not text:
            return False

        chosen = None
        for pattern, choices in _RULES:
            if pattern.search(text):
                chosen = random.choice([c for c in choices if c in _ALLOWED] or ["👍"])
                break

        if not chosen:
            return False
        if random.random() > _REACT_PROBABILITY:
            return False  # matched, but skip this time to feel natural

        await bot.set_message_reaction(
            chat_id=message.chat_id,
            message_id=message.message_id,
            reaction=[ReactionTypeEmoji(chosen)],
        )
        return True
    except TelegramError as e:
        # Some messages/chat types can't be reacted to (e.g. certain
        # service messages, or channels without reactions enabled) —
        # this is expected sometimes and should never break the caller.
        logger.debug(f"maybe_react: reaction failed (non-fatal): {e}")
        return False
    except Exception as e:
        logger.debug(f"maybe_react: unexpected error (non-fatal): {e}")
        return False
