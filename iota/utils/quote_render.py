"""
Iota Bot — Quote Sticker Renderer (/q)

COMPLETE REWRITE — now matches Baka-style output:
- Full-color emoji rendering (NotoColorEmoji) — no more tofu boxes
- ❌ ✦ 🎉 etc. all render correctly in the sticker
- Mixed emoji+text in one pass using a segmented draw approach
- Better visual hierarchy and proportions

HOW EMOJI RENDERING WORKS:
Pillow's FreeType backend supports CBDT/SBIX (color bitmap) emoji glyphs
via the `embedded_color=True` flag on draw.text() — but ONLY if the font
file actually has them. NotoColorEmoji.ttf does, and it's available on
most Linux servers (including this bot's likely hosts). The catch: you
can't mix NotoColorEmoji with a text font in a single draw.text() call —
they have completely different metrics. Instead we split each line into
emoji runs and text runs, draw them separately with their respective
fonts, and advance the x cursor between segments. This is the same
approach used by most serious Telegram quote-sticker bots.
"""
import io
import re
import logging

from PIL import Image, ImageDraw, ImageFont

from utils.font_manager import load_font

logger = logging.getLogger(__name__)

CARD_SIZE = 512
PADDING = 28
AVATAR_SIZE = 80
MAX_FONT_SIZE = 38
MIN_FONT_SIZE = 17
NAME_FONT_SIZE = 26

_BG_COLOR         = (28, 30, 46, 255)   # deep dark blue-slate
_BORDER_COLOR     = (255, 182, 72, 255)  # warm amber
_NAME_COLOR       = (255, 182, 72, 255)
_TEXT_COLOR       = (238, 234, 220, 255)
_DIVIDER_COLOR    = (60, 63, 82, 255)
_AVATAR_COLORS    = [
    (239, 83,  80,  255), (66,  165, 245, 255), (102, 187, 106, 255),
    (255, 202, 40,  255), (171, 71,  188, 255), (255, 112, 67,  255),
    (38,  198, 218, 255), (236, 64,  122, 255),
]

# NotoColorEmoji path — present on most Linux distros, including Ubuntu
# and Debian (used on most VPS hosts). If not found, emoji are stripped
# and only text is rendered (never a crash, just a missing icon).
_EMOJI_FONT_PATH = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

# Emoji Unicode ranges — used to split text into emoji vs text segments
_EMOJI_RE = re.compile(
    "("
    "[\U0001F300-\U0001FAFF]"   # misc symbols, pictographs, emoticons
    "|[\U0001F1E0-\U0001F1FF]"  # flags
    "|[\u2600-\u27BF]"          # misc symbols & dingbats (includes ❌ ✦ etc.)
    "|[\u2B00-\u2BFF]"          # misc symbols & arrows
    "|[\u2190-\u21FF]"          # arrows
    "|[\uFE00-\uFE0F]"          # variation selectors
    "|\u200D"                   # ZWJ
    "|[\u20E3]"                 # combining enclosing keycap
    ")",
    flags=re.UNICODE,
)

# smallcaps characters that NotoSans/DejaVu can't render → plain equivalents
_SMALLCAPS_FIX = {"\uA730": "F", "\uA731": "S"}


class QuoteRenderError(Exception):
    pass


def _fix_smallcaps(text: str) -> str:
    for bad, good in _SMALLCAPS_FIX.items():
        text = text.replace(bad, good)
    return text


def _has_devanagari(text: str) -> bool:
    return any('\u0900' <= ch <= '\u097F' for ch in text)


def _pick_text_font(size: int, bold: bool = False, devanagari: bool = False):
    if devanagari:
        name = "NotoSansDevanagari-Bold.ttf" if bold else "NotoSansDevanagari-Regular.ttf"
    else:
        name = "NotoSans-Bold.ttf" if bold else "NotoSans-Regular.ttf"
    font = load_font(name, size)
    return font or ImageFont.load_default()


def _pick_emoji_font(size: int):
    """
    Load NotoColorEmoji. This font is a color BITMAP font (CBDT/CBLC) —
    it does NOT support arbitrary point sizes like a normal vector font;
    Pillow can only load it at its one native embedded size (109px on
    the standard Noto Color Emoji build). Requesting any other size
    raises "invalid pixel size". So we always load at 109 here, and the
    caller is responsible for resizing the rendered glyph image itself
    (see _render_emoji_glyph) to fit the actual target text size.
    """
    import os
    if not os.path.exists(_EMOJI_FONT_PATH):
        return None
    try:
        return ImageFont.truetype(_EMOJI_FONT_PATH, 109)
    except Exception as e:
        logger.debug(f"emoji font load failed: {e}")
        return None


_EMOJI_NATIVE_SIZE = 109
_emoji_glyph_cache: dict = {}


