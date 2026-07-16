"""
Iota Bot — /q (Quote Sticker)
=============================

Ported faithfully from the IotaXMusic ``/q`` (quotly) system, but adapted from
Pyrogram/MTProto to python-telegram-bot (Bot API). Reply to a message with /q
to turn it into a Telegram-style quote image.

How it works
------------
1. Build a quotly ``quote`` payload from the replied message (text, sender,
   entities, optional reply-context bubble) — identical shape to IotaXMusic.
2. POST it to the external quotly API (LyoSU-compatible). It returns a PNG
   image (Telegram stickers are PNG-based; the ``.webp`` name is just the
   conventional extension).
3. Send it back. We try a real ``sticker`` first (the IotaXMusic look); if
   Bot API rejects the raw upload, we transparently fall back to a ``photo``,
   which Bot API accepts far more leniently. The user always gets the quote.

Everything degrades gracefully: if every quote endpoint is down, or the bot
cannot send media in that chat, the user gets a short in-character error
instead of a crash. Never raises. No chat actions are used.
"""
import base64
import logging
import random
import re
from io import BytesIO

import aiohttp
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# Quote-API endpoints tried in order (LyoSU-compatible, same resilient list
# the IotaXMusic bot uses so /q keeps working across networks).
_QUOTE_ENDPOINTS = (
    "https://shnwazdev-quoteapi.vercel.app/generate.png",
    "https://bot.lyo.su/quote/generate.png",
    "https://qc-api.rizzy.eu.org/generate",
)

_BACKGROUND = "#1b1429"
_QUOTE_EMOJI = "💜"
_HEADERS = {
    "Accept-Language": "en-US",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}
_TIMEOUT = aiohttp.ClientTimeout(total=25)


class QuotlyError(Exception):
    """Raised when no quote endpoint could produce an image."""


# ── Telegram-message → quotly field extractors ──────────────────────────────

def _sender_id(m) -> int:
    if getattr(m, "forward_origin", None):
        u = getattr(m, "from_user", None)
        return u.id if u else 1
    if getattr(m, "from_user", None):
        return m.from_user.id
    if getattr(m, "sender_chat", None):
        return m.sender_chat.id
    return 1


def _sender_name(m) -> str:
    u = getattr(m, "from_user", None)
    if u:
        return u.full_name or u.first_name or "Someone"
    sc = getattr(m, "sender_chat", None)
    if sc:
        return sc.title or "Channel"
    return "Someone"


def _sender_username(m) -> str:
    u = getattr(m, "from_user", None)
    if u and u.username:
        return u.username
    sc = getattr(m, "sender_chat", None)
    if sc and getattr(sc, "username", None):
        return sc.username
    return ""


def _chat_type(m) -> str:
    """Chat type string the quotly API expects ('private' / 'group' /
    'supergroup' / 'channel')."""
    chat = getattr(m, "chat", None)
    t = getattr(chat, "type", None)
    if t is None:
        return "private"
    return str(t).lower()


def _text_or_caption(m) -> str:
    return (getattr(m, "text", None) or getattr(m, "caption", None) or "")


def _entities_to_payload(m) -> list:
    """Convert PTB message entities to the quotly entity format so bold /
    italic / links / code etc. render exactly like in Telegram."""
    ents = getattr(m, "entities", None) or getattr(m, "caption_entities", None) or []
    out = []
    for e in ents:
        try:
            etype = e.type.value if hasattr(e.type, "value") else str(e.type)
        except Exception:
            etype = str(getattr(e, "type", ""))
        item = {
            "type": etype,
            "offset": e.offset,
            "length": e.length,
        }
        cid = getattr(e, "custom_emoji_id", None)
        if cid:
            item["custom_emoji_id"] = cid
        out.append(item)
    return out


