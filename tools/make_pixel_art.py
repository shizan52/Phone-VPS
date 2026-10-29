"""Generates all the pixel art of the Phone-VPS repo: README banner, feature icons, login avatar and the demo-gallery scenes.

Everything is drawn in code on a tiny canvas and enlarged with NEAREST scaling, so every pixel stays crisp.

    pip install pillow
    python tools/make_pixel_art.py            # writes into docs/images, docs/demo-assets and panel/templates/asset
"""
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
(REPO / "docs" / "images").mkdir(parents=True, exist_ok=True)
(REPO / "docs" / "demo-assets").mkdir(parents=True, exist_ok=True)
(REPO / "panel" / "templates" / "asset").mkdir(parents=True, exist_ok=True)


def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def canvas(w, h, bg):
    im = Image.new("RGB", (w, h), bg)
    return im, ImageDraw.Draw(im)


def rect(d, x0, y0, x1, y1, c):          # inclusive corners
    d.rectangle([x0, y0, x1, y1], fill=c)


def disc(d, cx, cy, r, c):
    for y in range(int(cy - r), int(cy + r) + 1):
        for x in range(int(cx - r), int(cx + r) + 1):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                d.point((x, y), fill=c)


def save(im, path, scale):
    big = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    big.save(path, optimize=True)
    print("saved", Path(path).relative_to(REPO), big.size)


def lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def sky(d, w, h, stops, y0=0, y1=None, bands=14):
    """Vertical gradient quantised to a few bands (the pixel-art look)."""
    y1 = h if y1 is None else y1
    for y in range(y0, y1):
        t = (y - y0) / max(1, (y1 - y0 - 1))
        t = round(t * bands) / bands
        seg = min(len(stops) - 2, int(t * (len(stops) - 1)))
        lt = t * (len(stops) - 1) - seg
        d.line([(0, y), (w, y)], fill=lerp(stops[seg], stops[seg + 1], lt))


def stars(d, w, h_max, n, seed, colors=("#ffffff", "#fde68a", "#bae6fd")):
    r = random.Random(seed)
    for _ in range(n):
        x, y = r.randrange(0, w), r.randrange(0, h_max)
        c = hexc(r.choice(colors))
        d.point((x, y), fill=c)
        if r.random() < 0.12:               # a few sparkle crosses
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                d.point((x + dx, y + dy), fill=lerp(c, (20, 20, 40), 0.55))


def hills(d, w, base, amp, freq, phase, color, bottom):
    for x in range(w):
        y = round(base - amp * (0.6 * math.sin(x * freq + phase) + 0.4 * math.sin(x * freq * 2.3 + phase * 1.7)))
        d.line([(x, y), (x, bottom)], fill=color)


