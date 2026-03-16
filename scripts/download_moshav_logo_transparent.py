"""
Download Moshav Sde Warburg logo and make green background transparent.
Saves to assets/logo-moshav.png
"""
import math
import os
import sys
from urllib.request import Request, urlopen

try:
    from PIL import Image
except ImportError:
    print("Pillow required. Run: pip install Pillow")
    sys.exit(1)

URL = "https://www.dsharon.org.il/uploads/n/1566803468.2648.jpg"
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "assets", "logo-moshav.png")


def color_distance(c1, c2):
    return sum((a - b) ** 2 for a, b in zip(c1[:3], c2[:3])) ** 0.5


def main():
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp_path = OUT_PATH + ".tmp.jpg"

    print("Downloading logo...")
    req = Request(URL, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0"})
    with urlopen(req) as resp:
        data = resp.read()
    with open(tmp_path, "wb") as f:
        f.write(data)

    img = Image.open(tmp_path).convert("RGB")
    w, h = img.size
    pixels = img.load()

    # Background green = corners. We'll walk FROM corners INWARD; first non-green = logo edge (white circle).
    corner_coords = [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]
    greens = [pixels[x, y] for x, y in corner_coords]
    bg_r = sum(p[0] for p in greens) // len(greens)
    bg_g = sum(p[1] for p in greens) // len(greens)
    bg_b = sum(p[2] for p in greens) // len(greens)
    bg_color = (bg_r, bg_g, bg_b)
    bg_threshold = 70  # pixel is "background green" if distance < this

    cx, cy = w / 2.0, h / 2.0
    # Rays: from corners and from points along edges, inward toward center. First non-green = logo boundary.
    boundary_distances = []
    start_points = []
    # 4 corners
    start_points.extend(corner_coords)
    # points along the 4 edges (so we get boundary in all directions)
    n = 25
    for i in range(n):
        t = i / (n - 1) if n > 1 else 1
        start_points.append((int(t * (w - 1)), 0))
        start_points.append((int(t * (w - 1)), h - 1))
        start_points.append((0, int(t * (h - 1))))
        start_points.append((w - 1, int(t * (h - 1))))

    for (sx, sy) in start_points:
        # ray from (sx,sy) toward center (cx, cy)
        steps = 300
        for k in range(1, steps + 1):
            t = k / steps
            x = sx + t * (cx - sx)
            y = sy + t * (cy - sy)
            ix, iy = int(x), int(y)
            if not (0 <= ix < w and 0 <= iy < h):
                break
            if color_distance(pixels[ix, iy], bg_color) > bg_threshold:
                # first non-green = we reached the logo (white circle); this is the boundary
                d = math.hypot(ix - cx, iy - cy)
                boundary_distances.append(d)
                break

    radius = float(sorted(boundary_distances)[len(boundary_distances) // 2]) if boundary_distances else min(w, h) // 2
    # optional: slight shrink so we don't include green edge pixels
    radius = radius * 0.995

    # Only make pixels OUTSIDE the circle transparent; keep all colors inside
    out = Image.new("RGBA", (w, h))
    out_pixels = out.load()
    for y in range(h):
        for x in range(w):
            r, g, b = pixels[x, y]
            dist_from_center = (x - cx) ** 2 + (y - cy) ** 2
            if dist_from_center > radius * radius:
                alpha = 0  # outside circle -> transparent
            else:
                # optional: smooth edge over a few pixels
                if dist_from_center > (radius - 2) ** 2:
                    # blend alpha near edge
                    d_center = math.sqrt(dist_from_center)
                    alpha = int(255 * (radius - d_center) / 2) if radius - d_center < 2 else 255
                    alpha = max(0, min(255, alpha))
                else:
                    alpha = 255
            out_pixels[x, y] = (r, g, b, alpha)

    # Normalize: scale so circle diameter = TARGET, output TARGET x TARGET (both logos same circle size)
    TARGET = 400
    scale = TARGET / (2.0 * radius)
    scaled_w, scaled_h = int(w * scale), int(h * scale)
    out_scaled = out.resize((scaled_w, scaled_h), Image.Resampling.LANCZOS)
    cx_scaled, cy_scaled = cx * scale, cy * scale
    final = Image.new("RGBA", (TARGET, TARGET), (0, 0, 0, 0))
    paste_x = int(TARGET // 2 - cx_scaled)
    paste_y = int(TARGET // 2 - cy_scaled)
    final.paste(out_scaled, (paste_x, paste_y), out_scaled)
    final.save(OUT_PATH, "PNG")
    try:
        os.remove(tmp_path)
    except OSError:
        pass
    print("Saved:", OUT_PATH)


if __name__ == "__main__":
    main()
