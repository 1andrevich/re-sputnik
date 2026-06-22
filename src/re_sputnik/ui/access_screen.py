# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Access control section — global filter mode + per-device independent toggles.

Lists DHCP-lease devices. The global mode (Отключён / Только выбранные / Все, кроме
выбранных) governs the device filter list; on top of that each device has three
INDEPENDENT switches that can be combined: filter membership (Через VPN/Напрямую,
meaning set by the global mode), Игровой (TCP-only), Весь трафик (global proxy).
Writes the homeproxy.control.lan_* uci lists; a deliberate service restart applies.
"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ..engine import access as access_engine
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import N_, _

# Display labels are marked for extraction with N_ and translated with _() at the
# render/lookup sites, so a runtime language switch is reflected consistently.
_GLOBAL_LABELS = {
    "disabled": N_("Отключён"),
    "listed_only": N_("Только выбранные"),
    "except_listed": N_("Все, кроме выбранных"),
}

_MODE_HINT = {
    "disabled": N_("Режим контроля доступа отключён. Вы можете выбрать для устройства режимы "
                "«Игровой» и «Весь трафик». Подробнее о режимах ниже."),
    "listed_only": N_("Заблокированные ресурсы идут через VPN по правилам — только на отмеченных "
                   "«Через VPN» устройствах. Остальные идут полностью напрямую."),
    "except_listed": N_("Заблокированные ресурсы идут через VPN по правилам на всех устройствах, "
                     "кроме отмеченных «Напрямую» — те идут полностью мимо VPN."),
}

# Per-device filter checkbox label, by global mode (None = filter toggle hidden).
_FILTER_LABEL = {"listed_only": N_("Через VPN"), "except_listed": N_("Напрямую")}

_GAMING_HINT = N_("«Игровой» — через VPN идёт только TCP (сайты, почта), а игровой и голосовой "
                "трафик идёт напрямую. Включите, если есть проблемы с подключением к игровым серверам.")
_GLOBAL_HINT = N_("«Весь трафик» — всё устройство идёт через VPN, в обход правил.")
_LEGEND_DISABLED_PREFIX = N_("Режим «Отключён»: список «Через VPN / Напрямую» не действует.")


class AccessScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=0, column=0, padx=24, pady=16, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self._body, text=_("Контроль доступа"), font=fonts.title(),
                     image=kit.icon(kit._ICON_FOR["access"], 26), compound="left",
                     text_color=palette.text).grid(row=0, column=0, pady=(4, 8), sticky="w")
        self._status = ctk.CTkLabel(self._body, text=_("Считываю устройства…"), font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w")
        self._status.grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._mode_card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._mode_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._mode_card.grid_columnconfigure(1, weight=1)

        # Top "Применить" — duplicated right under the mode so the user doesn't have
        # to scroll past the whole device list to the bottom button. Both apply
        # buttons are kept in sync (_apply_btns) and trigger the same restart.
        top_apply = ctk.CTkFrame(self._body, fg_color="transparent")
        top_apply.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        top_apply.grid_columnconfigure(0, weight=1)
        self._restart_btn_top = ctk.CTkButton(top_apply, text=_("Применить изменения"), font=fonts.body(),
                                               width=200, fg_color=palette.accent, text_color=palette.accent_fg,
                                               hover_color=palette.accent_hover, state="disabled",
                                               command=self._restart)
        self._restart_btn_top.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(top_apply, text=_("Выбор режима и настройки устройств вступают в силу только после "
                     "нажатия «Применить изменения»."), font=fonts.small(), text_color=palette.text_muted,
                     wraplength=560, justify="left", anchor="w").grid(row=1, column=0, sticky="w", pady=(6, 0))

        self._dev_card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._dev_card.grid(row=4, column=0, sticky="ew")
        self._dev_card.grid_columnconfigure(0, weight=1)
        self._restart_btn = ctk.CTkButton(self._body, text=_("Применить изменения"), font=fonts.body(),
                                           width=200, fg_color=palette.accent, text_color=palette.accent_fg,
                                           hover_color=palette.accent_hover, state="disabled",
                                           command=self._restart)
        self._restart_btn.grid(row=5, column=0, pady=(12, 8), sticky="w")
        self._apply_btns = (self._restart_btn_top, self._restart_btn)
        self.refresh()

    # ----- read ---------------------------------------------------------

    def refresh(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            policy = access_engine.get_policy(client)
            devices = access_engine.merge_configured(
                access_engine.list_devices(client), policy)
            return {"devices": devices, "policy": policy}

        run_async(self, task, self._render, lambda e: self._status.configure(
            text=_("Ошибка: {0}").format(e), text_color=self.p.fail))

    def _render(self, d: dict[str, Any]) -> None:
        self._status.configure(text="")
        self._policy = d["policy"]
        self._devices = d["devices"]
        self._render_mode_card()
        self._render_devices()

    def _render_mode_card(self) -> None:
        p = self.p
        for w in self._mode_card.winfo_children():
            w.destroy()
        mode = self._policy["mode"]
        ctk.CTkLabel(self._mode_card, text=_("Режим контроля"), font=fonts.body(),
                     text_color=p.text_muted).grid(row=0, column=0, padx=(16, 12), pady=(12, 4), sticky="w")
        gm = ctk.CTkOptionMenu(self._mode_card, values=[_(v) for v in _GLOBAL_LABELS.values()],
                               font=fonts.body(),
                               fg_color=p.surface_hover, button_color=p.accent,
                               button_hover_color=p.accent_hover, command=self._on_global)
        gm.set(_(_GLOBAL_LABELS.get(mode, list(_GLOBAL_LABELS.values())[0])))
        gm.grid(row=0, column=1, padx=(0, 16), pady=(12, 4), sticky="ew")
        hint = _MODE_HINT.get(mode)
        if hint:
            ctk.CTkLabel(self._mode_card, text=_(hint), font=fonts.small(), text_color=p.text_muted,
                         wraplength=440, justify="left").grid(
                row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="w")

    def _render_devices(self) -> None:
        p = self.p
        for w in self._dev_card.winfo_children():
            w.destroy()
        mode = self._policy["mode"]
        ctk.CTkLabel(self._dev_card, text=_("Устройства ({0})").format(len(self._devices)), font=fonts.heading(),
                     text_color=p.text).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        legend = _(_GAMING_HINT) + "\n" + _(_GLOBAL_HINT)
        if mode == "disabled":
            legend = _(_LEGEND_DISABLED_PREFIX) + "\n" + legend
        ctk.CTkLabel(self._dev_card, text=legend,
                     font=fonts.small(), text_color=p.text_muted, wraplength=560,
                     justify="left", anchor="w").grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        if not self._devices:
            ctk.CTkLabel(self._dev_card, text=_("Нет устройств в DHCP-лизах."), font=fonts.small(),
                         text_color=p.text_muted).grid(row=2, column=0, padx=16, pady=(0, 12), sticky="w")
            return
        for i, dev in enumerate(self._devices, start=2):
            flags = access_engine.device_flags(dev.ip, self._policy)
            frame = ctk.CTkFrame(self._dev_card, fg_color="transparent")
            frame.grid(row=i, column=0, padx=12, pady=(2, 6), sticky="ew")
            frame.grid_columnconfigure(0, weight=1)

            head = ctk.CTkFrame(frame, fg_color="transparent")
            head.grid(row=0, column=0, sticky="ew")
            head.grid_columnconfigure(0, weight=1)
            name_box = ctk.CTkFrame(head, fg_color="transparent")
            name_box.grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(name_box, text=dev.hostname, font=fonts.body(), text_color=p.text,
                         anchor="w").pack(side="left")
            if dev.manual:  # configured IP not in current DHCP leases (e.g. added in LuCI)
                ctk.CTkLabel(name_box, text=_("  · вне DHCP"), font=fonts.small(),
                             text_color=p.text_muted).pack(side="left")
            ctk.CTkLabel(head, text=dev.ip, font=fonts.small(), text_color=p.text_muted,
                         anchor="e").grid(row=0, column=1, sticky="e", padx=4)

            checks = ctk.CTkFrame(frame, fg_color="transparent")
            checks.grid(row=1, column=0, sticky="w", pady=(2, 0))
            col = 0
            filt_lbl = _FILTER_LABEL.get(mode)
            if filt_lbl:
                self._add_check(checks, col, _(filt_lbl), flags["filter"], dev.ip, "filter")
                col += 1
            self._add_check(checks, col, _("Игровой (TCP)"), flags["gaming"], dev.ip, "gaming")
            col += 1
            self._add_check(checks, col, _("Весь трафик"), flags["global"], dev.ip, "global")
        ctk.CTkLabel(self._dev_card, text="", height=4).grid(row=len(self._devices) + 2, column=0)

    def _add_check(self, parent: ctk.CTkBaseClass, col: int, text: str, on: bool,
                   ip: str, flag: str) -> None:
        var = ctk.StringVar(value="1" if on else "0")
        ctk.CTkCheckBox(parent, text=text, font=fonts.small(), variable=var,
                        onvalue="1", offvalue="0", checkbox_width=18, checkbox_height=18,
                        fg_color=self.p.accent, hover_color=self.p.accent_hover,
                        command=lambda: self._on_flag(ip, flag, var.get() == "1")
                        ).grid(row=0, column=col, padx=(0, 16), sticky="w")

    # ----- edits --------------------------------------------------------

    def _mark_dirty(self) -> None:
        for b in self._apply_btns:
            b.configure(state="normal")
        self._status.configure(text=_("Изменено. Нажмите «Применить изменения»."),
                               text_color=self.p.warn)

    def _on_global(self, label: str) -> None:
        # Reverse-map the (translated) selected label back to its mode key.
        mode = {_(v): k for k, v in _GLOBAL_LABELS.items()}.get(label)
        client = self._client

        def done(_r: Any) -> None:
            self._policy["mode"] = mode
            self._render_mode_card()
            self._render_devices()  # filter checkbox meaning changes with the mode
            self._mark_dirty()

        run_async(self, lambda: access_engine.set_global_mode(client, mode), done, self._err)

    def _on_flag(self, ip: str, flag: str, on: bool) -> None:
        client = self._client
        mode = self._policy["mode"]

        def done(_r: Any) -> None:
            # keep the local policy cache in sync so a later mode switch re-renders correctly
            name = access_engine._flag_list_name(flag, mode)
            if name:
                s = self._policy["lists"][name]
                s.add(ip) if on else s.discard(ip)
            self._mark_dirty()

        run_async(self, lambda: access_engine.set_device_flag(client, ip, flag, on, mode),
                  done, self._err)

    def _err(self, e: BaseException) -> None:
        self._status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)

    def _restart(self) -> None:
        for b in self._apply_btns:
            b.configure(state="disabled", text=_("Применяю…"))
        client = self._client
        run_async(self, lambda: client.ubus_homeproxy("diag_service_restart", timeout=40),
                  self._after_restart, self._restart_err)

    def _restart_err(self, e: BaseException) -> None:
        for b in self._apply_btns:
            b.configure(state="normal", text=_("Применить изменения"))
        self._status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)

    def _after_restart(self, res: dict[str, Any]) -> None:
        for b in self._apply_btns:
            b.configure(text=_("Применить изменения"))
        if res.get("result"):
            self._status.configure(text=_("Изменения применены."), text_color=self.p.ok)
        else:
            for b in self._apply_btns:
                b.configure(state="normal")
            self._status.configure(text=_("Не удалось применить изменения."), text_color=self.p.fail)