async def _avatar_data_url(context, m) -> str:
    """Download the sender's profile photo through the bot and return it as a
    base64 data URL (the quotly API accepts this via ``photo.url``). Telegram
    file_ids are NOT resolvable by the remote API, so this is what actually
    makes the avatar render. Returns "" on any failure (card still renders,
    just without a photo)."""
    try:
        uid = None
        u = getattr(m, "from_user", None)
        if u:
            uid = u.id
        elif getattr(m, "sender_chat", None):
            uid = m.sender_chat.id
        if not uid:
            return ""
        photos = await context.bot.get_user_profile_photos(uid, limit=1)
        if not photos or not photos.photos:
            return ""
        best = photos.photos[0][-1]  # largest size of the most recent photo
        tgf = await context.bot.get_file(best.file_id)
        raw = bytes(await tgf.download_as_bytearray())
        if not raw:
            return ""
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.debug(f"/q avatar fetch failed: {e}")
        return ""


async def _build_payload(context, messages, include_reply: bool,
                         background: str) -> dict:
    payload = {
        "type": "quote",
        "format": "png",
        "backgroundColor": background or _BACKGROUND,
        "messages": [],
    }
    for m in messages:
        avatar_url = await _avatar_data_url(context, m)
        photo = {"url": avatar_url} if avatar_url else {}
        entry = {
            "entities": _entities_to_payload(m),
            "chatId": _sender_id(m),
            "avatar": True,
            "from": {
                "id": _sender_id(m),
                "name": _sender_name(m),
                "username": _sender_username(m),
                "type": _chat_type(m),
                "photo": photo,
            },
            "text": _text_or_caption(m),
            "replyMessage": {},
        }
        reply = getattr(m, "reply_to_message", None)
        if include_reply and reply is not None:
            entry["replyMessage"] = {
                "name": _sender_name(reply),
                "text": _text_or_caption(reply),
                "chatId": _sender_id(reply),
                "entities": _entities_to_payload(reply),
            }
        payload["messages"].append(entry)
    return payload


async def _render_quote(context, messages, include_reply: bool,
                        background: str = _BACKGROUND) -> bytes:
    """POST the payload to each endpoint until one returns a real image.
    Returns raw image bytes. Raises QuotlyError if all endpoints fail."""
    payload = await _build_payload(context, messages, include_reply, background)
    last_err = "all quote endpoints failed"
    async with aiohttp.ClientSession(headers=_HEADERS, timeout=_TIMEOUT) as s:
        for url in _QUOTE_ENDPOINTS:
            try:
                async with s.post(url, json=payload) as r:
                    body = await r.read()
                    if r.status != 200:
                        last_err = f"HTTP {r.status} from {url}"
                        continue
                    ctype = r.headers.get("content-type", "")
                    if "application/json" in ctype or body[:1] == b"{":
                        try:
                            data = await r.json(content_type=None)
                        except Exception:
                            last_err = f"invalid JSON from {url}"
                            continue
                        img_b64 = (
                            (data.get("result") or {}).get("image")
                            or data.get("image")
                        )
                        if not img_b64:
                            last_err = f"no image field from {url}"
                            continue
                        try:
                            return base64.b64decode(img_b64)
                        except Exception:
                            last_err = f"bad base64 from {url}"
                            continue
                    if body:
                        return body
                    last_err = f"empty body from {url}"
            except Exception as e:
                last_err = f"{type(e).__name__}: {e} ({url})"
    raise QuotlyError(last_err)


def _looks_like_image(b: bytes) -> bool:
    """True if `b` starts with the magic bytes of a format Telegram accepts
    (WEBP / PNG / JPEG). The endpoints occasionally answer HTTP 200 with an
    HTML/JSON error page; rejecting those avoids sending junk."""
    if not b or len(b) < 12:
        return False
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return True
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if b[:3] == b"\xff\xd8\xff":
        return True
    return False


def _fresh_bio(img: bytes, name: str) -> BytesIO:
    """A brand-new BytesIO per send attempt (a consumed stream can't be
    re-read, so each fallback needs its own)."""
    bio = BytesIO(img)
    bio.name = name
    return bio


