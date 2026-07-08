"""
Iota Bot — Safe HTML utilities.

WHY THIS FILE EXISTS
─────────────────────
Telegram's HTML parse mode only allows a small whitelist of tags
(<b> <i> <u> <s> <code> <pre> <a> <tg-spoiler> <blockquote> <em> <strong>).

Every other "<...>" in a message — even something completely innocent like
a usage hint "/setmodel free|premium <model>" — is treated as an unknown
start tag and makes Telegram's API reject the ENTIRE message with:

    BadRequest: Can't parse entities: unsupported start tag "model"
    at byte offset 570

This is exactly what was crashing /panel and other owner commands: usage
strings like "<uid>", "<amt>", "<msg>", "<model>", "<user_id>" were being
sent raw inside reply_html() / parse_mode="HTML" calls.

FIX
───
1. Use safe_html() to escape any raw placeholder text before interpolating
   it into an HTML-mode message ("<model>" -> "&lt;model&gt;").
2. Use safe_reply_html() / safe_edit_html() as drop-in replacements for
   msg.reply_html() / query.edit_message_text() that:
     - never raise on a bad-entity error (auto-retries as plain text
       instead of crashing the whole command)
     - still render correctly formatted bold/code/etc. text normally
"""
import html as _html
import logging

logger = logging.getLogger(__name__)

# Tags Telegram's Bot API HTML parser actually supports.
_ALLOWED_TAGS = {
    "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "a", "tg-spoiler", "blockquote", "span",
}


def safe_html(text) -> str:
    """
    Escape a plain value so it can be safely interpolated into an
    HTML-parse-mode Telegram message. Use this around ANY user-controlled
    or placeholder-style value, e.g.:

        f"Usage: /addcoins {safe_html('<uid>')} {safe_html('<amt>')}"
        f"Hello {safe_html(user.full_name)}"

    This turns "<model>" into "&lt;model&gt;" so Telegram displays it as
    literal text instead of trying (and failing) to parse it as a tag.
    """
    if text is None:
        return ""
    return _html.escape(str(text), quote=False)


def placeholder(name: str) -> str:
    """Shorthand for building a literal '<name>' placeholder that is safe
    to embed in an HTML-parse-mode message, e.g. placeholder('uid') -> '&lt;uid&gt;'."""
    return f"&lt;{name}&gt;"


async def safe_reply_html(msg, text: str, **kwargs):
    """
    Drop-in replacement for `msg.reply_html(text, **kwargs)` that never
    lets a bad-entity error crash the calling command. If Telegram
    rejects the HTML (e.g. a stray unescaped '<' slipped through), this
    automatically retries as plain text so the user still gets a reply.
    """
    try:
        return await msg.reply_text(text, parse_mode="HTML", **kwargs)
    except Exception as e:
        err = str(e).lower()
        if "can't parse entities" in err or "unsupported start tag" in err:
            logger.warning(f"safe_reply_html: HTML parse failed, retrying as plain text: {e}")
            plain = _strip_tags(text)
            try:
                return await msg.reply_text(plain, **kwargs)
            except Exception:
                logger.exception("safe_reply_html: plain-text fallback also failed")
                return None
        raise


async def safe_edit_html(query, text: str, **kwargs):
    """Drop-in replacement for query.edit_message_text(text, parse_mode='HTML', ...)
    with the same auto-fallback-to-plain-text safety as safe_reply_html."""
    try:
        return await query.edit_message_text(text, parse_mode="HTML", **kwargs)
    except Exception as e:
        err = str(e).lower()
        if "can't parse entities" in err or "unsupported start tag" in err:
            logger.warning(f"safe_edit_html: HTML parse failed, retrying as plain text: {e}")
            plain = _strip_tags(text)
            try:
                return await query.edit_message_text(plain, **kwargs)
            except Exception:
                logger.exception("safe_edit_html: plain-text fallback also failed")
                return None
        raise


def _strip_tags(text: str) -> str:
    """Very small best-effort tag stripper used only as a last-resort
    fallback when HTML parsing fails and we need to show *something*."""
    import re
    # Unescape entities first so the plain text reads naturally.
    text = re.sub(r"<[^>]+>", "", text)
    return _html.unescape(text)
