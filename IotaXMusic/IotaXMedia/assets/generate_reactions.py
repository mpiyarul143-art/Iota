# Authored By Iota Coders © 2025
"""
Generate offline fallback reaction GIFs for the role-play commands.

These are bundled inside the repo (IotaXMedia/assets/reactions/*.gif) so the
/slap /kiss /hug ... commands never fail with "Couldn't fetch the animation"
even when the bot runs in an environment with no/limited outbound internet
(e.g. blocked DNS for api.waifu.pics / nekos.best). Network sources are still
tried first at runtime; this is only the guaranteed last-resort fallback.
"""
import os
import math
import colorsys

from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.join(os.path.dirname(__file__), "reactions")
SIZE = 240
FRAMES = 24

# (action, emoji, verb) — emoji kept for reference; we render the verb text
# and a moving shape (robust without a color-emoji font).
ACTIONS = [
    ("punch", "💥", "PUNCH"),
    ("slap", "😒", "SLAP"),
    ("hug", "🤗", "HUG"),
    ("bite", "😈", "BITE"),
    ("kiss", "😘", "KISS"),
    ("highfive", "🙌", "HIGH FIVE"),
    ("shoot", "🔫", "SHOOT"),
    ("dance", "💃", "DANCE"),
    ("happy", "😊", "HAPPY"),
    ("baka", "😡", "BAKA"),
    ("pat", "👋", "PAT"),
    ("nod", "👍", "NOD"),
    ("nope", "👎", "NOPE"),
    ("cuddle", "🤗", "CUDDLE"),
    ("feed", "🍴", "FEED"),
    ("bored", "😴", "BORED"),
    ("nom", "😋", "NOM"),
    ("yawn", "😪", "YAWN"),
    ("facepalm", "🤦", "FACEPALM"),
    ("tickle", "😆", "TICKLE"),
    ("yeet", "💨", "YEET"),
    ("think", "🤔", "THINK"),
    ("blush", "😊", "BLUSH"),
    ("smug", "😏", "SMUG"),
    ("wink", "😉", "WINK"),
    ("peck", "😘", "PECK"),
    ("smile", "😄", "SMILE"),
    ("wave", "👋", "WAVE"),
    ("poke", "👉", "POKE"),
    ("stare", "👀", "STARE"),
    ("shrug", "🤷", "SHRUG"),
    ("sleep", "😴", "SLEEP"),
    ("lurk", "👤", "LURK"),
]


def _find_font(size: int) -> ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _color_for(seed: str):
    h = sum(ord(c) for c in seed) % 360
    r, g, b = colorsys.hsv_to_rgb(h / 360.0, 0.55, 0.95)
    return (int(r * 255), int(g * 255), int(b * 255))


def make_gif(action: str, verb: str):
    bg = _color_for(action)
    fg = (255, 255, 255)
    accent = (255, 255, 255)
    font_big = _find_font(46)
    font_small = _find_font(22)

    frames = []
    cx, cy = SIZE // 2, SIZE // 2
    for i in range(FRAMES):
        t = i / FRAMES
        angle = t * 2 * math.pi
        img = Image.new("RGB", (SIZE, SIZE), bg)
        d = ImageDraw.Draw(img)

        # moving accent shape (circle) that flies in and bounces
        ox = int(math.sin(angle) * 40)
        oy = int(math.cos(angle * 2) * 30)
        r = 34
        d.ellipse(
            [cx + ox - r, cy + oy - r, cx + ox + r, cy + oy + r],
            outline=accent,
            width=6,
        )

        # pulsing verb text
        scale = 1.0 + 0.12 * math.sin(angle)
        w = d.textlength(verb, font=font_big) * scale if hasattr(d, "textlength") else 120
        # draw verb centered
        d.text((cx - w / 2, cy - 90), verb, font=font_big, fill=fg)
        d.text((cx - 40, cy + 70), "~ Iota ~", font=font_small, fill=fg)

        frames.append(img)

    path = os.path.join(OUT_DIR, f"{action}.gif")
    frames[0].save(
        path,
        save_all=True,
        append_images=frames[1:],
        duration=70,
        loop=0,
        optimize=False,
    )
    return path


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for action, emoji, verb in ACTIONS:
        p = make_gif(action, verb)
        print("generated", os.path.basename(p))
    print(f"Done. {len(ACTIONS)} GIFs in {OUT_DIR}")


if __name__ == "__main__":
    main()