async def _send_quote(msg, img: bytes) -> None:
    """Deliver the quote. Prefer a real sticker (the IotaXMusic look); if
    Bot API rejects the raw upload (it is stricter than Pyrogram/MTProto),
    transparently fall back to a photo — Bot API accepts photos far more
    leniently, and the quote looks the same to the user. No chat actions."""
    reply_kwargs = {
        "reply_to_message_id": msg.message_id,
        "allow_sending_without_reply": True,
    }
    # 1) Sticker — matches IotaXMusic's native look.
    try:
        await msg.reply_sticker(
            _fresh_bio(img, "quote.webp"),
            emoji=_QUOTE_EMOJI,
            **reply_kwargs,
        )
        return
    except Exception as e:
        logger.warning(f"/q reply_sticker rejected, falling back to photo: {e}")
    # 2) Photo — reliable delivery path under Bot API.
    try:
        await msg.reply_photo(_fresh_bio(img, "quote.png"), **reply_kwargs)
        return
    except Exception as e:
        logger.warning(f"/q reply_photo also failed: {e}")
        raise


async def quote_sticker_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    reply = msg.reply_to_message
    if not reply:
        await msg.reply_text(
            "❌ Reply to a message with /q to turn it into a quote sticker!"
        )
        return

    include_reply, count, background = _parse_args(context.args)
    if count < 1 or count > 10:
        await msg.reply_text("❌ Range 1-10 rakho.")
        return

    if not _text_or_caption(reply).strip():
        await msg.reply_text(
            "❌ Reply to a text message (a caption also works) to quote it."
        )
        return

    try:
        img = await _render_quote(context, [reply], include_reply,
                                  background or _BACKGROUND)
    except QuotlyError as e:
        logger.warning(f"/q failed (all endpoints): {e}")
        await _safe_reply(msg, "❌ Abhi quote nahi ban paaya, thodi der baad try karo 🥺")
        return
    except Exception as e:
        logger.exception(f"/q render error: {e}")
        await _safe_reply(msg, "❌ Abhi quote nahi ban paaya, thodi der baad try karo 🥺")
        return

    try:
        await _send_quote(msg, img)
    except Exception as e:
        logger.exception(f"/q send failed: {e}")
        await _safe_reply(
            msg, "❌ Quote ban gaya par yahan bhej nahi paayi 🥺 "
                 "(shayad media bhejne ki permission nahi hai)",
        )


async def _safe_reply(msg, text: str):
    """Send a plain-text reply, swallowing any send error (used on the error
    paths so a failed error-notice can't crash the handler)."""
    try:
        await msg.reply_text(text)
    except Exception as e:
        logger.debug(f"/q error-reply failed: {e}")


# ── Argument parsing ────────────────────────────────────────────────────────

def _parse_args(args) -> tuple[bool, int, str]:
    """Parse `/q [r] [N] [color]` → (include_reply, count, background).

    • 'r' / 'reply' → include the reply-context bubble.
    • integer (1-10) → count (reserved; Bot API can't fetch threads, but we
      still validate the range so `/q 3` doesn't error).
    • '#rrggbb' / '#rgb' / a known colour name / 'random' → background color.
    Invalid tokens are ignored. Returns background="" to mean "use default"."""
    include_reply = False
    count = 1
    background = ""
    for a in (args or []):
        al = a.lower().strip()
        if al in ("r", "reply"):
            include_reply = True
            continue
        if al == "random":
            background = _random_hex()
            continue
        if _HEX_RE.match(al):
            background = al
            continue
        if al in _KNOWN_COLOR_NAMES:
            background = al
            continue
        try:
            count = int(al)
        except (ValueError, TypeError):
            continue
    return include_reply, count, background


_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_KNOWN_COLOR_NAMES = {
    "white", "black", "red", "green", "blue", "yellow", "orange", "purple",
    "pink", "gray", "grey", "cyan", "magenta", "brown", "teal", "navy",
    "maroon", "olive", "lime", "aqua", "silver", "gold", "violet", "indigo",
}


def _random_hex() -> str:
    return "#{:06x}".format(random.randint(0, 0xFFFFFF))
