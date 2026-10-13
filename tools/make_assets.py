"""Generates assets/lavati.ico and the installer wizard bitmaps (run once; outputs are committed)."""
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS = os.path.join(ROOT, "fonts")
AMBER, AMBER_D = (245, 166, 35), (214, 126, 14)
INK = (20, 22, 28)
BG_TOP, BG_BOT = (27, 30, 36), (11, 13, 16)


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, name), size)


def vgrad(w, h, a, b):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        c = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
        for x in range(w):
            px[x, y] = c
    return img


def logo(size):
    """Amber rounded square with a bin glyph, drawn at 4x and downsampled."""
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.23), fill=255)
    g = vgrad(s, s, (250, 184, 60), AMBER_D).convert("RGBA")
    img.paste(g, (0, 0), mask)
    d = ImageDraw.Draw(img)
    u = s / 100
    w = int(7 * u)
    # lid, handle, body
    d.rounded_rectangle((26 * u, 29 * u, 74 * u, 35 * u), radius=3 * u, fill=INK)
    d.rounded_rectangle((41 * u, 21 * u, 59 * u, 29 * u), radius=3 * u, outline=INK, width=int(4 * u))
    d.polygon([(31 * u, 38 * u), (69 * u, 38 * u), (65 * u, 78 * u), (35 * u, 78 * u)], fill=INK)
    for x in (42, 50, 58):
        d.rounded_rectangle(((x - 1.5) * u, 46 * u, (x + 1.5) * u, 70 * u), radius=1.5 * u, fill=(250, 184, 60))
    return img.resize((size, size), Image.LANCZOS)


def wizard_large():
    w, h = 328, 628
    img = vgrad(w, h, BG_TOP, BG_BOT)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w, 6), fill=AMBER)
    lg = logo(150)
    img.paste(lg, ((w - 150) // 2, 70), lg)
    f = font("ibm-plex-sans-latin-700-normal.ttf", 40)
    t = "Lavati"
    tw = d.textlength(t, font=f)
    d.text(((w - tw) / 2, 246), t, font=f, fill=(240, 241, 243))
    f2 = font("ibm-plex-sans-latin-500-normal.ttf", 13)
    t2 = "C L E A N E R"
    d.text(((w - d.textlength(t2, font=f2)) / 2, 300), t2, font=f2, fill=AMBER)
    f3 = font("ibm-plex-sans-latin-400-normal.ttf", 16)
    for i, line in enumerate(("Scan. Preview. Clean.", "Everything is reversible.")):
        d.text(((w - d.textlength(line, font=f3)) / 2, 388 + i * 24), line, font=f3, fill=(160, 166, 176))
    f4 = font("ibm-plex-sans-latin-400-normal.ttf", 13)
    v = "Version 1.0"
    d.text(((w - d.textlength(v, font=f4)) / 2, 580), v, font=f4, fill=(110, 116, 126))
    img.save(os.path.join(ROOT, "installer", "wizard-large.bmp"))


def wizard_small():
    img = Image.new("RGB", (110, 110), (255, 255, 255))
    lg = logo(84)
    img.paste(lg, (13, 13), lg)
    img.save(os.path.join(ROOT, "installer", "wizard-small.bmp"))


def icon():
    big = logo(256)
    big.save(os.path.join(ROOT, "assets", "lavati.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(os.path.join(ROOT, "assets", "logo.png"))
    logo(30).save(os.path.join(ROOT, "assets", "logo30.png"))


if __name__ == "__main__":
    os.makedirs(os.path.join(ROOT, "installer"), exist_ok=True)
    os.makedirs(os.path.join(ROOT, "assets"), exist_ok=True)
    wizard_large()
    wizard_small()
    icon()
    print("assets written")
