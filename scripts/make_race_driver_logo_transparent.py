"""
Make white background transparent in the race driver logo and normalize circle size.
Reads assets/logo-race-driver.png, saves back with transparent background.
Output is 400x400 with circle diameter 400 (same as moshav logo).
"""
import math
import os
import sys

try:
    from PIL import Image
except ImportError:
    print("Pillow required. Run: pip install Pillow")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(SCRIPT_DIR, "..")
IN_PATH = os.path.join(ROOT, "assets", "logo-race-driver.png")
OUT_PATH = IN_PATH
TARGET = 400  # same as moshav script: circle diameter and canvas size


def color_distance(c1, c2):
    return sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])) ** 0.5


def main():
    if not os.path.isfile(IN_PATH):
        print("File not found:", IN_PATH)
        sys.exit(1)

    img = Image.open(IN_PATH)
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    pixels = img.load()

    # Detect circle: from corners inward, first non-background = logo edge. Background = white or black (transparent).
    def is_background(rgb):
        r, g, b = rgb
        if color_distance(rgb, (255, 255, 255)) <= 90:
            return True
        if r + g + b < 40:  # transparent became black
            return True
        return False

    cx, cy = w / 2.0, h / 2.0
    boundary_distances = []
    corner_coords = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    for i in range(25):
        t = i / 24 if i < 24 else 1
        for (sx, sy) in corner_coords + [
            (int(t * (w - 1)), 0), (int(t * (w - 1)), h - 1),
            (0, int(t * (h - 1))), (w - 1, int(t * (h - 1))),
        ]:
            for k in range(1, 301):
                t2 = k / 300
                x = sx + t2 * (cx - sx)
                y = sy + t2 * (cy - sy)
                ix, iy = int(x), int(y)
                if not (0 <= ix < w and 0 <= iy < h):
                    break
                if not is_background(pixels[ix, iy]):
                    d = math.hypot(ix - cx, iy - cy)
                    boundary_distances.append(d)
                    break

    radius = float(sorted(boundary_distances)[len(boundary_distances) // 2]) if boundary_distances else min(w, h) // 2
    radius = radius * 0.995

    # Outside circle -> transparent. Inside circle -> keep all colors (including white)
    out = Image.new("RGBA", (w, h))
    out_pixels = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            dist_from_center_sq = (x - cx) ** 2 + (y - cy) ** 2
            if dist_from_center_sq > radius * radius:
                alpha = 0
            else:
                alpha = 255
            out_pixels[x, y] = (r, g, b, alpha)

    # Normalize: same circle diameter as moshav (400px), output TARGET x TARGET
    scale = TARGET / (2.0 * radius)
    scaled_w, scaled_h = int(w * scale), int(h * scale)
    out_scaled = out.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    cx_scaled, cy_scaled = cx * scale, cy * scale
    final = Image.new("RGBA", (TARGET, TARGET), (0, 0, 0, 0))
    paste_x = int(TARGET // 2 - cx_scaled)
    paste_y = int(TARGET // 2 - cy_scaled)
    final.paste(out_scaled, (paste_x, paste_y), out_scaled)
    final.save(OUT_PATH, "PNG")
    print("Saved:", OUT_PATH)


if __name__ == "__main__":
    main()
