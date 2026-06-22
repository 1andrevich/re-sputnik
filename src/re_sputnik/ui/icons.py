# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Service brand icons (Simple Icons, pre-rasterized PNGs bundled in resources).

Icons are loaded lazily and cached as CTkImage. Service brand marks belong to
their respective owners; they're used here only to identify the service a routing
rule applies to. Unknown services fall back to a neutral badge.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import customtkinter as ctk
from PIL import Image

_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "icons")


def has_real_icon(service: str) -> bool:
    """True if a brand-specific PNG exists (not the neutral fallback badge)."""
    return os.path.exists(os.path.join(_ICON_DIR, f"{service}.png"))


@lru_cache(maxsize=None)
def service_icon(service: str, size: int = 22) -> Optional[ctk.CTkImage]:
    """CTkImage for a service (brand or generic badge). Must be called on the Tk
    thread. Returns None only if even the default badge is missing."""
    path = os.path.join(_ICON_DIR, f"{service}.png")
    if not os.path.exists(path):
        path = os.path.join(_ICON_DIR, "_default.png")
    if not os.path.exists(path):
        return None
    try:
        img = Image.open(path).convert("RGBA")
        return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    except Exception:  # noqa: BLE001 — a broken asset shouldn't crash the UI
        return None
