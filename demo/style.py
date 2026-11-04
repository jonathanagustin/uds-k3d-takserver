#!/usr/bin/env python3
# Copyright 2026 uds-k3d-takserver authors
# SPDX-License-Identifier: GPL-3.0-only

"""The look of the demo videos, in one place: canvas, palette, fonts, the
window frame around each recording, title cards and lower-thirds.

    style.py fonts                         check the fonts (no fallbacks)
    style.py background OUT.png            the canvas background
    style.py frame UNDER.png OVER.png MASK.png
                                           the window frame: shadow and title
                                           bar under the recording, border
                                           over it, and the recording's
                                           rounded-corner mask
    style.py card OUT.png TITLE SUBTITLE   a title card
    style.py lower OUT.png TEXT [TAG]      a lower-third; prints "X Y" where
                                           it goes on the canvas
    style.py still IN.png OUT.png          a still for the docs, in the frame

demo/assemble.sh and demo/filters.py use these. Pillow draws everything, so
the sizes and colours below are exact.
"""

import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# Canvas and timing.
W, H = 1920, 1080
FPS = 30
# The recording inside the window frame: about 85% of the canvas. The frame
# sits a little above centre so a lower-third has room under it.
CONTENT_W, CONTENT_H = 1632, 840
TITLE_BAR = 36
FRAME_X = (W - CONTENT_W) // 2
FRAME_Y = 40
CONTENT_X, CONTENT_Y = FRAME_X, FRAME_Y + TITLE_BAR
FRAME_W, FRAME_H = CONTENT_W, CONTENT_H + TITLE_BAR
RADIUS = 12

# Palette. Nothing else is drawn.
BG = "#0F172A"
BG_EDGE = "#020617"
INDIGO = "#818CF8"
EMERALD = "#34D399"
HEADER = "#F8FAFC"
BODY = "#CBD5E1"
OVERLAY = (15, 23, 42, 217)  # rgba(15,23,42,0.85)
OVERLAY_BORDER = (255, 255, 255, 26)  # rgba(255,255,255,0.1)
FRAME_BORDER = (255, 255, 255, 38)  # rgba(255,255,255,0.15)

# Fonts, by fontconfig name. check_fonts() fails on a fallback.
FONTS = {
    "title": ("Inter:style=SemiBold", "Inter", "SemiBold"),
    "lower": ("Inter:style=Medium", "Inter", "Medium"),
    "mono": ("JetBrains Mono", "JetBrains Mono", None),
}
TITLE_SIZE = 64
SUBTITLE_SIZE = 32
LOWER_SIZE = 28
TEXT_MAX_W = int(W * 0.84)
LOWER_MAX_W = 1180


def hex_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def font_file(role):
    pattern, family, style = FONTS[role]
    out = subprocess.run(["fc-match", "-f", "%{file}\n%{family}\n%{style}", pattern],
                         capture_output=True, text=True, check=True).stdout.split("\n")
    path, families, styles = out[0], out[1], out[2] if len(out) > 2 else ""
    if family not in families.split(","):
        sys.exit(f"font {pattern}: fontconfig falls back to {families} ({path})")
    if style and style not in styles and style.replace(" ", "") not in path:
        sys.exit(f"font {pattern}: no {style} face, got {styles} ({path})")
    return path


def font(role, size):
    return ImageFont.truetype(font_file(role), size)


def check_fonts():
    for role in FONTS:
        print(f"{role}: {font_file(role)}")


def background():
    """#0F172A in the middle, #020617 at the corners, a soft radial falloff."""
    small = Image.new("RGB", (W // 4, H // 4))
    inner, outer = hex_rgb(BG), hex_rgb(BG_EDGE)
    cx, cy = small.width / 2, small.height / 2
    reach = (cx ** 2 + cy ** 2) ** 0.5
    px = small.load()
    for y in range(small.height):
        for x in range(small.width):
            d = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5 / reach)
            t = max(0.0, (d - 0.35) / 0.65) ** 1.6
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(inner, outer))
    return small.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(2))


def shadow(size, box, radius, offset_y, blur, alpha):
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle((x0, y0 + offset_y, x1, y1 + offset_y), radius, fill=(0, 0, 0, alpha))
    return layer.filter(ImageFilter.GaussianBlur(blur))


def frame():
    """UNDER: background, shadow (0 24px 48px rgba(0,0,0,.5)) and the title
    bar with three dots. OVER: the 1px border. MASK: the recording's rounded
    bottom corners (white shows the recording)."""
    box = (FRAME_X, FRAME_Y, FRAME_X + FRAME_W - 1, FRAME_Y + FRAME_H - 1)
    under = background().convert("RGBA")
    # A CSS blur radius of 48px is about a Gaussian sigma of 24.
    under.alpha_composite(shadow((W, H), box, RADIUS, 24, 24, 128))
    draw = ImageDraw.Draw(under)
    draw.rounded_rectangle(box, RADIUS, fill=hex_rgb(BG_EDGE))
    dot_y = FRAME_Y + TITLE_BAR // 2
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for i in range(3):
        cx = FRAME_X + 20 + i * 20
        dd.ellipse((cx - 6, dot_y - 6, cx + 6, dot_y + 6), fill=hex_rgb(BODY) + (90,))
    under.alpha_composite(dots)
    over = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(over).rounded_rectangle(box, RADIUS, outline=FRAME_BORDER, width=1)
    mask = Image.new("L", (CONTENT_W, CONTENT_H), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, -RADIUS * 2, CONTENT_W - 1, CONTENT_H - 1), RADIUS, fill=255)
    return under, over, mask


