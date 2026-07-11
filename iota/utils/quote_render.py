"""
Iota Bot — Quote Sticker Renderer (/q)

Renders a replied message (or a short thread of them) into a stylish quote
card with the sender's circular avatar, name, the message text, full-color
emoji and Devanagari support, a reply preview, multiple themes, and either
WEBP sticker or PNG image output.

Pure Pillow — no cairo/svg needed. Emoji use NotoColorEmoji when present
(most Ubuntu/Debian VPS hosts have it); if missing, emoji are skipped
gracefully (never a crash, just no icon).
"""
import io
import re
import logging

from PIL import Image, ImageDraw, ImageFont

from utils.font_manager import load_font

logger = logging.getLogger(__name__)

CARD_W = 512
PADDING = 28
INSET = 10
AVATAR_SIZE = 84
MAX_FONT_SIZE = 38
MIN_FONT_SIZE = 16
NAME_FONT_SIZE = 26

# ── Themes ────────────────────────────────────────────────────────────────
THEMES = {
    "dark":   {"bg": (28, 30, 46),      "border": (255, 182, 72),
               "name": (255, 182, 72),  "text": (238, 234, 220),
               "divider": (60, 63, 82), "accent": (255, 182, 72)},
    "light":  {"bg": (244, 244, 246),   "border": (255, 153, 51),
               "name": (198, 110, 20),  "text": (38, 40, 48),
               "divider": (212, 214, 220), "accent": (255, 153, 51)},
    "white":  {"bg": (255, 255, 255),   "border": (255, 153, 51),
               "name": (198, 110, 20),  "text": (30, 30, 30),
               "divider": (220, 220, 220), "accent": (255, 153, 51)},
    "purple": {"bg": (46, 30, 64),      "border": (186, 124, 255),
               "name": (200, 150, 255), "text": (240, 230, 252),
               "divider": (82, 60, 104), "accent": (186, 124, 255)},
    "blue":   {"bg": (18, 34, 60),      "border": (96, 178, 255),
               "name": (120, 190, 255), "text": (224, 238, 255),
               "divider": (48, 74, 112),  "accent": (96, 178, 255)},
}

_EMOJI_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

_EMOJI_RE = re.compile(
    "("
    "[\U0001F300-\U0001FAFF]"   # pictographs / emoticons
    "|[\U0001F1E0-\U0001F1FF]"  # flags
    "|[\u2600-\u27BF]"          # symbols & dingbats (❌ ✦ etc.)
    "|[\u2B00-\u2BFF]"          # symbols & arrows
    "|[\u2190-\u21FF]"          # arrows
    "|[\uFE00-\uFE0F]"          # variation selectors
    "|\u200D"                   # ZWJ
    "|[\u20E3]"                 # enclosing keycap
    ")",
    flags=re.UNICODE,
)

_SMALLCAPS_FIX = {"\uA730": "F", "\uA731": "S"}


class QuoteRenderError(Exception):
    pass


def _fix_smallcaps(text: str) -> str:
    for bad, good in _SMALLCAPS_FIX.items():
        text = text.replace(bad, good)
    return text


def _has_devanagari(text: str) -> bool:
    return any('\u0900' <= ch <= '\u097F' for ch in text)


def _hex_to_rgb(h: str):
    h = h.lstrip("#").strip()
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return None
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return None


def _parse_theme(theme: str):
    """Return a palette dict. `theme` may be a name or 'color #rrggbb'."""
    t = (theme or "dark").strip().lower()
    if t in THEMES:
        return dict(THEMES[t])
    if t.startswith("color"):
        parts = theme.split()
        hexv = None
        for p in parts[1:]:
            rgb = _hex_to_rgb(p)
            if rgb:
                hexv = rgb
                break
        if hexv:
            r, g, b = hexv
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            fg = (30, 30, 30) if lum > 140 else (238, 238, 238)
            accent = (255, 255, 255) if lum <= 140 else (20, 20, 20)
            return {"bg": hexv, "border": accent, "name": accent,
                    "text": fg, "divider": hexv, "accent": accent}
    return dict(THEMES["dark"])


def _pick_text_font(size: int, bold: bool = False, devanagari: bool = False):
    name = ("NotoSansDevanagari-Bold.ttf" if bold else "NotoSansDevanagari-Regular.ttf") \
        if devanagari else ("NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf")
    return load_font(name, size) or ImageFont.load_default()


def _pick_emoji_font():
    import os
    if not os.path.exists(_EMOJI_FONT_PATH):
        return None
    try:
        return ImageFont.truetype(_EMOJI_FONT_PATH, 109)
    except Exception as e:
        logger.debug(f"emoji font load failed: {e}")
        return None


_EMOJI_NATIVE = 109
_emoji_cache: dict = {}