def _render_emoji_glyph(emoji_char: str, emoji_font, target_size: int):
    """
    Renders a single emoji character to its own small RGBA image at
    `target_size`x`target_size`, using NotoColorEmoji at its native
    109px size then downscaling. Cached per (char, size) since the
    same emoji is drawn repeatedly across a chat's stickers.
    Returns None if rendering fails (caller should just skip it).
    """
    cache_key = (emoji_char, target_size)
    if cache_key in _emoji_glyph_cache:
        return _emoji_glyph_cache[cache_key]
    try:
        canvas = Image.new("RGBA", (_EMOJI_NATIVE_SIZE, _EMOJI_NATIVE_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(canvas)
        d.text((0, 0), emoji_char, font=emoji_font, embedded_color=True)
        # Crop to actual ink bounding box so spacing looks natural
        bbox = canvas.getbbox()
        if bbox:
            canvas = canvas.crop(bbox)
        resized = canvas.resize((target_size, target_size), Image.LANCZOS)
        _emoji_glyph_cache[cache_key] = resized
        return resized
    except Exception as e:
        logger.debug(f"_render_emoji_glyph failed for {emoji_char!r}: {e}")
        _emoji_glyph_cache[cache_key] = None
        return None


def _segment(text: str) -> list[tuple[str, bool]]:
    """Split `text` into [(chunk, is_emoji), ...] segments."""
    parts = _EMOJI_RE.split(text)
    segments = []
    for part in parts:
        if not part:
            continue
        is_emoji = bool(_EMOJI_RE.fullmatch(part))
        if segments and segments[-1][1] == is_emoji:
            segments[-1] = (segments[-1][0] + part, is_emoji)
        else:
            segments.append((part, is_emoji))
    return segments


def _segment_width(segments: list, text_font, emoji_font, size: int,
                   dummy_draw: ImageDraw.ImageDraw) -> int:
    """Total pixel width of a list of segments."""
    total = 0
    for chunk, is_emoji in segments:
        if is_emoji and emoji_font:
            # Each emoji codepoint is approximately size*1.1 pixels wide
            total += int(size * 1.1) * len(chunk)
        else:
            bb = dummy_draw.textbbox((0, 0), chunk, font=text_font)
            total += bb[2] - bb[0]
    return total


def _draw_segmented_line(draw: ImageDraw.ImageDraw, x: float, y: float,
                          line: str, text_font, emoji_font, size: int,
                          text_color: tuple, card: Image.Image = None) -> float:
    """
    Draw a mixed emoji+text line, returning the x position after drawing.
    `card` (the actual target image) is needed to paste rendered emoji
    glyphs — draw.text() alone can't place a color bitmap glyph at an
    arbitrary size, so emoji are rendered separately and pasted.
    """
    emoji_px = int(size * 1.15)
    for chunk, is_emoji in _segment(line):
        if is_emoji and emoji_font and card is not None:
            for ch in chunk:
                glyph = _render_emoji_glyph(ch, emoji_font, emoji_px)
                if glyph:
                    paste_y = int(y + (size - emoji_px) * 0.15)
                    card.paste(glyph, (int(x), paste_y), glyph)
                x += emoji_px
        elif is_emoji:
            # No emoji font available — skip silently rather than show tofu
            x += emoji_px * len(chunk)
        else:
            draw.text((x, y), chunk, font=text_font, fill=text_color)
            bb = draw.textbbox((0, 0), chunk, font=text_font)
            x += bb[2] - bb[0]
    return x


def _wrap_segmented(text: str, text_font, emoji_font, font_size: int,
                     max_width: int, dummy_draw: ImageDraw.ImageDraw) -> list[str]:
    """Word-wrap text respecting the mixed emoji+text width calculation."""
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        segs = _segment(trial)
        w = _segment_width(segs, text_font, emoji_font, font_size, dummy_draw)
        if w <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _fit_text_segmented(text: str, draw: ImageDraw.ImageDraw,
                         emoji_font_base, max_width: int, max_height: int,
                         devanagari: bool) -> tuple:
    """Find font size + wrapped lines that fit in max_width x max_height."""
    for size in range(MAX_FONT_SIZE, MIN_FONT_SIZE - 1, -2):
        tf = _pick_text_font(size, devanagari=devanagari)
        ef = _pick_emoji_font(size) if emoji_font_base else None
        lines = _wrap_segmented(text, tf, ef, size, max_width, draw)
        lh = draw.textbbox((0, 0), "Ay", font=tf)[3] + 8
        if lh * len(lines) <= max_height:
            return tf, ef, size, lines, lh
    # Fallback: smallest size, truncate
    size = MIN_FONT_SIZE
    tf = _pick_text_font(size, devanagari=devanagari)
    ef = _pick_emoji_font(size) if emoji_font_base else None
    lh = draw.textbbox((0, 0), "Ay", font=tf)[3] + 8
    max_lines = max(1, max_height // lh)
    lines = _wrap_segmented(text, tf, ef, size, max_width, draw)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        last = lines[-1]
        while last and _segment_width(_segment(last + "…"), tf, ef, size, draw) > max_width:
            last = last[:-1]
        lines[-1] = last + "…"
    return tf, ef, size, lines, lh


def _draw_avatar(card: Image.Image, avatar_img, letter: str,
                 color: tuple, x: int, y: int):
    mask = Image.new("L", (AVATAR_SIZE, AVATAR_SIZE), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, AVATAR_SIZE, AVATAR_SIZE), fill=255)

    if avatar_img:
        av = avatar_img.convert("RGBA").resize((AVATAR_SIZE, AVATAR_SIZE))
        card.paste(av, (x, y), mask)
    else:
        circle = Image.new("RGBA", (AVATAR_SIZE, AVATAR_SIZE), color)
        d = ImageDraw.Draw(circle)
        font = _pick_text_font(int(AVATAR_SIZE * 0.45), bold=True)
        bb = d.textbbox((0, 0), letter, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        d.text(((AVATAR_SIZE - tw) / 2 - bb[0], (AVATAR_SIZE - th) / 2 - bb[1]),
               letter, font=font, fill=(255, 255, 255, 255))
        card.paste(circle, (x, y), mask)


def render_quote_sticker(name: str, text: str, avatar_bytes, uid: int) -> bytes:
    """
    Renders name + text into a 512x512 WEBP sticker with:
    - Full-color emoji (NotoColorEmoji)
    - Circular avatar or colored-initial fallback
    - Auto word-wrap and font-size shrink to fit
    Returns raw bytes ready to pass to bot.send_sticker().
    Raises QuoteRenderError for truly un-renderable input.
    """
    if not text or not text.strip():
        raise QuoteRenderError("❌ Reply to a text message.")

    # Normalize smallcaps-only glyphs that NotoSans can't draw
    text = _fix_smallcaps(text.strip())
    name = _fix_smallcaps((name or "User").strip()) or "User"

    card = Image.new("RGBA", (CARD_SIZE, CARD_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(card)

    # Rounded card background
    inset = 10
    draw.rounded_rectangle(
        (inset, inset, CARD_SIZE - inset, CARD_SIZE - inset),
        radius=30, fill=_BG_COLOR, outline=_BORDER_COLOR, width=4
    )

    # Avatar
    avatar_img = None
    if avatar_bytes:
        try:
            avatar_img = Image.open(io.BytesIO(avatar_bytes))
        except Exception:
            avatar_img = None

    av_x = PADDING + inset
    av_y = PADDING + inset
    fallback_letter = (name[:1] or "?").upper()
    fallback_color = _AVATAR_COLORS[uid % len(_AVATAR_COLORS)]
    _draw_avatar(card, avatar_img, fallback_letter, fallback_color, av_x, av_y)

    # Name (with emoji support)
    name_font = _pick_text_font(NAME_FONT_SIZE, bold=True, devanagari=_has_devanagari(name))
    name_emoji_font = _pick_emoji_font(NAME_FONT_SIZE)
    name_x = av_x + AVATAR_SIZE + 14
    name_y = av_y + (AVATAR_SIZE - NAME_FONT_SIZE) // 2 - 2
    max_name_w = CARD_SIZE - name_x - PADDING - inset
    # Truncate name if too wide
    display_name = name
    while (display_name and
           _segment_width(_segment(display_name), name_font, name_emoji_font,
                          NAME_FONT_SIZE, draw) > max_name_w):
        display_name = display_name[:-1]
    if display_name != name:
        display_name = display_name.rstrip() + "…"
    _draw_segmented_line(draw, name_x, name_y, display_name,
                          name_font, name_emoji_font, NAME_FONT_SIZE, _NAME_COLOR, card)

    # Thin divider under the name/avatar row
    div_y = av_y + AVATAR_SIZE + 12
    draw.line(
        (PADDING + inset, div_y, CARD_SIZE - PADDING - inset, div_y),
        fill=_DIVIDER_COLOR, width=1
    )

    # Message text
    text_top = div_y + 14
    text_max_w = CARD_SIZE - 2 * (PADDING + inset)
    text_max_h = CARD_SIZE - text_top - PADDING - inset

    emoji_font_available = _pick_emoji_font(MAX_FONT_SIZE) is not None
    tf, ef, size, lines, lh = _fit_text_segmented(
        text, draw, emoji_font_available, text_max_w, text_max_h, _has_devanagari(text)
    )

    y = float(text_top)
    for line in lines:
        _draw_segmented_line(draw, float(PADDING + inset), y,
                              line, tf, ef, size, _TEXT_COLOR, card)
        y += lh

    buf = io.BytesIO()
    card.save(buf, format="WEBP", lossless=True)
    return buf.getvalue()
