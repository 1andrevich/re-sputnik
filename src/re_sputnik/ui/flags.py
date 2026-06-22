# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Show country flags in server names as IMAGES where the OS font can't.

Server names from subscriptions begin with a flag emoji (e.g. ``🇧🇷 Бразилия``).
macOS renders that as a real flag (Apple Color Emoji has flag glyphs); Windows
and Linux do not (Segoe UI Emoji omits flags; Tk 8.6 can't draw color-emoji
fonts), so it degrades to the bare letters "BR".

On Windows/Linux we peel the leading flag emoji off the name and draw a small
flag PNG (vendored from Twemoji, see ``scripts/fetch_flags.py``) instead. On
macOS we change nothing — the emoji already looks right.
"""
from __future__ import annotations

import os
import sys

import customtkinter as ctk

_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "flags")
_cache: dict = {}
# macOS already renders flag emoji; only synthesize images elsewhere.
_USE_IMAGES = sys.platform != "darwin"
_RI_LO, _RI_HI = 0x1F1E6, 0x1F1FF  # regional-indicator codepoint range (A..Z)


def split_flag(name: str) -> tuple[str | None, str]:
    """If ``name`` starts with a flag emoji, return ``(iso2_lower, rest)``;
    otherwise ``(None, name)``. e.g. ``"🇧🇷 Бразилия (vless)"`` → ``("br", "Бразилия (vless)")``."""
    if not name or len(name) < 2:
        return None, name
    a, b = ord(name[0]), ord(name[1])
    if _RI_LO <= a <= _RI_HI and _RI_LO <= b <= _RI_HI:
        cc = chr(ord("A") + a - _RI_LO) + chr(ord("A") + b - _RI_LO)
        return cc.lower(), name[2:].lstrip()
    return None, name


def flag_image(cc: str, height: int = 16):
    """Cached CTkImage for an ISO-3166 alpha-2 code, scaled to ``height`` (keeps
    aspect), or None if there's no such flag / on macOS."""
    if not _USE_IMAGES or not cc:
        return None
    key = (cc, height)
    if key not in _cache:
        path = os.path.join(_DIR, f"{cc}.png")
        img = None
        if os.path.exists(path):
            try:
                from PIL import Image

                pil = Image.open(path).convert("RGBA")
                w, h = pil.size
                img = ctk.CTkImage(light_image=pil, dark_image=pil,
                                   size=(max(1, round(w * height / h)), height))
            except Exception:  # noqa: BLE001 — a missing/broken flag just falls back to text
                img = None
        _cache[key] = img
    return _cache[key]


def apply_to_label(label: ctk.CTkLabel, text: str, *, flag_height: int = 16) -> None:
    """Configure an EXISTING label (one refreshed in place) to show a flag image +
    cleaned name on Windows/Linux, or plain text on macOS / when there's no flag.
    ``image=None`` clears a stale flag when switching to a flagless name."""
    if _USE_IMAGES:
        cc, rest = split_flag(text)
        img = flag_image(cc, flag_height) if cc else None
        if img is not None:
            label.configure(text="  " + rest, image=img, compound="left")
            return
    label.configure(text=text, image=None, compound="left")


def name_label(master, text: str, *, flag_height: int = 16, **label_kw) -> ctk.CTkLabel:
    """Drop-in for ``CTkLabel(master, text=<server name>, …)``: on Windows/Linux it
    shows a flag image + the name with the emoji stripped; on macOS (or when there's
    no flag) it's a plain text label, unchanged. The flag emoji must lead ``text``."""
    if _USE_IMAGES:
        cc, rest = split_flag(text)
        img = flag_image(cc, flag_height) if cc else None
        if img is not None:
            return ctk.CTkLabel(master, text="  " + rest, image=img, compound="left", **label_kw)
    return ctk.CTkLabel(master, text=text, **label_kw)
