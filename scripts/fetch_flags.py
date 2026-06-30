#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Dev-time only: vendor country-flag PNGs into ``resources/flags/<cc>.png``.

Windows' Segoe UI Emoji has no flag glyphs (and the bundled Tk can't render
color-emoji fonts), so flag emoji in server names show as bare letters ("BR").
We instead draw a small flag IMAGE on Windows/Linux. This pulls the flag art
from Twemoji (CC-BY 4.0 — attribution in NOTICE), trims the padding, downsizes,
and saves one PNG per ISO-3166-1 alpha-2 code. Run once; commit the PNGs.

    python scripts/fetch_flags.py
"""
from __future__ import annotations

import io
import os
import ssl
import string
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

try:
    import certifi
    _CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:  # noqa: BLE001
    _CTX = ssl.create_default_context()

OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                   "src", "re_sputnik", "resources", "flags")
HEIGHT = 24  # px; CTkImage scales for HiDPI. Trimmed flags keep their aspect.
# jdecked/twemoji is the maintained fork of Twitter's archived twemoji.
BASE = "https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/72x72/"


def _codepoints(code: str) -> str:
    # 'BR' -> regional indicators U+1F1E7 U+1F1F7 -> '1f1e7-1f1f7'
    return "-".join(f"{0x1F1E6 + ord(c) - 65:x}" for c in code)


def _fetch(code: str) -> bool:
    url = BASE + _codepoints(code) + ".png"
    try:
        data = urllib.request.urlopen(url, timeout=20, context=_CTX).read()
    except Exception:  # noqa: BLE001 — non-flag pairs 404; just skip
        return False
    im = Image.open(io.BytesIO(data)).convert("RGBA")
    bbox = im.getbbox()
    if bbox:
        im = im.crop(bbox)               # drop the transparent square padding
    w, h = im.size
    im = im.resize((max(1, round(w * HEIGHT / h)), HEIGHT), Image.LANCZOS)
    im.save(os.path.join(OUT, code.lower() + ".png"))
    return True


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    codes = [a + b for a in string.ascii_uppercase for b in string.ascii_uppercase]
    with ThreadPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(_fetch, codes))
    got = sum(results)
    print(f"saved {got} flag PNGs to {OUT} ({len(codes) - got} non-flag pairs skipped)")


if __name__ == "__main__":
    main()
