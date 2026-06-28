# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Re:Sputnik UI kit — shared chrome + components for the Quick Setup redesign.

One source of truth for the wizard's look: a branded titlebar band, a 9-step
progress strip, a footer action bar, and standardized controls (section header,
card, field, dropdown, check, radio, toggle, buttons, orbital loader, status
line). Screens compose these instead of styling
widgets ad-hoc — that's where the "one crafted product" consistency comes from.

Styling targets the design handoff (CLAUDE_DESIGN_RESPUTNIK.md). customtkinter
has no CSS gradients/shadows/blur, so those are dropped or faked per §6.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Optional

import customtkinter as ctk

from .theme import Palette, fonts
from ..i18n import _

# Refresh/reload glyph. macOS renders the 🔄 emoji at a nice text-matched size,
# but Windows falls back to a tiny symbol-font glyph — so there use a plain
# text arrow (↻), which is sized to the surrounding text. Keeps macOS untouched.
REFRESH_GLYPH = "🔄" if sys.platform == "darwin" else "↻"

# Glyph vocabulary for section headers / chips (§4.1) — emoji FALLBACK when the
# custom line-icon PNG isn't present.
GLYPH = {
    "ssh": "🔑", "password": "🔒", "core": "📦", "links": "🔗", "file": "📄",
    "network": "🌐", "wifi": "📶", "wired": "🔌",
    "overview": "📊", "rules": "🧭", "access": "🛡", "byedpi": "🚧",
    "strategy": "🎯", "diagnostics": "🩺", "security": "🛡", "traffic": "🔀",
    "alert": "⚠", "info": "ℹ",
}

# Section-header glyph key -> line-icon file name (resources/icons_line/<name>.png).
ICON_FOR = {
    "ssh": "key", "password": "lock", "core": "package", "links": "link",
    "file": "file", "network": "globe", "wifi": "wifi", "wired": "connect",
    "nodes": "nodes", "verify": "verify", "finalize": "finalize", "resource": "resource",
    "connect": "connect",
    "overview": "overview", "rules": "rules", "access": "access", "byedpi": "byedpi",
    "antidpi": "byedpi", "zapret": "strategy",
    "strategy": "strategy", "diagnostics": "diagnostics", "security": "security",
    "traffic": "traffic", "alert": "alert", "info": "info",
}
_ICON_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "icons_line")
_icon_cache: dict = {}


def icon(name: str, size: int = 20) -> Optional[ctk.CTkImage]:
    """Cached CTkImage for a committed line-icon PNG, or None if it's missing
    (so callers fall back to an emoji and nothing breaks)."""
    key = (name, size)
    if key not in _icon_cache:
        path = os.path.join(_ICON_DIR, f"{name}.png")
        if not os.path.exists(path):
            _icon_cache[key] = None
        else:
            try:
                from PIL import Image

                img = Image.open(path).convert("RGBA")
                _icon_cache[key] = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
            except Exception:  # noqa: BLE001
                _icon_cache[key] = None
    return _icon_cache[key]


# ===== §3 chrome ===========================================================

class AppTitleBar(ctk.CTkFrame):
    """Branded header band (logo mark + Re:Sputnik wordmark). 44px, no window
    controls — the OS titlebar keeps the real min/maximize/close."""

    def __init__(self, master: ctk.CTkBaseClass, p: Palette) -> None:
        super().__init__(master, fg_color=p.chrome_bg, height=44, corner_radius=0)
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        try:
            from ..branding import app_icon_image

            self._img = ctk.CTkImage(light_image=app_icon_image(48),
                                     dark_image=app_icon_image(48), size=(22, 22))
            ctk.CTkLabel(self, image=self._img, text="").grid(
                row=0, column=0, padx=(14, 8), pady=11)
        except Exception:  # noqa: BLE001 — logo is decorative
            pass
        word = ctk.CTkFrame(self, fg_color="transparent")
        word.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(word, text="Re:", font=fonts.body(), text_color=p.accent).pack(side="left")
        ctk.CTkLabel(word, text="Sputnik", font=fonts.body(), text_color=p.text).pack(side="left")
        # 1px bottom divider
        ctk.CTkFrame(self, fg_color=p.border_dim, height=1, corner_radius=0).grid(
            row=1, column=0, columnspan=2, sticky="ew")


