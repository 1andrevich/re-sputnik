# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Re:Sputnik brand assets — loader for the shipped logo/icon files.

The artwork is the approved "Sputnik '57" design (the 1957 satellite climbing
over Earth's horizon with a signal downlink). The vector source of truth is
``resources/branding/logo_mark.svg``; the PNG set + ``icon.ico`` are generated
from it (externally, via an SVG rasterizer — see the design handoff README) and
committed alongside. This module just *loads* those assets — it does not draw
them — so the app carries no SVG/cairo dependency at runtime.
"""

from __future__ import annotations

import os

from PIL import Image

_BRANDING_DIR = os.path.join(os.path.dirname(__file__), "resources", "branding")
_PNG_SIZES = (16, 32, 48, 64, 128, 256)


def ico_path() -> str:
    """Path to the Windows multi-resolution icon (window/taskbar/executable)."""
    return os.path.join(_BRANDING_DIR, "icon.ico")


def icon_png_path(size: int = 256) -> str:
    """Path to the committed PNG icon at the smallest size >= ``size``."""
    pick = next((s for s in _PNG_SIZES if s >= size), _PNG_SIZES[-1])
    return os.path.join(_BRANDING_DIR, f"icon_{pick}.png")


def app_icon_image(size: int = 64) -> Image.Image:
    """RGBA logo image for the Tk window/taskbar icon or an in-app ``CTkImage``.

    Loads the shipped PNG (exact size if present, otherwise the nearest larger
    one scaled down with LANCZOS).
    """
    exact = os.path.join(_BRANDING_DIR, f"icon_{size}.png")
    path = exact if os.path.exists(exact) else icon_png_path(size)
    img = Image.open(path).convert("RGBA")
    return img if img.size == (size, size) else img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    # quick asset-presence check
    missing = [f"icon_{s}.png" for s in _PNG_SIZES
               if not os.path.exists(os.path.join(_BRANDING_DIR, f"icon_{s}.png"))]
    missing += [n for n in ("icon.ico", "logo_mark.svg", "logo_wordmark.svg")
                if not os.path.exists(os.path.join(_BRANDING_DIR, n))]
    print("branding assets OK" if not missing else f"MISSING: {missing}")
