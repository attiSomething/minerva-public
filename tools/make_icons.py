"""Rebuilds the app icons from the two owl drawings:

    minerva/static/owl.svg        the full seal, for 48 px and up
    minerva/static/owl-small.svg  just the face, for 16-32 px

Writes packaging/minerva.ico (every Windows size, each drawn for its size)
and packaging/owl-512.png. Needs Node with Playwright:

    python tools/make_icons.py
"""
import os
import subprocess
import sys
import tempfile

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "minerva", "static")
PACKAGING = os.path.join(ROOT, "packaging")
SIZES = {16: "owl-small.svg", 24: "owl-small.svg", 32: "owl-small.svg",
         48: "owl.svg", 64: "owl.svg", 128: "owl.svg", 256: "owl.svg", 512: "owl.svg"}


def main():
    with tempfile.TemporaryDirectory() as tmp:
        args = []
        for size, svg in SIZES.items():
            args += [os.path.join(STATIC, svg), str(size), os.path.join(tmp, f"{size}.png")]
        subprocess.run(["node", os.path.join(ROOT, "tools", "render_svg.js"), *args], check=True)
        images = {s: Image.open(os.path.join(tmp, f"{s}.png")).convert("RGBA") for s in SIZES}
        images[512].save(os.path.join(PACKAGING, "owl-512.png"))
        ico = [images[s] for s in (16, 24, 32, 48, 64, 128, 256)]
        ico[-1].save(os.path.join(PACKAGING, "minerva.ico"), sizes=[im.size for im in ico],
                     append_images=ico[:-1])
    print("wrote packaging/minerva.ico and packaging/owl-512.png")


if __name__ == "__main__":
    sys.exit(main())