class StepStrip(ctk.CTkFrame):
    """9-segment progress strip. Call ``set_step(n, label)`` per screen."""

    def __init__(self, master: ctk.CTkBaseClass, p: Palette, total: int = 9) -> None:
        super().__init__(master, fg_color=p.strip_bg, corner_radius=0)
        self.p = p
        self.total = total
        self.grid_columnconfigure(0, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=18, pady=(9, 6))
        head.grid_columnconfigure(0, weight=1)
        self._label = ctk.CTkLabel(head, text=_("Быстрая настройка"), font=fonts.small(),
                                   text_color=p.text_mid)
        self._label.grid(row=0, column=0, sticky="w")
        self._counter = ctk.CTkLabel(head, text="", font=fonts.small(), text_color=p.text_dim)
        self._counter.grid(row=0, column=1, sticky="e")

        segs = ctk.CTkFrame(self, fg_color="transparent")
        segs.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        self._segs: list[ctk.CTkFrame] = []
        for i in range(total):
            segs.grid_columnconfigure(i, weight=1)
            s = ctk.CTkFrame(segs, height=3, corner_radius=2, fg_color=p.seg_future)
            s.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 4, 0))
            self._segs.append(s)
        ctk.CTkFrame(self, fg_color=p.border_dim, height=1, corner_radius=0).grid(
            row=2, column=0, sticky="ew")

    def set_step(self, step: int, label: Optional[str] = None) -> None:
        if label:
            self._label.configure(text=label)
        self._counter.configure(text=_("Шаг {0} из {1}").format(step, self.total))
        for i, s in enumerate(self._segs):
            s.configure(fg_color=self.p.accent if i < step else self.p.seg_future)


class FooterBar(ctk.CTkFrame):
    """Bottom action bar: a full-width primary button + optional link below."""

    def __init__(self, master: ctk.CTkBaseClass, p: Palette) -> None:
        super().__init__(master, fg_color=p.strip_bg, corner_radius=0)
        self.p = p
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkFrame(self, fg_color=p.border_dim, height=1, corner_radius=0).grid(
            row=0, column=0, sticky="ew")
        self._inner = ctk.CTkFrame(self, fg_color="transparent")
        self._inner.grid(row=1, column=0, sticky="ew", padx=28, pady=(14, 18))
        self._inner.grid_columnconfigure(0, weight=1)
        self._primary: Optional[ctk.CTkButton] = None
        self._link: Optional[ctk.CTkButton] = None

    def set_primary(self, text: str, command: Callable[[], None]) -> ctk.CTkButton:
        if self._primary is None:
            self._primary = primary_button(self._inner, self.p, text, command, height=46)
            self._primary.grid(row=0, column=0, sticky="ew")
        else:
            self._primary.configure(text=text, command=command)
        return self._primary

    def set_link(self, text: str, command: Callable[[], None]) -> ctk.CTkButton:
        if self._link is None:
            self._link = link_button(self._inner, self.p, text, command)
            self._link.grid(row=1, column=0, sticky="w", pady=(9, 0))
        else:
            self._link.configure(text=text, command=command)
        return self._link


