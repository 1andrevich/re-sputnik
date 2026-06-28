# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Advanced-mode settings shell — left nav + swappable content area.

The seven sections (Nodes, Rules, Access, ByeDPI, Core, Diagnostics, Security)
each have a real screen; ``_stub`` remains only as a defensive fallback for an
unrecognised section key.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from ..i18n import N_, _
from ..router import RouterClient, RouterState
from . import kit
from .theme import Palette, fonts

OnExit = Callable[[], None]

_SECTIONS = [
    ("overview", N_("Обзор")),
    ("nodes", N_("Ключи и подписки")),
    ("rules", N_("Правила")),
    ("access", N_("Контроль доступа")),
    ("antidpi", N_("AntiDPI")),
    ("core", N_("Ядро")),
    ("diagnostics", N_("Диагностика")),
    ("security", N_("Безопасность")),
    ("advanced", N_("Дополнительно")),
    ("about", N_("О программе")),
]


class SettingsShell(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        palette: Palette,
        client: RouterClient,
        state: RouterState,
        *,
        on_exit: Optional[OnExit] = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._state = state
        self._on_exit = on_exit
        self._nav_buttons: dict[str, ctk.CTkButton] = {}
        self._content: Optional[ctk.CTkBaseClass] = None

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_nav()
        self.show_section("overview")

    def _build_nav(self) -> None:
        p = self.p
        nav = ctk.CTkFrame(self, fg_color=p.surface, corner_radius=0, width=200)
        nav.grid(row=0, column=0, sticky="nsw")
        nav.grid_propagate(False)

        head = ctk.CTkFrame(nav, fg_color="transparent")
        head.grid(row=0, column=0, padx=18, pady=(20, 14), sticky="w")
        _gear = kit.icon("settings", 20)
        if _gear is not None:
            ctk.CTkLabel(head, text="", image=_gear).grid(row=0, column=0, padx=(0, 10))
        ctk.CTkLabel(head, text=_("Настройки"), font=fonts.heading(), text_color=p.text).grid(
            row=0, column=1, sticky="w"
        )
        for i, (key, label) in enumerate(_SECTIONS, start=1):
            glyph = {"about": "info", "advanced": "mode_advanced"}.get(key, key)
            img = kit.icon(kit.ICON_FOR.get(glyph, glyph), 18)
            btn = ctk.CTkButton(
                nav, text=_(label), font=fonts.body(), anchor="w",
                image=img, compound="left",
                fg_color="transparent", hover_color=p.surface_hover, text_color=p.text,
                corner_radius=8, command=lambda k=key: self.show_section(k),
            )
            btn.grid(row=i, column=0, padx=10, pady=2, sticky="ew")
            self._nav_buttons[key] = btn

        if self._on_exit is not None:
            ctk.CTkButton(
                nav, text=_("← Выход"), font=fonts.body(), fg_color=p.fail,
                hover_color="#DC2626", text_color="#FFFFFF", height=30, width=120,
                corner_radius=8, command=self._on_exit,
            ).grid(row=len(_SECTIONS) + 2, column=0, padx=10, pady=(20, 10))
        nav.grid_columnconfigure(0, weight=1)

    def show_section(self, key: str) -> None:
        # Highlight the active nav item.
        for k, btn in self._nav_buttons.items():
            btn.configure(fg_color=self.p.accent if k == key else "transparent")

        if self._content is not None:
            self._content.destroy()

        if key == "overview":
            from .overview_screen import OverviewScreen

            self._content = OverviewScreen(self, self.p, self._client)
        elif key == "diagnostics":
            from .diagnostics_screen import DiagnosticsScreen

            self._content = DiagnosticsScreen(self, self.p, self._client)
        elif key == "core":
            from .core_screen import CoreScreen

            self._content = CoreScreen(self, self.p, self._client, self._state)
        elif key == "nodes":
            from .nodes_screen import NodesScreen

            self._content = NodesScreen(self, self.p, self._client)
        elif key == "rules":
            from .rules_screen import RulesScreen

            self._content = RulesScreen(self, self.p, self._client)
        elif key == "access":
            from .access_screen import AccessScreen

            self._content = AccessScreen(self, self.p, self._client)
        elif key == "antidpi":
            from .antidpi_screen import AntiDPIScreen

            self._content = AntiDPIScreen(self, self.p, self._client)
        elif key == "security":
            from .security_screen import SecurityScreen

            self._content = SecurityScreen(self, self.p, self._client)
        elif key == "advanced":
            from .advanced_screen import AdvancedScreen

            self._content = AdvancedScreen(self, self.p, self._client,
                                           on_router_reset=self._on_exit)
        elif key == "about":
            from .about_screen import AboutScreen

            self._content = AboutScreen(self, self.p)
        else:
            self._content = self._stub(dict(_SECTIONS)[key])
        self._content.grid(row=0, column=1, sticky="nsew")

    def _stub(self, title: str) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(self, fg_color="transparent")
        frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(frame, text=_(title), font=fonts.title(), text_color=self.p.text).grid(
            row=0, column=0, padx=32, pady=(40, 8), sticky="w"
        )
        ctk.CTkLabel(
            frame, text=_("Раздел в разработке."), font=fonts.body(), text_color=self.p.text_muted
        ).grid(row=1, column=0, padx=32, sticky="w")
        return frame
