# SPDX-License-Identifier: GPL-2.0-only
"""О программе / Лицензии — app info + bundled third-party NOTICE.

Shows the app name, version, copyright and a scrollable view of the
repository ``NOTICE`` file (dependency licenses + icon/trademark
attribution). Reading the NOTICE keeps a single source of truth; if the
file cannot be located a short inline fallback is shown.
"""

from __future__ import annotations

import os
import sys

import customtkinter as ctk

from .. import APP_NAME, __version__
from .theme import Palette, fonts

_COPYRIGHT = "© 2026 1andrevich"

_FALLBACK = (
    "Сторонние компоненты:\n"
    "  • paramiko (LGPL-2.1), customtkinter (MIT), Pillow (HPND), qrcode (BSD)\n"
    "  • Иконки сервисов — Simple Icons (CC0-1.0); товарные знаки принадлежат "
    "их владельцам и используются только для обозначения сервисов.\n\n"
    "Полный текст — в файле NOTICE в каталоге программы."
)


def _load_notice() -> str:
    """Locate the repo-root NOTICE (or a resources copy) and return its text."""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    # Frozen app (PyInstaller): bundled data lives under sys._MEIPASS. This is the
    # robust location on BOTH the Windows onefile and the macOS .app — the
    # __file__-relative paths below only resolve inside the onefile temp dir, which
    # is why the .app fell back to the short notice. Check _MEIPASS first.
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidates += [
            os.path.join(base, "re_sputnik", "resources", "NOTICE"),
            os.path.join(base, "re_sputnik", "resources", "NOTICE.txt"),
            os.path.join(base, "NOTICE"),
        ]
    candidates += [
        # repo root: ui -> re_sputnik -> src -> <root>
        os.path.join(here, os.pardir, os.pardir, os.pardir, "NOTICE"),
        # packaged copy alongside resources, if one is ever added
        os.path.join(here, os.pardir, "resources", "NOTICE"),
        os.path.join(here, os.pardir, "resources", "NOTICE.txt"),
    ]
    for path in candidates:
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read().strip()
        except OSError:
            pass
    return _FALLBACK


class AboutScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build()

    def _build(self) -> None:
        p = self.p

        # Header: brand mark + app name/version/copyright.
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=32, pady=(40, 8), sticky="w")
        try:
            from ..branding import app_icon_image

            self._logo = ctk.CTkImage(
                light_image=app_icon_image(72), dark_image=app_icon_image(72), size=(72, 72))
            ctk.CTkLabel(header, image=self._logo, text="").grid(
                row=0, column=0, rowspan=2, padx=(0, 16))
        except Exception:  # noqa: BLE001 — logo is decorative, never block the screen
            pass
        ctk.CTkLabel(header, text=APP_NAME, font=fonts.title(), text_color=p.text).grid(
            row=0, column=1, sticky="sw")
        ctk.CTkLabel(
            header, text=f"v{__version__}\n{_COPYRIGHT}",
            font=fonts.body(), text_color=p.text_muted, justify="left",
        ).grid(row=1, column=1, sticky="nw", pady=(2, 0))

        ctk.CTkLabel(
            self, text="Лицензии третьих сторон", font=fonts.heading(),
            text_color=p.text,
        ).grid(row=1, column=0, padx=32, pady=(8, 6), sticky="w")

        box = ctk.CTkTextbox(
            self, font=fonts.small(), fg_color=p.surface,
            text_color=p.text_muted, wrap="word", corner_radius=10,
        )
        box.grid(row=2, column=0, padx=32, pady=(0, 32), sticky="nsew")
        box.insert("1.0", _load_notice())
        box.configure(state="disabled")
