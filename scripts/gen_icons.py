# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Fetch + rasterize the two icons missing from resources/icons.

Reliable, no native deps: SVGs come from free icon sets and are rasterized with
resvg-py (a self-contained Rust wheel — no cairo/GTK). Output: 64x64 RGBA PNGs.

  - whatsapp.png : Simple Icons (CC0) WhatsApp mark, recoloured to brand green.
    Identifies the service on the "proxy calls" toggle (nominative use; the screen
    carries a trademark notice).
  - torrent.png  : Phosphor (MIT) filled magnet — a NEUTRAL magnet, deliberately
    not the BitTorrent Inc. logo ("torrents" is a generic protocol).

Run:  python scripts/gen_icons.py
"""

from __future__ import annotations

import io
import os
import re
import urllib.request

import resvg_py
from PIL import Image

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                   "src", "re_sputnik", "resources", "icons")

# name -> (svg url, brand/glyph colour)
ICONS = {
    "whatsapp": ("https://cdn.jsdelivr.net/npm/simple-icons@latest/icons/whatsapp.svg", "#25D366"),
    "torrent": ("https://raw.githubusercontent.com/phosphor-icons/core/main/assets/fill/"
                "magnet-fill.svg", "#D23A3A"),
}


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "re-companion"})
    with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 — fixed https hosts
        return r.read().decode()


def _recolour(svg: str, colour: str) -> str:
    """Force a single fill colour: replace any non-'none' fill, and make sure the
    root <svg> carries the colour so fill-less paths (Simple Icons) inherit it."""
    svg = re.sub(r'fill="(?!none)[^"]*"', f'fill="{colour}"', svg)
    if "fill=" not in svg.split(">", 1)[0]:
        svg = svg.replace("<svg", f'<svg fill="{colour}"', 1)
    return svg


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    for name, (url, colour) in ICONS.items():
        svg = _recolour(_fetch(url), colour)
        png = resvg_py.svg_to_bytes(svg_string=svg, width=256, height=256)
        img = Image.open(io.BytesIO(bytes(png))).convert("RGBA").resize((64, 64), Image.LANCZOS)
        img.save(os.path.join(OUT, f"{name}.png"))
        print("wrote", f"{name}.png", img.size, img.mode)


if __name__ == "__main__":
    main()
