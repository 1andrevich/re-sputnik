# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Rasterize the line-icon SVGs (design handoff) to PNG for the app.

customtkinter can't load SVG, so we render each master SVG once at high
resolution with resvg-py and commit the PNGs; CTkImage downscales them crisply
at runtime. Build-time only (resvg-py is in the [build] extra) — the app ships
the PNGs and carries no SVG renderer.

Run:  python scripts/render_icons.py
"""
from __future__ import annotations

import os

import resvg_py

SRC = os.path.join("src", "re_sputnik", "banner", "assets", "icons")
DST = os.path.join("src", "re_sputnik", "resources", "icons_line")
SIZE = 96  # render high; CTkImage scales down to 16/24/30/64 cleanly


def main() -> int:
    os.makedirs(DST, exist_ok=True)
    n = 0
    for f in sorted(os.listdir(SRC)):
        if not f.endswith(".svg"):
            continue
        png = resvg_py.svg_to_bytes(svg_path=os.path.join(SRC, f), width=SIZE, height=SIZE)
        if not isinstance(png, (bytes, bytearray)):
            png = bytes(png)
        with open(os.path.join(DST, f[:-4] + ".png"), "wb") as fh:
            fh.write(png)
        n += 1
        print("rendered", f[:-4])
    print(f"--- {n} icons -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
