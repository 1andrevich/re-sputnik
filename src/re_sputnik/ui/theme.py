# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Visual theme: a modern font (Inter) + a restrained palette.

customtkinter is already a "not-Arial" toolkit; we lift it to ~8/10 with a
bundled Inter font, one accent color, a neutral grey scale, and color reserved
for status only. If the Inter TTF isn't bundled yet, we fall back gracefully to
Roboto (customtkinter's default) so the app still runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import customtkinter as ctk

ASSETS = Path(__file__).resolve().parent.parent / "assets"
FONTS_DIR = ASSETS / "fonts"


@dataclass(frozen=True, slots=True)
class Palette:
    """"Orbit Cyan" — accent + greys lifted from the logo (navy + blue→cyan),
    color reserved for status. ``accent_fg`` is the dark label that sits ON the
    bright accent (white on cyan fails AA; dark passes 8.7:1)."""

    accent: str = "#38BDF8"          # cyan — buttons, active nav, highlights
    accent_hover: str = "#0EA5E0"
    accent_fg: str = "#0B1220"       # text/icon ON accent (dark — AA 8.7:1)
    accent_disabled: str = "#7CC9E6"  # disabled primary button (flat cyan tint)
    bg: str = "#10131A"              # window background (navy, matches logo plate)
    surface: str = "#1B2230"        # cards
    surface_hover: str = "#232C3D"
    text: str = "#E7E8EA"
    text_muted: str = "#93A0AE"
    ok: str = "#22C55E"             # green — status only
    warn: str = "#F59E0B"
    fail: str = "#EF4444"
    border: str = "#2B3547"

    # --- structural tints (Quick Setup redesign chrome) — same navy-grey ramp,
    #     not new brand colors: recessed surfaces, chrome bands, dim text grades.
    field_bg: str = "#141925"        # text inputs, recessed rows (darker than surface)
    chrome_bg: str = "#0B0E14"       # titlebar band background
    strip_bg: str = "#0E121A"        # progress strip + footer background
    console_bg: str = "#0A0D13"      # log/console panel + technical textarea
    console_head_bg: str = "#0D1018"  # log panel header bar
    border_dim: str = "#1C2330"      # chrome dividers (titlebar/strip/footer)
    border_row: str = "#242E3D"      # inner row borders (saved routers)
    chip_bg: str = "#163142"         # icon-chip background (flat muted-cyan)
    text_strong: str = "#CDD5DF"     # control labels (checkbox/toggle/radio)
    text_mid: str = "#AEB9C6"        # strip label, deselected radio label
    text_dim: str = "#7B8A9C"        # hints, mono endpoints, idle status
    text_faint: str = "#5F6E80"      # placeholders, log body, control glyphs
    seg_future: str = "#26303F"      # not-yet-reached progress segment


# Logical font slots used across the app, resolved once at startup.
_FONT_FAMILY = "Inter"
_FALLBACK_FAMILY = "Roboto"
_MONO_FAMILY = "JetBrains Mono"
_MONO_FALLBACK = "Consolas"  # ships on Windows; Tk falls back further if absent


def _resolve_family() -> str:
    """Use Inter if its TTF is bundled, else fall back without crashing."""
    inter = FONTS_DIR / "Inter-Regular.ttf"
    if inter.exists():
        try:
            # tkfontloader-style private load; customtkinter exposes FontManager.
            from customtkinter import FontManager

            FontManager.load_font(str(inter))
            for weight in ("Medium", "SemiBold", "Bold"):
                ttf = FONTS_DIR / f"Inter-{weight}.ttf"
                if ttf.exists():
                    FontManager.load_font(str(ttf))
            return _FONT_FAMILY
        except Exception:
            return _FALLBACK_FAMILY
    return _FALLBACK_FAMILY


class _Fonts:
    """Lazy font objects (must be created after a Tk root exists)."""

    def __init__(self) -> None:
        self._family: Optional[str] = None
        self._mono_fam: Optional[str] = None
        self._cache: dict[str, ctk.CTkFont] = {}

    def _ensure(self) -> str:
        if self._family is None:
            self._family = _resolve_family()
        return self._family

    def _ensure_mono(self) -> str:
        """JetBrains Mono if its TTF is bundled, else an OS monospace."""
        if self._mono_fam is None:
            jb = FONTS_DIR / "JetBrainsMono-Regular.ttf"
            if jb.exists():
                try:
                    from customtkinter import FontManager

                    FontManager.load_font(str(jb))
                    for w in ("Medium", "Bold"):
                        ttf = FONTS_DIR / f"JetBrainsMono-{w}.ttf"
                        if ttf.exists():
                            FontManager.load_font(str(ttf))
                    self._mono_fam = _MONO_FAMILY
                except Exception:
                    self._mono_fam = _MONO_FALLBACK
            else:
                self._mono_fam = _MONO_FALLBACK
        return self._mono_fam

    def _font(self, key: str, size: int, weight: str = "normal",
              family: Optional[str] = None) -> ctk.CTkFont:
        if key not in self._cache:
            self._cache[key] = ctk.CTkFont(
                family=family or self._ensure(), size=size, weight=weight)
        return self._cache[key]

    def title(self) -> ctk.CTkFont:
        return self._font("title", 22, "bold")

    def heading(self) -> ctk.CTkFont:
        return self._font("heading", 16, "bold")

    def body(self) -> ctk.CTkFont:
        return self._font("body", 13)

    def small(self) -> ctk.CTkFont:
        return self._font("small", 11)

    def mono(self, size: int = 12, weight: str = "normal") -> ctk.CTkFont:
        """Monospace slot for technical strings (IPs, root@host:port, logs, keys)."""
        return self._font(f"mono-{size}-{weight}", size, weight, family=self._ensure_mono())


fonts = _Fonts()


def apply_theme(appearance: str = "dark") -> Palette:
    """Set global customtkinter appearance + return the palette to use."""
    ctk.set_appearance_mode(appearance)
    ctk.set_default_color_theme("blue")
    pal = Palette()
    # Recolor customtkinter's built-in widget accents to "Orbit Cyan" so the
    # widgets that rely on the default theme (option menus, checkboxes, radios,
    # switches, progress, sliders, segmented) match the palette. CTkButton is
    # left untouched on purpose — many secondary buttons rely on its default
    # light text, which must NOT become the dark accent label.
    try:
        t = ctk.ThemeManager.theme
        for w in ("CTkOptionMenu", "CTkComboBox"):
            if w in t:
                t[w]["button_color"] = pal.accent
                t[w]["button_hover_color"] = pal.accent_hover
        for w in ("CTkCheckBox", "CTkRadioButton"):
            if w in t:
                t[w]["fg_color"] = pal.accent
                t[w]["hover_color"] = pal.accent_hover
        if "CTkSwitch" in t:
            t["CTkSwitch"]["progress_color"] = pal.accent
        if "CTkProgressBar" in t:
            t["CTkProgressBar"]["progress_color"] = pal.accent
        if "CTkSlider" in t:
            t["CTkSlider"]["button_color"] = pal.accent
            t["CTkSlider"]["progress_color"] = pal.accent
        if "CTkSegmentedButton" in t:
            t["CTkSegmentedButton"]["selected_color"] = pal.accent
            t["CTkSegmentedButton"]["selected_hover_color"] = pal.accent_hover
    except Exception:  # noqa: BLE001 — theming tweak must never block startup
        pass
    return pal