def _render_emoji_glyph(ch: str, emoji_font, target: int):
    key = (ch, target)
    if key in _emoji_cache:
        return _emoji_cache[key]
    try:
        canvas = Image.new("RGBA", (_EMOJI_NATIVE, _EMOJI_NATIVE), (0, 0, 0, 0))
        ImageDraw.Draw(canvas).text((0, 0), ch, font=emoji_font, embedded_color=True)
        bbox = canvas.getbbox()
        if bbox:
            canvas = canvas.crop(bbox)
        out = canvas.resize((target, target), Image.LANCZOS)
        _emoji_cache[key] = out
        return out
    except Exception as e:
        logger.debug(f"emoji glyph failed {ch!r}: {e}")
        _emoji_cache[key] = None
        return None


def _segment(text: str):
    parts = _EMOJI_RE.split(text)
    segs = []
    for part in parts:
        if not part:
            continue
        is_emoji = bool(_EMOJI_RE.fullmatch(part))
        if segs and segs[-1][1] == is_emoji:
            segs[-1] = (segs[-1][0] + part, is_emoji)
        else:
            segs.append((part, is_emoji))
    return segs


def _seg_width(segs, tf, ef, size, dd):
    total = 0
    for chunk, is_emoji in segs:
        if is_emoji and ef:
            total += int(size * 1.15) * len(chunk)
        else:
            bb = dd.textbbox((0, 0), chunk, font=tf)
            total += bb[2] - bb[0]
    return total


def _draw_segmented(draw, x, y, line, tf, ef, size, color, card):
    epx = int(size * 1.15)
    for chunk, is_emoji in _segment(line):
        if is_emoji and ef and card is not None:
            for ch in chunk:
                g = _render_emoji_glyph(ch, ef, epx)
                if g:
                    card.paste(g, (int(x), int(y + (size - epx) * 0.15)), g)
                x += epx
        elif is_emoji:
            x += epx * len(chunk)
        else:
            draw.text((x, y), chunk, font=tf, fill=color)
            bb = draw.textbbox((0, 0), chunk, font=tf)
            x += bb[2] - bb[0]
    return x


def _wrap(text: str, tf, ef, size, max_w, dd):
    """Word-wrap, preserving explicit newlines."""
    out = []
    for para in text.split("\n"):
        words = para.split(" ")
        cur = ""
        for w in words:
            trial = (cur + " " + w).strip()
            if _seg_width(_segment(trial), tf, ef, size, dd) <= max_w:
                cur = trial
            else:
                if cur:
                    out.append(cur)
                cur = w
        out.append(cur)
    return out or [""]


