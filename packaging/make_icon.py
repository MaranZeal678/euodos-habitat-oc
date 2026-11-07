"""Draw the Euodos app icon (an arch whose crown is the keystone) and write a macOS .icns.

  python packaging/make_icon.py packaging/build/Euodos.icns
"""
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

TEAL, DEEP, STONE, KEY = (15, 107, 92), (8, 52, 45), (238, 246, 243), (224, 168, 74)


def draw(size=1024):
    s = size / 1024
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rectangle([40 * s, 40 * s, 984 * s, 984 * s], fill=TEAL)
    d.rectangle([40 * s, 560 * s, 984 * s, 984 * s], fill=DEEP)
    cx, cy, r_out, r_in = 512 * s, 640 * s, 360 * s, 230 * s
    n = 9  # voussoirs; the middle one is the keystone
    gap = math.radians(2.2)
    for i in range(n):
        a0 = math.pi - i * math.pi / n - gap / 2
        a1 = math.pi - (i + 1) * math.pi / n + gap / 2
        grow = 34 * s if i == n // 2 else 0
        pts = [(cx + (r_in) * math.cos(a), cy - (r_in) * math.sin(a)) for a in (a0, a1)]
        pts += [(cx + (r_out + grow) * math.cos(a), cy - (r_out + grow) * math.sin(a)) for a in (a1, a0)]
        d.polygon(pts, fill=KEY if i == n // 2 else STONE)
    d.rectangle([cx - r_out, cy, cx - r_in, 860 * s], fill=STONE)
    d.rectangle([cx + r_in, cy, cx + r_out, 860 * s], fill=STONE)
    mask = Image.new("L", (size, size), 0)  # one rounded-square silhouette clips everything
    ImageDraw.Draw(mask).rounded_rectangle([40 * s, 40 * s, 984 * s, 984 * s], radius=200 * s, fill=255)
    im.putalpha(mask)
    return im


def main(out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    base = draw()
    base.save(out.with_suffix(".png"))
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Euodos.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            base.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
            base.resize((px * 2, px * 2), Image.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
        if shutil.which("iconutil"):
            subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(out)], check=True)
        else:
            base.save(out, format="ICNS")
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "packaging/build/Euodos.icns")