def wrap(text, fnt, max_w, draw):
    words, lines, line = text.split(), [], ""
    for word in words:
        test = f"{line} {word}".strip()
        if draw.textlength(test, font=fnt) <= max_w or not line:
            line = test
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def fitted(role, size, text, max_w, max_lines, draw):
    """The largest size up to SIZE whose wrapped text has at most MAX_LINES."""
    while size > 12:
        fnt = font(role, size)
        lines = wrap(text, fnt, max_w, draw)
        if len(lines) <= max_lines and all(draw.textlength(l, font=fnt) <= max_w for l in lines):
            return fnt, lines
        size -= 2
    fnt = font(role, size)
    return fnt, wrap(text, fnt, max_w, draw)


def card(title, subtitle):
    img = background().convert("RGBA")
    draw = ImageDraw.Draw(img)
    tfont, tlines = fitted("title", TITLE_SIZE, title, TEXT_MAX_W, 2, draw)
    sfont, slines = fitted("mono", SUBTITLE_SIZE, subtitle, TEXT_MAX_W, 2, draw)
    t_line = round(tfont.size * 1.2)
    s_line = round(sfont.size * 1.4)
    gap = 36
    total = t_line * len(tlines) + gap + s_line * len(slines)
    y = (H - total) // 2
    for line in tlines:
        draw.text((W / 2, y), line, font=tfont, fill=HEADER, anchor="mt")
        y += t_line
    y += gap
    for line in slines:
        draw.text((W / 2, y), line, font=sfont, fill=INDIGO, anchor="mt")
        y += s_line
    return img.convert("RGB")


def lower(text, tag=""):
    """A floating box: 16/24px padding, 12px radius, soft shadow. TAG is an
    emerald pill for a speed-up. Returns the image and its canvas position."""
    probe = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    fnt = font("lower", LOWER_SIZE)
    tag_font = font("lower", 22)
    tag_w = probe.textlength(tag, font=tag_font) + 28 if tag else 0
    lines = wrap(text, fnt, LOWER_MAX_W - tag_w, probe)[:2]
    line_h = round(LOWER_SIZE * 1.3)
    text_w = max(probe.textlength(l, font=fnt) for l in lines)
    pad_x, pad_y = 24, 16
    box_w = round(text_w + (tag_w + 16 if tag else 0) + 2 * pad_x)
    box_h = line_h * len(lines) + 2 * pad_y
    margin = 32  # room for the shadow
    img = Image.new("RGBA", (box_w + 2 * margin, box_h + 2 * margin), (0, 0, 0, 0))
    box = (margin, margin, margin + box_w - 1, margin + box_h - 1)
    img.alpha_composite(shadow(img.size, box, RADIUS, 8, 12, 110))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, RADIUS, fill=OVERLAY, outline=OVERLAY_BORDER, width=1)
    y = margin + pad_y
    for line in lines:
        draw.text((margin + pad_x, y + line_h / 2), line, font=fnt, fill=HEADER, anchor="lm")
        y += line_h
    if tag:
        tx = margin + pad_x + text_w + 16
        ty = margin + box_h / 2
        pill = (tx, ty - 17, tx + tag_w, ty + 17)
        draw.rounded_rectangle(pill, 17, fill=hex_rgb(EMERALD) + (36,), outline=hex_rgb(EMERALD) + (140,), width=1)
        draw.text(((pill[0] + pill[2]) / 2, ty), tag, font=tag_font, fill=EMERALD, anchor="mm")
    x = 48 - margin
    y = H - 48 - box_h - margin
    return img, x, y


def still(src):
    """A docs still: the screenshot in the window frame, on the background,
    cropped to the frame with a margin."""
    shot = Image.open(src).convert("RGB")
    scale = min(CONTENT_W / shot.width, CONTENT_H / shot.height, 1.0)
    cw, ch = round(shot.width * scale), round(shot.height * scale)
    shot = shot.resize((cw, ch), Image.LANCZOS) if scale < 1 else shot
    m = 48
    fw, fh = cw, ch + TITLE_BAR
    size = (fw + 2 * m, fh + 2 * m + 24)
    img = background().resize(size, Image.BICUBIC).convert("RGBA")
    box = (m, m, m + fw - 1, m + fh - 1)
    img.alpha_composite(shadow(size, box, RADIUS, 24, 24, 128))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(box, RADIUS, fill=hex_rgb(BG_EDGE))
    for i in range(3):
        cx, cy = m + 20 + i * 20, m + TITLE_BAR // 2
        draw.ellipse((cx - 6, cy - 6, cx + 6, cy + 6), fill=hex_rgb(BODY) + (90,))
    mask = Image.new("L", (cw, ch), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, -RADIUS * 2, cw - 1, ch - 1), RADIUS, fill=255)
    img.paste(shot, (m, m + TITLE_BAR), mask)
    ImageDraw.Draw(img).rounded_rectangle(box, RADIUS, outline=FRAME_BORDER, width=1)
    return img.convert("RGB")


def main():
    cmd = sys.argv[1]
    if cmd == "fonts":
        check_fonts()
    elif cmd == "background":
        background().save(sys.argv[2])
    elif cmd == "frame":
        under, over, mask = frame()
        under.save(sys.argv[2])
        over.save(sys.argv[3])
        mask.save(sys.argv[4])
    elif cmd == "card":
        card(sys.argv[3], sys.argv[4]).save(sys.argv[2])
    elif cmd == "lower":
        img, x, y = lower(sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else "")
        img.save(sys.argv[2])
        print(x, y)
    elif cmd == "still":
        still(sys.argv[2]).save(sys.argv[3])
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