# --------------------------------------------------------------------------- 5x7 / 3x5 pixel fonts
F5 = {
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
    "H": ["#...#", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#", "#...#", "#...#"],
    "E": ["#####", "#....", "#....", "####.", "#....", "#....", "#####"],
    "V": ["#...#", "#...#", "#...#", "#...#", ".#.#.", ".#.#.", "..#.."],
    "S": [".####", "#....", "#....", ".###.", "....#", "....#", "####."],
    " ": ["...", "...", "...", "...", "...", "...", "..."],
}
F3 = {
    "O": ["111", "101", "101", "101", "111"], "L": ["100", "100", "100", "100", "111"],
    "D": ["110", "101", "101", "101", "110"], "P": ["111", "101", "111", "100", "100"],
    "H": ["101", "101", "111", "101", "101"], "N": ["1001", "1101", "1011", "1001", "1001"],
    "E": ["111", "100", "110", "100", "111"], "W": ["10001", "10001", "10101", "10101", "01010"],
    "S": ["011", "100", "010", "001", "110"], "R": ["110", "101", "110", "101", "101"],
    "V": ["101", "101", "101", "101", "010"], ".": ["0", "0", "0", "0", "1"], " ": ["00", "00", "00", "00", "00"],
    "A": ["010", "101", "111", "101", "101"], "U": ["101", "101", "101", "101", "111"], "T": ["111", "010", "010", "010", "010"],
    "B": ["110", "101", "110", "101", "110"], "G": ["011", "100", "101", "101", "011"], "I": ["111", "010", "010", "010", "111"],
    "Y": ["101", "101", "010", "010", "010"], "F": ["111", "100", "110", "100", "100"], "M": ["101", "111", "111", "101", "101"],
}


def text(d, s, x, y, font, color, scale=1, gap=1, shadow=None):
    cx = x
    for ch in s:
        g = font[ch]
        for ry, row in enumerate(g):
            for rx, v in enumerate(row):
                if v in "#1":
                    if shadow:
                        rect(d, cx + rx * scale + 1, y + ry * scale + 1, cx + rx * scale + scale, y + ry * scale + scale, shadow)
                    rect(d, cx + rx * scale, y + ry * scale, cx + rx * scale + scale - 1, y + ry * scale + scale - 1, color)
        cx += (len(g[0]) + gap) * scale
    return cx


def text_width(s, font, scale=1, gap=1):
    return sum((len(font[c][0]) + gap) * scale for c in s) - gap * scale


# --------------------------------------------------------------------------- sprites
def phone(d, x, y, w=24, h=34, glitch=True, lines_seed=3):
    body, hi, lo = hexc("#262834"), hexc("#4a4e60"), hexc("#14151d")
    rect(d, x, y, x + w - 1, y + h - 1, body)
    d.line([(x, y), (x + w - 1, y)], fill=hi)
    d.line([(x, y), (x, y + h - 1)], fill=hi)
    d.line([(x + w - 1, y), (x + w - 1, y + h - 1)], fill=lo)
    d.line([(x, y + h - 1), (x + w - 1, y + h - 1)], fill=lo)
    rect(d, x + 2, y + 3, x + w - 3, y + h - 5, hexc("#05090d"))          # screen
    r = random.Random(lines_seed)
    for i in range(7):                                                      # terminal text
        ly = y + 5 + i * 3
        if ly > y + h - 7:
            break
        ln = r.randrange(5, w - 8)
        col = hexc("#4ade80") if i % 3 else hexc("#facc15")
        d.line([(x + 4, ly), (x + 4 + ln, ly)], fill=col)
    if glitch:                                                              # the famous green line on the real phone's screen
        gx = x + w // 2 + 3
        d.line([(gx, y + 3), (gx, y + h - 5)], fill=hexc("#22ff5a"))
        d.line([(gx + 1, y + 3), (gx + 1, y + h - 5)], fill=hexc("#0f9d3a"))
    d.point((x + w // 2, y + 1), fill=hexc("#0b0b10"))                      # camera
    rect(d, x + w // 2 - 2, y + h - 3, x + w // 2 + 1, y + h - 3, hexc("#6b7088"))   # home bar


def wifi(d, cx, cy, color):
    for r in (3, 6, 9):
        for ang in range(-60, 61, 6):
            x = cx + round(r * math.sin(math.radians(ang)))
            y = cy - round(r * math.cos(math.radians(ang)))
            d.point((x, y), fill=color)
    d.point((cx, cy), fill=color)


def cloud(d, cx, cy, scale=1.0):
    base, light, shade, edge = hexc("#f6821f"), hexc("#fdb764"), hexc("#d4620f"), hexc("#8a3d06")
    blobs = [(-9, 3, 6), (-2, -3, 8), (7, 0, 7), (12, 4, 5), (0, 4, 7)]
    pts = set()
    for bx, by, br in blobs:
        for y in range(-12, 14):
            for x in range(-20, 22):
                if (x - bx * scale) ** 2 + (y - by * scale) ** 2 <= (br * scale) ** 2:
                    pts.add((x, y))
    for (x, y) in pts:
        c = base
        if (x, y - 1) not in pts or (x, y - 2) not in pts:
            c = light
        elif (x, y + 2) not in pts:
            c = shade
        d.point((cx + x, cy + y), fill=c)
    for (x, y) in pts:                                                      # outline
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            if (x + dx, y + dy) not in pts:
                d.point((cx + x + dx, cy + y + dy), fill=edge)


def packets(d, x0, y0, x1, y1, n, color, arrow=True, wave=2.0):
    for i in range(n):
        t = i / (n - 1)
        x = round(x0 + (x1 - x0) * t)
        y = round(y0 + (y1 - y0) * t + wave * math.sin(t * math.pi * 2))
        c = lerp(color, (255, 255, 255), 0.25 * (i % 2))
        rect(d, x, y, x + 1, y + 1, c)
    if arrow:
        ax, ay = x1 + 3, round(y1)
        for k in range(4):
            d.line([(ax + k, ay - 3 + k), (ax + k, ay + 3 - k)], fill=color)


def browser(d, x, y, w=46, h=32):
    frame, bar = hexc("#d9deea"), hexc("#2d3a5c")
    rect(d, x, y, x + w - 1, y + h - 1, frame)
    rect(d, x + 1, y + 1, x + w - 2, y + 5, bar)
    for i, c in enumerate(("#ef4444", "#facc15", "#22c55e")):
        d.point((x + 3 + i * 3, y + 3), fill=hexc(c))
    rect(d, x + 1, y + 6, x + w - 2, y + 9, hexc("#f4f6fb"))                # address bar
    rect(d, x + 3, y + 7, x + 5, y + 8, hexc("#16a34a"))                     # padlock
    d.line([(x + 7, y + 7), (x + w - 6, y + 7)], fill=hexc("#8e96ad"))
    d.line([(x + 7, y + 8), (x + w - 10, y + 8)], fill=hexc("#c4c9d8"))
    rect(d, x + 1, y + 10, x + w - 2, y + h - 2, hexc("#0e1630"))            # page
    disc(d, x + 12, y + 20, 7, hexc("#1d4ed8"))                              # globe
    for px, py in ((9, 17), (10, 17), (10, 18), (14, 21), (15, 21), (13, 23), (14, 23), (11, 15), (16, 18)):
        d.point((x + px, y + py), fill=hexc("#34d399"))
    d.arc([x + 5, y + 13, x + 19, y + 27], 0, 360, fill=hexc("#93c5fd"))
    for i in range(5):
        d.line([(x + 24, y + 14 + i * 3), (x + 24 + [14, 18, 11, 16, 9][i], y + 14 + i * 3)], fill=hexc("#334a86") if i else hexc("#60a5fa"))


def desk(d, w, y):
    rect(d, 0, y, w, y + 2, hexc("#7c4a1e"))
    d.line([(0, y), (w, y)], fill=hexc("#a86a30"))
    d.line([(0, y + 2), (w, y + 2)], fill=hexc("#4a2a10"))


# --------------------------------------------------------------------------- banner
def banner():
    W, H = 200, 64
    im, d = canvas(W, H, hexc("#0d1128"))
    sky(d, W, H, [hexc("#0b0f2a"), hexc("#1d1b4b"), hexc("#3b2a73"), hexc("#7a3f87"), hexc("#e0679a")], bands=12)
    stars(d, W, 36, 70, 7)
    disc(d, 176, 10, 5, hexc("#fff4c2"))                                     # moon
    disc(d, 178, 9, 4, hexc("#ffe9a0"))
    hills(d, W, 54, 5, 0.07, 0.6, hexc("#2a1d52"), H)
    hills(d, W, 58, 4, 0.11, 2.1, hexc("#15122f"), H)

    t = "PHONE VPS"
    tw = text_width(t, F5, 2)
    text(d, t, (W - tw) // 2, 4, F5, hexc("#4ade80"), scale=2, shadow=hexc("#0b4a22"))
    sub = "OLD PHONE . NEW SERVER"
    sw = text_width(sub, F3, 1)
    text(d, sub, (W - sw) // 2, 20, F3, hexc("#fcd9ea"))

    phone(d, 14, 25, 24, 33)
    wifi(d, 26, 22, hexc("#7dd3fc"))
    desk(d, W, 57)
    d.line([(26, 57), (26, 58)], fill=hexc("#cbd5e1"))                       # charging cable
    packets(d, 40, 40, 80, 38, 9, hexc("#fb923c"))
    cloud(d, 97, 40, 1.0)
    packets(d, 115, 38, 134, 40, 6, hexc("#fb923c"))
    browser(d, 142, 25, 46, 32)
    for x, y in ((190, 33), (8, 31), (60, 30)):                              # little twinkles
        d.point((x, y), fill=hexc("#ffffff"))
    save(im, REPO / "docs" / "images" / "banner.png", 6)


# --------------------------------------------------------------------------- icons (16x16)
PAL = {".": None, "k": "#1b1f2e", "g": "#4ade80", "G": "#16a34a", "w": "#f1f5f9", "b": "#38bdf8", "B": "#1d4ed8", "o": "#f6821f",
       "O": "#d4620f", "y": "#facc15", "r": "#ef4444", "R": "#991b1b", "s": "#94a3b8", "S": "#475569", "p": "#a78bfa", "n": "#7c4a1e", "N": "#a86a30"}
ICONS = {
    "phone": ["................", "....kkkkkkkk....", "...kSSSSSSSSk...", "...kSkkkkkkSk...", "...kSkggggkSk...", "...kSkkkkkkSk...", "...kSkgggkkSk...",
              "...kSkkkkkkSk...", "...kSkggggkSk...", "...kSkkkkkkSk...", "...kSkgkgkkSk...", "...kSkkkkkkSk...", "...kSSSSSSSSk...", "...kSSSwwSSSk...",
              "....kkkkkkkk....", "................"],
    "cloud": ["................", "................", "......oooo......", ".....owwoooo....", "....ooooooooo...", "..oooooooooooo..", ".ooooooooooooooo",
              ".oooooooooooooo.", ".oOOOOOOOOOOOO..", "..OOOOOOOOOOO...", "................", "..y.....y....y..", "..y..y..y....y..", "................",
              "................", "................"],
    "folder": ["................", "................", "..yyyyy.........", ".yyyyyyyyyyyyy..", ".yNNNNNNNNNNNy..", ".yyyyyyyyyyyyy..", ".yyyyyyyyyyyyy..", ".yyyyyyyyyyyyy..",
               ".yyyyyyyyyyyyy..", ".yyyyyyyyyyyyy..", ".yyyyyyyyyyyyy..", ".yyyyyyyyyyyyy..", ".nnnnnnnnnnnnn..", "................", "................", "................"],
    "lock": ["................", "......ssss......", ".....s....s.....", ".....s....s.....", ".....s....s.....", "...yyyyyyyyyy...", "...yyyyyyyyyy...", "...yyyyggyyyy...",
             "...yyyyggyyyy...", "...yyyyyyyyyy...", "...yyyyyyyyyy...", "...nnnnnnnnnn...", "................", "................", "................", "................"],
    "shield": ["................", "...bbbbbbbbbb...", "..bbbbbbbbbbbb..", "..bbBBBBBBBBbb..", "..bbBBBwwBBBbb..", "..bbBBBwwBBBbb..", "..bbBwwwwwwBbb..", "..bbBBBwwBBBbb..",
              "..bbBBBwwBBBbb..", "...bbBBBBBBbb...", "....bbBBBBbb....", ".....bbBBbb.....", "......bbbb......", "................", "................", "................"],
    "trash": ["................", "......ssss......", "...ssssssssss...", "...SSSSSSSSSS...", "....sSsSsSsS....", "....sSsSsSsS....", "....sSsSsSsS....", "....sSsSsSsS....",
              "....sSsSsSsS....", "....sSsSsSsS....", "....SSSSSSSS....", "................", "................", "................", "................", "................"],
}


def icons():
    for name, rows in ICONS.items():
        im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                c = PAL.get(ch)
                if c:
                    im.putpixel((x, y), hexc(c) + (255,))
        big = im.resize((96, 96), Image.NEAREST)
        big.save(REPO / "docs" / "images" / f"icon-{name}.png", optimize=True)
    print("saved", len(ICONS), "icons")


# --------------------------------------------------------------------------- avatar for the login page
def avatar():
    W = 64
    im, d = canvas(W, W, hexc("#0f172a"))
    for y in range(W):                                                       # soft diagonal gradient, quantised
        for x in range(W):
            t = round(((x + y) / (2 * W)) * 7) / 7
            d.point((x, y), fill=lerp(hexc("#0ea5a4"), hexc("#4338ca"), t))
    r = random.Random(11)
    for _ in range(26):
        d.point((r.randrange(W), r.randrange(W)), fill=hexc("#e0f2fe"))
    o = 5                                                                    # everything sits 5 px lower so the Wi-Fi arcs fit above
    rect(d, 17, 7 + o, 46, 56 + o, hexc("#15161f"))                          # body
    d.line([(17, 7 + o), (46, 7 + o)], fill=hexc("#5a5f78")); d.line([(17, 7 + o), (17, 56 + o)], fill=hexc("#5a5f78"))
    d.line([(46, 7 + o), (46, 56 + o)], fill=hexc("#090a10")); d.line([(17, 56 + o), (46, 56 + o)], fill=hexc("#090a10"))
    rect(d, 20, 12 + o, 43, 49 + o, hexc("#06120d"))                         # screen
    rect(d, 24, 21 + o, 28, 27 + o, hexc("#4ade80")); rect(d, 35, 21 + o, 39, 27 + o, hexc("#4ade80"))     # eyes
    rect(d, 25, 22 + o, 26, 23 + o, hexc("#d1fae5")); rect(d, 36, 22 + o, 37, 23 + o, hexc("#d1fae5"))
    for x, y in ((24, 36), (25, 37), (26, 38), (27, 39), (28, 39), (29, 39), (30, 39), (31, 39), (32, 39), (33, 39), (34, 39),
                 (35, 39), (36, 39), (37, 38), (38, 37), (39, 36)):
        d.point((x, y + o), fill=hexc("#4ade80"))
    rect(d, 28, 52 + o - 1, 35, 53 + o - 1, hexc("#6b7088"))
    d.point((31, 9 + o), fill=hexc("#0b0b10"))
    wifi(d, 31, 9, hexc("#bae6fd"))
    save(im, REPO / "panel" / "templates" / "asset" / "profile.png", 8)


# --------------------------------------------------------------------------- demo gallery scenes (96x64 -> 576x384)
S = (96, 64)


def scene_sunset():
    im, d = canvas(*S, (0, 0, 0))
    sky(d, 96, 64, [hexc("#1e1b4b"), hexc("#7c3aed"), hexc("#f472b6"), hexc("#fb923c"), hexc("#fde68a")], 0, 54, 12)
    disc(d, 62, 40, 9, hexc("#fff1a8")); disc(d, 62, 40, 7, hexc("#ffd966"))
    stars(d, 96, 16, 22, 1)
    hills(d, 96, 44, 8, 0.09, 0.4, hexc("#5b2a86"), 64)
    hills(d, 96, 50, 8, 0.12, 2.2, hexc("#3a1c5e"), 64)
    hills(d, 96, 57, 6, 0.15, 4.0, hexc("#1d0f33"), 64)
    return im


def scene_city():
    im, d = canvas(*S, (0, 0, 0))
    sky(d, 96, 64, [hexc("#050816"), hexc("#16205a"), hexc("#3b2f7a")], 0, 64, 10)
    stars(d, 96, 30, 40, 2)
    disc(d, 78, 12, 6, hexc("#f5f3d0")); disc(d, 80, 11, 5, hexc("#e9e6b8"))
    r = random.Random(5)
    x = 0
    while x < 96:
        w, h = r.randrange(6, 12), r.randrange(14, 44)
        rect(d, x, 64 - h, x + w - 1, 63, hexc("#0a0d1c"))
        for wy in range(64 - h + 2, 62, 3):
            for wx in range(x + 1, x + w - 1, 2):
                if r.random() < 0.45:
                    d.point((wx, wy), fill=hexc(r.choice(["#fde68a", "#fbbf24", "#7dd3fc"])))
        x += w
    return im


def scene_forest():
    im, d = canvas(*S, (0, 0, 0))
    sky(d, 96, 64, [hexc("#7dd3fc"), hexc("#bae6fd"), hexc("#fef3c7")], 0, 40, 10)
    disc(d, 20, 14, 6, hexc("#fff6bf"))
    for layer, (col, base, hmin) in enumerate([(hexc("#2e6b4a"), 44, 12), (hexc("#1f5a3a"), 52, 16), (hexc("#123d28"), 64, 22)]):
        r = random.Random(30 + layer)
        x = -2
        while x < 98:
            h = r.randrange(hmin - 4, hmin + 6)
            for i in range(h):
                half = (i * 5) // h
                d.line([(x - half, base - h + i), (x + half, base - h + i)], fill=col)
            rect(d, x, base - 1, x, base + 2, hexc("#3b2412"))
            x += r.randrange(7, 12)
        rect(d, 0, min(base, 63), 95, 63, col)
    return im


def scene_ocean():
    im, d = canvas(*S, (0, 0, 0))
    sky(d, 96, 64, [hexc("#312e81"), hexc("#db2777"), hexc("#fdba74")], 0, 30, 10)
    disc(d, 48, 30, 8, hexc("#fff0a8"))
    for y in range(30, 64):
        t = (y - 30) / 33
        d.line([(0, y), (96, y)], fill=lerp(hexc("#f59e6c"), hexc("#0b2a5b"), min(1, t * 1.4)))
    r = random.Random(8)
    for _ in range(90):
        x, y = r.randrange(96), r.randrange(32, 64)
        d.line([(x, y), (x + r.randrange(2, 5), y)], fill=lerp(hexc("#fde68a"), hexc("#7dd3fc"), (y - 32) / 32))
    rect(d, 66, 44, 74, 46, hexc("#3b2412"))                                 # boat
    d.line([(70, 28), (70, 44)], fill=hexc("#1f1308"))
    for i in range(14):
        d.line([(71, 30 + i), (71 + (i * 6) // 14, 30 + i)], fill=hexc("#f8fafc"))
    return im


def scene_desert():
    im, d = canvas(*S, (0, 0, 0))
    sky(d, 96, 64, [hexc("#fde68a"), hexc("#fdba74"), hexc("#f97316")], 0, 54, 10)
    disc(d, 70, 22, 8, hexc("#fff7d1"))
    hills(d, 96, 42, 6, 0.07, 0.5, hexc("#e8a15a"), 64)
    hills(d, 96, 50, 7, 0.1, 2.5, hexc("#c97a34"), 64)
    hills(d, 96, 58, 5, 0.13, 4.2, hexc("#8f4c1c"), 64)
    rect(d, 20, 40, 22, 56, hexc("#2f7d3a")); rect(d, 16, 44, 19, 46, hexc("#2f7d3a")); rect(d, 16, 40, 17, 46, hexc("#2f7d3a"))
    rect(d, 23, 46, 26, 48, hexc("#2f7d3a")); rect(d, 25, 42, 26, 48, hexc("#2f7d3a"))
    return im


def scene_cabin():
    im, d = canvas(*S, (0, 0, 0))
    sky(d, 96, 64, [hexc("#06122e"), hexc("#12306b"), hexc("#2c5aa0")], 0, 44, 10)
    stars(d, 96, 36, 55, 4)
    rect(d, 0, 44, 95, 63, hexc("#e8f1fb"))
    hills(d, 96, 46, 3, 0.2, 1.1, hexc("#cfe0f2"), 63)
    rect(d, 36, 36, 62, 52, hexc("#6b3f1d")); rect(d, 36, 36, 62, 37, hexc("#8a5528"))
    for i in range(10):                                                      # roof
        d.line([(34 + i, 36 - i), (64 - i, 36 - i)], fill=hexc("#f8fbff") if i % 2 else hexc("#d5e4f4"))
    rect(d, 42, 41, 48, 47, hexc("#fcd34d")); d.line([(45, 41), (45, 47)], fill=hexc("#92400e")); d.line([(42, 44), (48, 44)], fill=hexc("#92400e"))
    rect(d, 54, 42, 58, 52, hexc("#3a200c"))
    for px in (14, 22, 74, 82):
        for i in range(14):
            half = i // 3
            d.line([(px - half, 34 + i), (px + half, 34 + i)], fill=hexc("#0f3d2a") if i else hexc("#e8f1fb"))
        rect(d, px, 48, px, 51, hexc("#3b2412"))
    return im


def scene_space():
    im, d = canvas(*S, (0, 0, 0))
    rect(d, 0, 0, 96, 64, hexc("#04030d"))
    stars(d, 96, 64, 120, 9, colors=("#ffffff", "#c4b5fd", "#fde68a", "#fca5a5"))
    disc(d, 44, 34, 15, hexc("#7c3aed")); disc(d, 42, 32, 12, hexc("#a78bfa")); disc(d, 40, 30, 7, hexc("#c4b5fd"))
    for x in range(14, 78):                                                  # ring
        y = 34 + round(7 * math.sin((x - 14) / 64 * math.pi * 2 - math.pi / 2) * 0.35) - 1
        yy = 34 + round(((x - 46) / 32) * 6)
        for dy in (0, 1):
            d.point((x, yy + dy), fill=hexc("#fde68a") if dy == 0 else hexc("#f59e0b"))
    disc(d, 80, 12, 3, hexc("#f87171")); disc(d, 80, 11, 2, hexc("#fecaca"))
    return im


def scene_aurora():
    im, d = canvas(*S, (0, 0, 0))
    sky(d, 96, 64, [hexc("#020617"), hexc("#0b1b3a"), hexc("#10294f")], 0, 64, 8)
    stars(d, 96, 40, 50, 6)
    for x in range(96):
        base = 20 + 7 * math.sin(x * 0.08) + 4 * math.sin(x * 0.21)
        for i, col in enumerate(("#22c55e", "#4ade80", "#86efac", "#34d399", "#67e8f9")):
            y0 = round(base) + i * 3
            for dy in range(3):
                t = 0.55 - 0.1 * i
                d.point((x, y0 + dy), fill=lerp(hexc("#0b1b3a"), hexc(col), max(0.15, t - dy * 0.12)))
    hills(d, 96, 54, 6, 0.1, 0.7, hexc("#07101f"), 64)
    hills(d, 96, 59, 4, 0.15, 3.0, hexc("#030812"), 64)
    return im


SCENES = {"sunset": scene_sunset, "city_night": scene_city, "forest": scene_forest, "ocean": scene_ocean,
          "desert": scene_desert, "cabin_snow": scene_cabin, "space": scene_space, "aurora": scene_aurora}


def scenes():
    for name, fn in SCENES.items():
        im = fn()
        im.resize((S[0] * 6, S[1] * 6), Image.NEAREST).save(REPO / "docs" / "demo-assets" / f"{name}.png", optimize=True)
    print("saved", len(SCENES), "scenes")


banner()
icons()
avatar()
scenes()
