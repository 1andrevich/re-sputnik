# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Пошаговая настройка — финальные рекомендации.

Optional housekeeping at the end of setup: the LuCI firmware-upgrade login
check, and an optional zram-swap install (recommended on low-RAM devices).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import customtkinter as ctk

from ..engine import finalize as fin
from ..engine import overview as ov_engine
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import _, luci_lang

OnDone = Callable[[], None]


class FinalizeScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, on_done: OnDone, on_back: Optional[OnDone] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_done = on_done
        self._on_back = on_back
        self._dhcp_var = ctk.StringVar(value="1")  # hide device name in DHCP requests
        self._ntp_var = ctk.StringVar(value="1")   # RU NTP pool

        self._sc = kit.WizardScaffold(self, palette, step=8, label=_("Завершение"), footer=False)
        self._scroll = self._sc.content
        b = self._scroll

        ctk.CTkLabel(b, text=_("Завершение"), font=fonts.title(), text_color=palette.text).grid(
            row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        ctk.CTkLabel(b, text=_("Несколько необязательных рекомендаций."), font=fonts.body(),
                     text_color=palette.text_muted).grid(row=1, column=0, pady=(0, 12), padx=32,
                                                         sticky="w")

        # --- router name (hostname) ------------------------------------
        hn = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        hn.grid(row=2, column=0, padx=32, pady=(0, 12), sticky="ew")
        hn.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(hn, palette, "network", _("Имя роутера")).grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(hn, text=_("Как роутер называется в сети и в веб-интерфейсе. Сейчас обычно "
                     "«OpenWrt» — можно задать своё. Латиница, цифры, дефис, без пробелов."),
                     font=fonts.small(), text_color=palette.text_muted, wraplength=520,
                     justify="left").grid(row=1, column=0, padx=16, sticky="w")
        hrow = ctk.CTkFrame(hn, fg_color="transparent")
        hrow.grid(row=2, column=0, padx=16, pady=(6, 12), sticky="ew")
        hrow.grid_columnconfigure(0, weight=1)
        # Disabled until the page loads the CURRENT hostname — so the user can't type
        # a new name into an empty field before the existing value arrives.
        self._host = ctk.CTkEntry(hrow, font=fonts.body(), placeholder_text=_("Загрузка текущего имени…"),
                                  state="disabled")
        self._host.grid(row=0, column=0, sticky="ew")
        self._host_btn = ctk.CTkButton(hrow, text=_("Переименовать"), font=fonts.body(), width=130,
                                       fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                       state="disabled", command=self._rename)
        self._host_btn.grid(row=0, column=1, padx=(8, 0))
        # Feedback right here, next to the button — the screen-wide status line is far
        # down a long scroll and would be off-screen.
        self._host_status = ctk.CTkLabel(hn, text="", font=fonts.small(),
                                         text_color=palette.text_muted, anchor="w",
                                         wraplength=520, justify="left")
        self._host_status.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")

        # --- zram ------------------------------------------------------
        zr = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        zr.grid(row=4, column=0, padx=32, pady=(12, 0), sticky="ew")
        zr.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(zr, palette, "resource", _("zram-swap (рекомендуется)")).grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(zr, text=_("Сжатый swap в ОЗУ — снижает риск нехватки памяти на устройствах с "
                     "малым объёмом RAM."), font=fonts.small(), text_color=palette.text_muted,
                     wraplength=520, justify="left").grid(row=1, column=0, padx=16, sticky="w")
        self._zram_status = ctk.CTkLabel(zr, text=_("Проверяю…"), font=fonts.small(),
                                         text_color=palette.text_muted)
        self._zram_status.grid(row=2, column=0, padx=16, pady=(4, 2), sticky="w")
        self._zram_btn = ctk.CTkButton(zr, text=_("Установить zram-swap"), font=fonts.body(),
                                       fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                       command=self._install_zram, state="disabled")
        self._zram_btn.grid(row=3, column=0, padx=16, pady=(4, 12), sticky="w")

        # --- optional LuCI apps (UPnP, SQM) ----------------------------
        self._app_btns: dict[str, ctk.CTkButton] = {}
        ap = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        ap.grid(row=5, column=0, padx=32, pady=(12, 0), sticky="ew")
        ap.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(ap, text=_("Дополнительные приложения LuCI (необязательно)"),
                     font=fonts.heading(), text_color=palette.text).grid(
            row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        for i, (pkg, title, desc) in enumerate(fin.OPTIONAL_APPS):
            rowf = ctk.CTkFrame(ap, fg_color="transparent")
            rowf.grid(row=i + 1, column=0, padx=16, pady=(2, 4), sticky="ew")
            rowf.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(rowf, text=_(title), font=fonts.body(), text_color=palette.text,
                         anchor="w").grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(rowf, text=_(desc), font=fonts.small(), text_color=palette.text_muted,
                         anchor="w", wraplength=440, justify="left").grid(row=1, column=0, sticky="w")
            btn = ctk.CTkButton(rowf, text=_("Установить"), font=fonts.body(), width=120,
                                fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                command=lambda p=pkg: self._install_app(p))
            btn.grid(row=0, column=1, rowspan=2, padx=(8, 0))
            self._app_btns[pkg] = btn
        ctk.CTkLabel(ap, text=_("После установки оба приложения требуют активации и дополнительной "
                     "настройки в меню «Дополнительно» или в веб-интерфейсе роутера."),
                     font=fonts.small(), text_color=palette.warn, wraplength=520,
                     justify="left").grid(
            row=len(fin.OPTIONAL_APPS) + 1, column=0, padx=16, pady=(2, 12), sticky="w")

        # --- new-device privacy (DHCP hostname + NTP) ------------------
        pv = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        pv.grid(row=6, column=0, padx=32, pady=(12, 0), sticky="ew")
        pv.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(pv, palette, "security", _("Приватность устройства")).grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(pv, text=_("Применено для нового устройства, чтобы роутер не выдавал себя "
                     "провайдеру. Можно отключить."), font=fonts.small(),
                     text_color=palette.text_muted, wraplength=520, justify="left").grid(
            row=1, column=0, padx=16, pady=(0, 6), sticky="w")
        self._dhcp_switch = ctk.CTkSwitch(
            pv, text=_("Не отправлять имя устройства в DHCP-запросах"), font=fonts.body(),
            variable=self._dhcp_var, onvalue="1", offvalue="0", progress_color=palette.accent,
            command=self._toggle_dhcp)
        self._dhcp_switch.grid(row=2, column=0, padx=16, pady=4, sticky="w")
        self._ntp_switch = ctk.CTkSwitch(
            pv, text=_("Российский пул NTP (0–3.ru.pool.ntp.org)"), font=fonts.body(),
            variable=self._ntp_var, onvalue="1", offvalue="0", progress_color=palette.accent,
            command=self._toggle_ntp)
        self._ntp_switch.grid(row=3, column=0, padx=16, pady=(4, 12), sticky="w")

        ctk.CTkButton(b, text=_("Готово"), font=fonts.heading(), height=42, fg_color=palette.ok,
                      hover_color=palette.accent_hover, command=on_done).grid(
            row=7, column=0, padx=32, pady=(18, 6), sticky="ew")
        if on_back is not None:
            ctk.CTkButton(b, text=_("← Назад"), font=fonts.body(), fg_color="transparent",
                          hover_color=palette.surface_hover, width=90, command=on_back).grid(
                row=8, column=0, padx=32, pady=(0, 4), sticky="w")

        self._status = ctk.CTkLabel(b, text="", font=fonts.small(), text_color=palette.text_muted)
        self._status.grid(row=9, column=0, padx=32, pady=(0, 12), sticky="w")

        self._load()

    # ----- load ---------------------------------------------------------

    def _load(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            # New-device privacy defaults, applied once (idempotent) during setup.
            if not fin.dhcp_hostname_hidden(client):
                fin.set_dhcp_hostname_hidden(client, True)
            if not fin.ntp_is_ru(client):
                fin.set_ru_ntp(client, True)
            # Disable the LuCI firmware-upgrade online check silently — no prompt
            # (best-effort; no-op if attendedsysupgrade isn't installed).
            fin.set_check_for_upgrades(client, False)
            return {"zram": fin.zram_status(client),
                    "hostname": client.run("uci -q get system.@system[0].hostname").stdout.strip(),
                    "apps": {pkg: fin.app_installed(client, pkg)
                             for pkg, _t, _d in fin.OPTIONAL_APPS},
                    "dhcp_hidden": fin.dhcp_hostname_hidden(client),
                    "ntp_ru": fin.ntp_is_ru(client)}

        run_async(self, task, self._render, self._load_err)

    def _unlock_host(self) -> None:
        self._host.configure(state="normal")
        self._host_btn.configure(state="normal")

    def _load_err(self, e: BaseException) -> None:
        # Unlock the field even if the load failed, so the user isn't stuck.
        self._unlock_host()
        self._status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)

    def _render(self, d: dict[str, Any]) -> None:
        # Page loaded → unlock the name field and fill in the current hostname.
        self._unlock_host()
        if d.get("hostname") and not self._host.get():
            self._host.insert(0, d["hostname"])
        for pkg, installed in (d.get("apps") or {}).items():
            if installed and pkg in self._app_btns:
                self._app_btns[pkg].configure(state="disabled", text=_("Установлено ✓"))
        # Reflect the (now applied) privacy defaults on the toggles.
        self._dhcp_var.set("1" if d.get("dhcp_hidden") else "0")
        self._ntp_var.set("1" if d.get("ntp_ru") else "0")
        z = d["zram"]
        if z.installed:
            self._zram_status.configure(
                text=_("Установлен") + (_(" и активен ✓") if z.active else _(" (не активен)")),
                text_color=self.p.ok if z.active else self.p.warn)
            self._zram_btn.configure(state="disabled", text=_("Уже установлен"))
        else:
            self._zram_status.configure(text=_("Не установлен."), text_color=self.p.text_muted)
            self._zram_btn.configure(state="normal")

    # ----- actions ------------------------------------------------------

    def _install_app(self, pkg: str) -> None:
        btn = self._app_btns[pkg]
        btn.configure(state="disabled", text=_("Устанавливаю…"))
        self._status.configure(text=_("Устанавливаю {0} (+ русский язык)…").format(pkg),
                               text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: fin.install_luci_app(client, pkg, language=luci_lang()),
                  lambda ok: self._app_done(pkg, ok), lambda e: self._app_err(pkg, e))

    def _app_done(self, pkg: str, ok: bool) -> None:
        btn = self._app_btns[pkg]
        if ok:
            btn.configure(state="disabled", text=_("Установлено ✓"))
            self._status.configure(text=_("{0} установлено.").format(pkg), text_color=self.p.ok)
        else:
            btn.configure(state="normal", text=_("Установить"))
            self._status.configure(text=_("Не удалось установить {0} (нет в фиде или нет связи).").format(pkg),
                                   text_color=self.p.warn)

    def _app_err(self, pkg: str, exc: BaseException) -> None:
        self._app_btns[pkg].configure(state="normal", text=_("Установить"))
        self._status.configure(text=_("Ошибка установки {0}: {1}").format(pkg, exc), text_color=self.p.fail)

    def _rename(self) -> None:
        name = self._host.get().strip()
        if not name:
            self._host_status.configure(text=_("Введите имя роутера."), text_color=self.p.warn)
            return
        self._host_btn.configure(state="disabled", text=_("Применяю…"))
        self._host_status.configure(text=_("Переименовываю роутер…"), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: ov_engine.set_hostname(client, name), self._renamed, self._rename_err)

    def _renamed(self, name: str) -> None:
        self._host_btn.configure(state="normal", text=_("Переименовать"))
        self._host_status.configure(text=_("Готово — роутер переименован в «{0}».").format(name),
                                    text_color=self.p.ok)

    def _rename_err(self, exc: BaseException) -> None:
        self._host_btn.configure(state="normal", text=_("Переименовать"))
        self._host_status.configure(text=_("Не удалось переименовать: {0}").format(exc), text_color=self.p.fail)

    def _toggle_dhcp(self) -> None:
        on = self._dhcp_var.get() == "1"
        client = self._client
        run_async(self, lambda: fin.set_dhcp_hostname_hidden(client, on),
                  lambda _r: self._status.configure(
                      text=_("Имя устройства в DHCP ") + (_("скрыто.") if on else _("восстановлено.")),
                      text_color=self.p.ok),
                  lambda e: self._status.configure(text=_("Не сохранено: {0}").format(e), text_color=self.p.fail))

    def _toggle_ntp(self) -> None:
        on = self._ntp_var.get() == "1"
        client = self._client
        run_async(self, lambda: fin.set_ru_ntp(client, on),
                  lambda _r: self._status.configure(
                      text="NTP: " + (_("российский пул.") if on else _("пул OpenWrt.")),
                      text_color=self.p.ok),
                  lambda e: self._status.configure(text=_("Не сохранено: {0}").format(e), text_color=self.p.fail))

    def _install_zram(self) -> None:
        self._zram_btn.configure(state="disabled", text=_("Устанавливаю…"))
        self._status.configure(text=_("Устанавливаю zram-swap…"), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: fin.install_zram(client), self._zram_done,
                  lambda e: (self._zram_btn.configure(state="normal", text=_("Установить zram-swap")),
                             self._status.configure(text=_("Не удалось: {0}").format(e), text_color=self.p.fail)))

    def _zram_done(self, z: fin.ZramStatus) -> None:
        if z.installed:
            self._zram_status.configure(
                text=_("Установлен") + (_(" и активен ✓") if z.active else _(" (не активен)")),
                text_color=self.p.ok if z.active else self.p.warn)
            self._zram_btn.configure(text=_("Уже установлен"))
            self._status.configure(text=_("zram-swap установлен."), text_color=self.p.ok)
        else:
            self._zram_btn.configure(state="normal", text=_("Установить zram-swap"))
            self._status.configure(text=_("Установка не подтвердилась."), text_color=self.p.warn)