def _fit(text, dd, ef, max_w, max_h, devanagari):
    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        tf = _pick_text_font(size, devanagari=devanagari)
        lh = dd.textbbox((0, 0), "Ay", font=tf)[3] + 8
        lines = _wrap(text, tf, ef, size, max_w, dd)
        if lh * len(lines) <= max_h:
            return tf, size, lines, lh
    size = MIN_FONT_SIZE
    tf = _pick_text_font(size, devanagari=devanagari)
    lh = dd.textbbox((0, 0), "Ay", font=tf)[3] + 8
    lines = _wrap(text, tf, ef, size, max_w, dd)
    max_lines = max(1, max_h // lh)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and _seg_width(_segment(last + "…"), tf, ef, size, dd) > max_w:
            last = last[:-1]
        lines[-1] = last + "…"
    return tf, size, lines, lh


def _draw_avatar(card, avatar_bytes, letter, color, x, y):
    mask = Image.new("L", (AVATAR_SIZE, AVATAR_SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=255)
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA") \
                     .resize((AVATAR_SIZE, AVATAR_SIZE))
            card.paste(av, (x, y), mask)
            return
        except Exception:
            pass
    circle = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), color)
    d = ImageDraw.Draw(circle)
    font = _pick_text_font(int(AVATAR_SIZE * 0.45), bold=True)
    bb = d.textbbox((0, 0), letter, font=font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    d.text(((AVATAR_SIZE - tw) / 2 - bb[0], (AVATAR_SIZE - th) / 2 - bb[1]),
           letter, font=font, fill=(255, 255, 255, 255))
    card.paste(circle, (x, y), mask)


def render_quote_card(messages, avatar_bytes, theme="dark", mode="sticker",
                      reply_preview=None):
    """
    Render a quote card.

    messages:     list of {"name","text","uid"} (oldest-last or single).
    avatar_bytes: raw bytes of the primary sender's PFP (or None).
    theme:        'dark'|'light'|'white'|'purple'|'blue'|'color #rrggbb'.
    mode:         'sticker' (512x512 WEBP) or 'png' (PNG image).
    reply_preview: optional {"name","text"} for a nested reply snippet.

    Returns raw image bytes. Raises QuoteRenderError for bad input.
    """
    if not messages:
        raise QuoteRenderError("❌ Nothing to quote.")

    pal = _parse_theme(theme)
    primary = messages[0]
    name = _fix_smallcaps((primary.get("name") or "User").strip()) or "User"
    single = len(messages) == 1

    # Build the body text. Single message: just the text. Thread: each
    # message labelled with its sender so multi-quotes stay readable.
    if single:
        body_source = primary["text"]
    else:
        body_source = "\n".join(f"{m['name']}: {m['text']}" for m in messages)

    if not body_source or not body_source.strip():
        raise QuoteRenderError("❌ That message has no text to quote.")
    body_source = _fix_smallcaps(body_source.strip())

    ef = _pick_emoji_font()
    deva = _has_devanagari(body_source) or _has_devanagari(name)

    # ── Layout: compute a tightly-fitting card height ───────────────────
    header_h = AVATAR_SIZE
    reply_h = 0
    if reply_preview:
        reply_h = 34  # one compact line for the nested reply
    text_top = INSET + PADDING + header_h + 14 + reply_h + 8
    body_max_w = CARD_W - 2 * (PADDING + INSET)

    # First pass on a scratch canvas to measure.
    scratch = Image.new("RGBA", (CARD_W, CARD_W))
    dd = ImageDraw.Draw(scratch)
    max_body_h = (512 if mode == "sticker" else 900) - text_top - PADDING - INSET
    tf, size, lines, lh = _fit(body_source, dd, ef, body_max_w, max_body_h, deva)

    card_h = max(512, text_top + lh * len(lines) + PADDING + INSET)
    card = Image.new("RGBA", (CARD_W, card_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    # Rounded background
    draw.rounded_rectangle(
        (INSET, INSET, CARD_W - INSET, card_h - INSET),
        radius=30, fill=pal["bg"], outline=pal["border"], width=4,
    )

    # Avatar
    av_x = PADDING + INSET
    av_y = PADDING + INSET
    letter = (name[:1] or "?").upper()
    _draw_avatar(card, avatar_bytes, letter, pal["accent"], av_x, av_y)

    # Name
    nf = _pick_text_font(NAME_FONT_SIZE, bold=True, devanagari=_has_devanagari(name))
    nef = _pick_emoji_font()
    name_x = av_x + AVATAR_SIZE + 14
    name_y = av_y + (AVATAR_SIZE - NAME_FONT_SIZE) // 2 - 2
    max_name_w = CARD_W - name_x - PADDING - INSET
    disp = name
    while disp and _seg_width(_segment(disp), nf, nef, NAME_FONT_SIZE, draw) > max_name_w:
        disp = disp[:-1]
    if disp != name:
        disp = disp.rstrip() + "…"
    _draw_segmented(draw, name_x, name_y, disp, nf, nef, NAME_FONT_SIZE, pal["name"], card)

    # Reply preview (nested quote)
    cur_y = av_y + AVATAR_SIZE + 12
    if reply_preview:
        rp = _fix_smallcaps((reply_preview.get("text") or "").strip())
        rp_name = _fix_smallcaps((reply_preview.get("name") or "Someone").strip())
        if rp:
            rp_font = _pick_text_font(16, devanagari=_has_devanagari(rp))
            rmax = CARD_W - 2 * (PADDING + INSET) - 10
            rp_lines = _wrap("↩ " + rp_name + ": " + rp, rp_font, ef, 16, rmax, dd)[:1]
            rp_text = rp_lines[0]
            # indent + light vertical bar
            draw.line((PADDING + INSET, cur_y - 4, PADDING + INSET, cur_y + 16),
                      fill=pal["divider"], width=3)
            _draw_segmented(draw, PADDING + INSET + 10, cur_y, rp_text,
                            rp_font, ef, 16, pal["divider"], card)
            cur_y += 30

    # Divider under the header/reply area
    div_y = cur_y + 2
    draw.line((PADDING + INSET, div_y, CARD_W - PADDING - INSET, div_y),
              fill=pal["divider"], width=1)

    # Message body
    y = float(div_y + 14)
    for line in lines:
        _draw_segmented(draw, float(PADDING + INSET), y, line, tf, ef, size, pal["text"], card)
        y += lh

    buf = io.BytesIO()
    if mode == "sticker":
        # Stickers must be exactly 512x512 — composite the card centered.
        out = Image.new("RGBA", (CARD_W, CARD_W), (0, 0, 0, 0))
        paste_y = max(0, (CARD_W - card_h) // 2)
        out.paste(card, (0, paste_y), card)
        out.save(buf, format="WEBP", lossless=True)
    else:
        card.save(buf, format="PNG")
    return buf.getvalue()
