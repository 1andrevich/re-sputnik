# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""О программе / Лицензии — app info + bundled third-party NOTICE.

Shows the app name, version, copyright and a scrollable view of the
repository ``NOTICE`` file (dependency licenses + icon/trademark
attribution). Reading the NOTICE keeps a single source of truth; if the
file cannot be located a short inline fallback is shown.
"""

from __future__ import annotations

import customtkinter as ctk

from .. import APP_NAME, __version__
from ..i18n import _
from .theme import Palette, fonts

_COPYRIGHT = "© 2026 1andrevich"


def _load_notice() -> str:
    """Full third-party NOTICE text (shared loader; see ``legal.load_notice``)."""
    from ..legal import load_notice

    return load_notice()


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

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=1, column=0, padx=32, pady=(8, 6), sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head, text=_("Лицензии третьих сторон"), font=fonts.heading(), text_color=p.text,
        ).grid(row=0, column=0, sticky="w")
        # Opens the full-text browser (NOTICE + every bundled license file) so the
        # complete texts are readable in-app, not just the attribution summary.
        ctk.CTkButton(
            head, text=_("Полные тексты лицензий"), font=fonts.small(), height=32, width=200,
            fg_color=p.surface, hover_color=p.surface_hover, text_color=p.text,
            command=self._open_licenses,
        ).grid(row=0, column=1, sticky="e")

        box = ctk.CTkTextbox(
            self, font=fonts.small(), fg_color=p.surface,
            text_color=p.text_muted, wrap="word", corner_radius=10,
        )
        box.grid(row=2, column=0, padx=32, pady=(0, 32), sticky="nsew")
        box.insert("1.0", _load_notice())
        box.configure(state="disabled")

    def _open_licenses(self) -> None:
        """Open the App's full-text license browser (lives on the top-level window)."""
        opener = getattr(self.winfo_toplevel(), "show_licenses_browser", None)
        if callable(opener):
            opener()
