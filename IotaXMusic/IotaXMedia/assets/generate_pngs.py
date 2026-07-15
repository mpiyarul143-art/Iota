# Authored By Iota Coders © 2025
"""
Regenerate Iota Music Bot PNG assets in the new "Iota ✘ Music" style.

Run:  python3 IotaXMedia/assets/generate_pngs.py

All outputs keep their ORIGINAL dimensions so nothing breaks:
  • welcome.png  (2880x1620)  – welcome-card background
  • couple.png   (2288x1496)  – couple-photo frame/background
  • upic.png     (500x500)     – fallback avatar (becomes a circle)
  • tiny.png     (500x200)     – banner pasted behind /tiny stickers
  • play_icons.png (721x78)    – player-control glyph strip (silhouetted)
"""
import os
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ARIMO = os.path.join(HERE, "iota", "Arimo.ttf")

# ── palette (new Iota style: dark neon on indigo/purple) ────────────────
INDIGO = (11, 11, 26)
PLUM = (27, 16, 53)
PURPLE = (45, 27, 78)
CYAN = (24, 224, 255)
MAGENTA = (255, 61, 240)
WHITE = (255, 255, 255)
SOFT = (237, 230, 255)


def fnt(size):
    return ImageFont.truetype(ARIMO, size)


def gradient(w, h, c1, c2, diag=True):
    img = Image.new("RGBA", (w, h))
    p = img.load()
    for y in range(h):
        for x in range(w):
            t = ((x / w + y / h) / 2) if diag else (y / h)
            p[x, y] = (
                int(c1[0] + (c2[0] - c1[0]) * t),
                int(c1[1] + (c2[1] - c1[1]) * t),
                int(c1[2] + (c2[2] - c1[2]) * t),
                255,
            )
    return img


def radial_glow(img, cx, cy, radius, color, max_alpha=110):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    steps = 26
    for i in range(steps, 0, -1):
        r = radius * i / steps
        a = int(max_alpha * (1 - i / steps))
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color + (a,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(50)))


def glow_text(img, xy, text, fo, main, glow, blur=18, strength=2):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=fo, fill=glow + (255,))
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    for _ in range(strength):
        img.alpha_composite(layer)
    ImageDraw.Draw(img).text(xy, text, font=fo, fill=main + (255,))


