#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""יוצר את אייקוני האפליקציה של mishelanu (תיקיית static/icons).

הרצה:  python mishelanu/tools/make_icons.py
האות ממורכזת בתוך אזור הבטיחות, כך שהאייקון מתאים גם כאייקון maskable.
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ICONS_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"
BACKGROUND = (13, 148, 136)
LETTER_COLOR = (255, 255, 255)
LETTER = "מ"
FONT_CANDIDATES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
SIZES = (192, 512)


def find_font():
    for candidate in FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("No suitable font file found - add one to FONT_CANDIDATES.")


def make_icon(size, font_path):
    scale = 4  # draw large, shrink down: smooth edges
    side = size * scale
    image = Image.new("RGB", (side, side), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(font_path, int(side * 0.56))
    left, top, right, bottom = draw.textbbox((0, 0), LETTER, font=font)
    draw.text(
        ((side - right + left) / 2 - left, (side - bottom + top) / 2 - top),
        LETTER, font=font, fill=LETTER_COLOR,
    )
    image.resize((size, size), Image.LANCZOS).save(ICONS_DIR / f"icon-{size}.png")


def main():
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    font_path = find_font()
    for size in SIZES:
        make_icon(size, font_path)
        print(f"icon-{size}.png")
    print("done")


if __name__ == "__main__":
    main()