class WizardScaffold:
    """Lay the Quick Setup chrome into a screen frame and expose where content
    goes. A screen calls this once, then fills ``.content`` and configures
    ``.footer`` — the titlebar/strip/footer stack is built for it.

        sc = WizardScaffold(self, p, step=2, label="Безопасность")
        # ... build widgets inside sc.content ...
        sc.footer.set_primary("Применить", self._apply)
        sc.footer.set_link("← Назад", self._back)
    """

    def __init__(self, screen: ctk.CTkBaseClass, p: Palette, *, step: int = 1,
                 label: str = "", total: int = 8, footer: bool = True,
                 scroll: bool = True, strip: bool = True, titlebar: bool = False) -> None:
        screen.grid_columnconfigure(0, weight=1)
        r = 0
        if titlebar:
            AppTitleBar(screen, p).grid(row=r, column=0, sticky="ew")
            r += 1
        # The connection screen is a gateway/login, not a wizard step — pass
        # strip=False (and titlebar=False) so it carries no chrome and the
        # 8-step rail begins at the first real step.
        self.strip: Optional[StepStrip] = None
        if strip:
            self.strip = StepStrip(screen, p, total)
            self.strip.grid(row=r, column=0, sticky="ew")
            self.strip.set_step(step, label)
            r += 1
        screen.grid_rowconfigure(r, weight=1)
        if scroll:
            self.content: ctk.CTkBaseClass = ctk.CTkScrollableFrame(screen, fg_color="transparent")
        else:
            self.content = ctk.CTkFrame(screen, fg_color="transparent")
        self.content.grid(row=r, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        r += 1
        self.footer: Optional[FooterBar] = FooterBar(screen, p) if footer else None
        if self.footer is not None:
            self.footer.grid(row=r, column=0, sticky="ew")


# ===== §4 components =======================================================

class SectionHeader(ctk.CTkFrame):
    """Icon chip + title (§4.1). ``glyph`` is a GLYPH key or a literal char."""

    def __init__(self, master: ctk.CTkBaseClass, p: Palette, glyph: str, title: str) -> None:
        super().__init__(master, fg_color="transparent")
        chip = ctk.CTkFrame(self, width=30, height=30, corner_radius=9, fg_color=p.chip_bg)
        chip.grid(row=0, column=0, padx=(0, 10))
        chip.grid_propagate(False)
        img = icon(ICON_FOR.get(glyph, glyph), 16)
        if img is not None:
            ctk.CTkLabel(chip, image=img, text="").place(relx=0.5, rely=0.5, anchor="center")
        else:  # emoji fallback if the line-icon PNG isn't present
            ctk.CTkLabel(chip, text=GLYPH.get(glyph, glyph), font=fonts.body()).place(
                relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(self, text=title, font=fonts.heading(), text_color=p.text).grid(
            row=0, column=1, sticky="w")


class Card(ctk.CTkFrame):
    """Standard panel (§4.2): surface fill, 1px border, radius 12."""

    def __init__(self, master: ctk.CTkBaseClass, p: Palette, **kw) -> None:
        kw.setdefault("fg_color", p.surface)
        kw.setdefault("corner_radius", 12)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", p.border)
        super().__init__(master, **kw)


def field(master: ctk.CTkBaseClass, p: Palette, *, placeholder: str = "",
          show: Optional[str] = None, width: int = 0, mono: bool = False) -> ctk.CTkEntry:
    """Recessed text input (§4.3)."""
    kw = dict(fg_color=p.field_bg, border_color=p.border, corner_radius=8,
              text_color=p.text, placeholder_text_color=p.text_faint,
              placeholder_text=placeholder, font=fonts.mono() if mono else fonts.body())
    if show is not None:
        kw["show"] = show
    if width:
        kw["width"] = width
    return ctk.CTkEntry(master, **kw)


def dropdown(master: ctk.CTkBaseClass, p: Palette, values: list[str], *,
             command: Optional[Callable[[str], None]] = None, idle: bool = False) -> ctk.CTkOptionMenu:
    """Field-shell dropdown with a cyan caret box (§4.4)."""
    return ctk.CTkOptionMenu(
        master, values=values, command=command, font=fonts.body(), corner_radius=8,
        fg_color=p.field_bg, button_color=p.accent, button_hover_color=p.accent_hover,
        text_color=p.text_dim if idle else p.text, dropdown_fg_color=p.surface,
        dropdown_text_color=p.text, dropdown_hover_color=p.surface_hover)


def check(master: ctk.CTkBaseClass, p: Palette, text: str, **kw) -> ctk.CTkCheckBox:
    """Standardized checkbox (§4.5)."""
    return ctk.CTkCheckBox(
        master, text=text, font=fonts.body(), text_color=p.text_strong,
        fg_color=p.accent, hover_color=p.accent_hover, checkmark_color=p.accent_fg,
        border_color="#3A4659", corner_radius=5, checkbox_width=18, checkbox_height=18, **kw)


def radio(master: ctk.CTkBaseClass, p: Palette, text: str, *, value: str,
          variable: ctk.Variable, **kw) -> ctk.CTkRadioButton:
    """Standardized radio (§4.6)."""
    return ctk.CTkRadioButton(
        master, text=text, value=value, variable=variable, font=fonts.body(),
        text_color=p.text, fg_color=p.accent, hover_color=p.accent_hover,
        border_color="#3A4659", radiobutton_width=18, radiobutton_height=18, **kw)


def toggle(master: ctk.CTkBaseClass, p: Palette, text: str = "", **kw) -> ctk.CTkSwitch:
    """Standardized toggle (§4.7)."""
    return ctk.CTkSwitch(
        master, text=text, font=fonts.body(), text_color=p.text_strong,
        progress_color=p.accent, button_color="#6B7A8D", button_hover_color=p.accent_fg,
        fg_color="#2B3547", **kw)


def primary_button(master: ctk.CTkBaseClass, p: Palette, text: str,
                   command: Callable[[], None], *, height: int = 46, **kw) -> ctk.CTkButton:
    """Primary action — cyan fill, DARK label (§4.8)."""
    return ctk.CTkButton(
        master, text=text, command=command, font=fonts.body(), height=height,
        corner_radius=9, fg_color=p.accent, hover_color=p.accent_hover,
        text_color=p.accent_fg, **kw)


def secondary_button(master: ctk.CTkBaseClass, p: Palette, text: str,
                     command: Callable[[], None], *, height: int = 36, **kw) -> ctk.CTkButton:
    """Secondary — surface fill, light label, 1px border (§4.8)."""
    return ctk.CTkButton(
        master, text=text, command=command, font=fonts.body(), height=height,
        corner_radius=8, fg_color=p.surface_hover, hover_color=p.border,
        text_color=p.text_strong, border_width=1, border_color=p.border, **kw)


def link_button(master: ctk.CTkBaseClass, p: Palette, text: str,
                command: Callable[[], None], *, accent: bool = False, **kw) -> ctk.CTkButton:
    """Borderless text action (§4.8): back/skip links, inline actions."""
    return ctk.CTkButton(
        master, text=text, command=command, font=fonts.small(), height=24,
        fg_color="transparent", hover_color=p.surface_hover,
        text_color=p.accent if accent else p.text_muted, **kw)


class OrbitLoader(ctk.CTkFrame):
    """Loader (§4.11): the mark + an indeterminate bar + skeleton rows. Never an
    empty black rectangle while checking."""

    def __init__(self, master: ctk.CTkBaseClass, p: Palette, *, skeletons: int = 3) -> None:
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(0, weight=1)
        try:
            from ..branding import app_icon_image

            self._img = ctk.CTkImage(light_image=app_icon_image(64),
                                     dark_image=app_icon_image(64), size=(56, 56))
            ctk.CTkLabel(self, image=self._img, text="").grid(row=0, column=0, pady=(8, 12))
        except Exception:  # noqa: BLE001
            pass
        self._bar = ctk.CTkProgressBar(self, mode="indeterminate", height=4,
                                       progress_color=p.accent, fg_color=p.field_bg)
        self._bar.grid(row=1, column=0, sticky="ew", padx=40, pady=(0, 16))
        self._bar.start()
        for i, w in enumerate(("70%", "90%", "55%")[:skeletons]):
            bar = ctk.CTkFrame(self, height=12, corner_radius=6, fg_color=p.field_bg)
            bar.grid(row=2 + i, column=0, sticky="w", padx=40, pady=4)
            bar.configure(width=int(360 * float(w.rstrip("%")) / 100))

    def stop(self) -> None:
        try:
            self._bar.stop()
        except Exception:  # noqa: BLE001
            pass


class StatusLine(ctk.CTkFrame):
    """Status dot + label (§4.12). ``set(text, state)`` with state in
    ok/warn/fail/busy/idle."""

    def __init__(self, master: ctk.CTkBaseClass, p: Palette) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = p
        self._dot = ctk.CTkLabel(self, text="●", font=fonts.small(), text_color=p.text_dim)
        self._dot.pack(side="left", padx=(0, 8))
        self._lbl = ctk.CTkLabel(self, text="", font=fonts.small(), text_color=p.text_dim)
        self._lbl.pack(side="left")

    def set(self, text: str, state: str = "idle") -> None:
        color = {"ok": self.p.ok, "warn": self.p.warn, "fail": self.p.fail,
                 "busy": self.p.accent}.get(state, self.p.text_dim)
        lblc = self.p.text_muted if state == "busy" else self.p.text_dim
        self._dot.configure(text_color=color)
        self._lbl.configure(text=text, text_color=lblc)