def center_text(img, text, y, size, main, glow, blur=18):
    fo = fnt(size)
    bbox = ImageDraw.Draw(img).textbbox((0, 0), text, font=fo)
    w = bbox[2] - bbox[0]
    glow_text(img, ((img.width - w) // 2, y), text, fo, main, glow, blur)


def draw_note(img, x, y, size, color, alpha=70):
    d = ImageDraw.Draw(img)
    r = max(4, size // 6)
    d.ellipse([x - r, y + size // 2, x + r, y + size // 2 + 2 * r],
              fill=color + (alpha,))
    d.line([x + r, y + size // 2, x + r, y], fill=color + (alpha,),
           width=max(2, size // 28))


def scatter_notes(img, spots, color, alpha=55):
    for (x, y, s) in spots:
        draw_note(img, x, y, s, color, alpha)


# ── 1) welcome.png ──────────────────────────────────────────────────────
def make_welcome():
    W, H = 2880, 1620
    img = gradient(W, H, INDIGO, PLUM, diag=True)
    radial_glow(img, 2300, 700, 900, CYAN, 90)
    radial_glow(img, 500, 1400, 800, MAGENTA, 80)
    scatter_notes(img, [
        (300, 200, 120), (2600, 200, 140), (200, 900, 100),
        (2700, 1100, 120), (1500, 200, 90), (1500, 1450, 110),
    ], CYAN, 50)
    # top brand
    center_text(img, "IOTA ✘ MUSIC", 110, 150, WHITE, CYAN, 22)
    center_text(img, "✦  W E L C O M E  ✦", 300, 70, SOFT, MAGENTA, 14)
    # bottom tag
    center_text(img, "ᴘᴏᴡᴇʀᴇᴅ ʙʏ ɪᴏᴛᴀ ᴍᴜsɪᴄ ʙᴏᴛ", H - 130, 52, SOFT, CYAN, 10)
    # faint centered watermark
    fo = fnt(420)
    bbox = ImageDraw.Draw(img).textbbox((0, 0), "IOTA", font=fo)
    w = bbox[2] - bbox[0]
    glow_text(img, ((W - w) // 2, 560), "IOTA", fo, (255, 255, 255), CYAN, 40, 1)
    img.save(os.path.join(HERE, "iota", "welcome.png"))
    print("welcome.png done")


# ── 2) couple.png ───────────────────────────────────────────────────────
def make_couple():
    W, H = 2288, 1496
    img = gradient(W, H, (24, 12, 44), (48, 22, 74), diag=True)
    radial_glow(img, 520, 300, 800, MAGENTA, 90)
    radial_glow(img, 1780, 1250, 800, CYAN, 90)
    scatter_notes(img, [
        (120, 200, 110), (2100, 200, 120), (120, 1250, 100),
        (2100, 1250, 110), (1140, 120, 90), (1140, 1380, 90),
    ], MAGENTA, 45)
    # guide frames where the two circular photos are pasted
    d = ImageDraw.Draw(img)
    for (cx, cy) in [(827, 919), (1812, 919)]:
        d.ellipse([cx - 430, cy - 430, cx + 430, cy + 430],
                  outline=CYAN + (180,), width=10)
        d.ellipse([cx - 448, cy - 448, cx + 448, cy + 448],
                  outline=MAGENTA + (120,), width=4)
    center_text(img, "IOTA ✘ MUSIC", 60, 96, WHITE, CYAN, 18)
    center_text(img, "💞 ᴄᴏᴜᴘʟᴇ ᴏꜰ ᴛʜᴇ ᴅᴀʏ 💞", H - 150, 60, SOFT, MAGENTA, 12)
    img.save(os.path.join(HERE, "iota", "couple.png"))
    print("couple.png done")


# ── 3) upic.png (becomes a circle) ──────────────────────────────────────
def make_upic():
    W = H = 500
    img = gradient(W, H, (20, 14, 40), (40, 20, 70), diag=False)
    radial_glow(img, 250, 250, 360, MAGENTA, 90)
    radial_glow(img, 150, 150, 260, CYAN, 70)
    draw_note(img, 70, 70, 120, CYAN, 80)
    draw_note(img, 360, 320, 110, MAGENTA, 80)
    center_text(img, "IOTA", 175, 96, WHITE, CYAN, 16)
    center_text(img, "♪ ✘ ♪", 300, 50, SOFT, MAGENTA, 10)
    img.save(os.path.join(HERE, "upic.png"))
    print("upic.png done")


# ── 4) tiny.png (banner behind /tiny stickers) ──────────────────────────
def make_tiny():
    W, H = 500, 200
    img = gradient(W, H, (14, 10, 30), (40, 18, 64), diag=True)
    radial_glow(img, 380, 100, 260, CYAN, 90)
    radial_glow(img, 120, 160, 220, MAGENTA, 70)
    # frame where the pasted sticker sits (top-left ~200x200)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([10, 10, 190, 190], radius=18,
                        outline=CYAN + (170,), width=4)
    center_text(img, "IOTA ✘", 60, 64, WHITE, CYAN, 14)
    center_text(img, "MUSIC", 130, 56, SOFT, MAGENTA, 12)
    img.save(os.path.join(HERE, "tiny.png"))
    print("tiny.png done")


# ── 5) play_icons.png (control-glyph strip) ─────────────────────────────
def _glyph(d, kind, cx, cy, s, col):
    hw = s / 2  # half
    if kind == "play":
        d.polygon([(cx - hw * 0.5, cy - hw * 0.6), (cx - hw * 0.5, cy + hw * 0.6),
                   (cx + hw * 0.6, cy)], fill=col)
    elif kind == "pause":
        d.rectangle([cx - hw * 0.55, cy - hw * 0.6, cx - hw * 0.15, cy + hw * 0.6], fill=col)
        d.rectangle([cx + hw * 0.15, cy - hw * 0.6, cx + hw * 0.55, cy + hw * 0.6], fill=col)
    elif kind == "prev":
        d.polygon([(cx + hw * 0.5, cy - hw * 0.6), (cx + hw * 0.5, cy + hw * 0.6),
                   (cx - hw * 0.6, cy)], fill=col)
        d.rectangle([cx - hw * 0.7, cy - hw * 0.6, cx - hw * 0.5, cy + hw * 0.6], fill=col)
    elif kind == "next":
        d.polygon([(cx - hw * 0.5, cy - hw * 0.6), (cx - hw * 0.5, cy + hw * 0.6),
                   (cx + hw * 0.6, cy)], fill=col)
        d.rectangle([cx + hw * 0.5, cy - hw * 0.6, cx + hw * 0.7, cy + hw * 0.6], fill=col)
    elif kind == "stop":
        d.rounded_rectangle([cx - hw * 0.55, cy - hw * 0.55, cx + hw * 0.55, cy + hw * 0.55],
                            radius=8, fill=col)
    elif kind == "heart":
        r = hw * 0.42
        d.ellipse([cx - hw * 0.5, cy - hw * 0.55, cx - hw * 0.5 + 2 * r, cy - hw * 0.55 + 2 * r], fill=col)
        d.ellipse([cx + hw * 0.5 - 2 * r, cy - hw * 0.55, cx + hw * 0.5, cy - hw * 0.55 + 2 * r], fill=col)
        d.polygon([(cx - hw * 0.5, cy - hw * 0.05), (cx + hw * 0.5, cy - hw * 0.05),
                   (cx, cy + hw * 0.6)], fill=col)
    elif kind == "shuffle":
        d.line([cx - hw * 0.6, cy - hw * 0.4, cx + hw * 0.6, cy + hw * 0.4], fill=col, width=8)
        d.line([cx - hw * 0.6, cy + hw * 0.4, cx + hw * 0.6, cy - hw * 0.4], fill=col, width=8)
        d.polygon([(cx + hw * 0.6, cy + hw * 0.4), (cx + hw * 0.35, cy + hw * 0.4),
                   (cx + hw * 0.6, cy + hw * 0.15)], fill=col)
        d.polygon([(cx + hw * 0.6, cy - hw * 0.4), (cx + hw * 0.35, cy - hw * 0.4),
                   (cx + hw * 0.6, cy - hw * 0.15)], fill=col)
    elif kind == "repeat":
        d.arc([cx - hw * 0.55, cy - hw * 0.55, cx + hw * 0.55, cy + hw * 0.55],
              200, 340, fill=col, width=8)
        d.polygon([(cx + hw * 0.55, cy - hw * 0.55), (cx + hw * 0.3, cy - hw * 0.55),
                   (cx + hw * 0.55, cy - hw * 0.3)], fill=col)
    elif kind == "volume":
        d.polygon([(cx - hw * 0.6, cy - hw * 0.25), (cx - hw * 0.2, cy - hw * 0.25),
                   (cx + hw * 0.1, cy - hw * 0.55), (cx + hw * 0.1, cy + hw * 0.55),
                   (cx - hw * 0.2, cy + hw * 0.25)], fill=col)
        d.arc([cx + hw * 0.1, cy - hw * 0.45, cx + hw * 0.6, cy + hw * 0.45],
              330, 30, fill=col, width=6)
    else:
        d.ellipse([cx - hw * 0.5, cy - hw * 0.5, cx + hw * 0.5, cy + hw * 0.5], fill=col)


def make_play_icons():
    W, H = 721, 78
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    kinds = ["shuffle", "prev", "play", "pause", "next", "repeat", "heart", "volume", "stop"]
    n = len(kinds)
    cell = W / n
    s = H * 0.86
    for i, k in enumerate(kinds):
        cx = int(cell * (i + 0.5))
        cy = H // 2
        _glyph(d, k, cx, cy, s, WHITE + (255,))
    img.save(os.path.join(HERE, "thumb", "play_icons.png"))
    print("play_icons.png done")


if __name__ == "__main__":
    make_welcome()
    make_couple()
    make_upic()
    make_tiny()
    make_play_icons()
    print("All Iota PNG assets regenerated.")
