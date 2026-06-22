# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Пошаговая настройка — phase «Интернет».

Checks whether the router can reach the internet. If not, offers a wired WAN
setup (when a cable is plugged) and/or a Wi-Fi client (STA) uplink as a
temporary solution. For Wi-Fi the router SCANS the air itself (OpenWrt) and
shows the networks it sees — name, band (2.4/5/6 GHz) and whether they're
locked — so the user picks one instead of typing an SSID by hand.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import customtkinter as ctk

from ..engine import network as net
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import _

OnDone = Callable[[], None]


def _signal_bars(dbm: int) -> str:
    if dbm >= -55:
        return "▂▄▆█"
    if dbm >= -67:
        return "▂▄▆ "
    if dbm >= -78:
        return "▂▄  "
    return "▂   "


class InternetScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, on_done: OnDone, allow_skip: bool = False,
                 on_back: Optional[OnDone] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_done = on_done
        self._on_back = on_back
        # Staging (Option 3): let the user pre-enter WAN details and move on even
        # without internet — the router may be configured away from the ISP socket.
        self._allow_skip = allow_skip
        self._radios: list[net.Radio] = []
        self._wan: Optional[net.WanInfo] = None
        self._sel: Optional[net.WifiNetwork] = None

        step = 2 if not allow_skip else 1  # preinstall flow reaches internet earlier
        # Footer only when there's somewhere to go back to — it carries the
        # "← Назад" link (fixed at the bottom, always reachable; this step is past
        # the irreversible firstrun, so back leaves the wizard to the connection
        # screen rather than re-entering step 1).
        self._sc = kit.WizardScaffold(self, palette, step=step, label=_("Интернет"),
                                      footer=on_back is not None)
        if on_back is not None and self._sc.footer is not None:
            self._sc.footer.set_link(_("← Назад"), on_back)
        self._scroll = self._sc.content
        body = self._scroll

        ctk.CTkLabel(body, text=_("Интернет"), font=fonts.title(), text_color=palette.text).grid(
            row=0, column=0, pady=(28, 4), padx=32, sticky="w")
        # Verdict + a manual re-check button side by side. Carrier/IP state isn't
        # pushed by the router, so after plugging a cable the user taps «Проверить»
        # to re-run the check instead of leaving/returning to the screen.
        head = ctk.CTkFrame(body, fg_color="transparent")
        head.grid(row=1, column=0, padx=32, pady=(0, 6), sticky="ew")
        head.grid_columnconfigure(0, weight=1)
        self._verdict = ctk.CTkLabel(head, text=_("Проверяю доступ в интернет…"), font=fonts.heading(),
                                     text_color=palette.text_muted, anchor="w", wraplength=480,
                                     justify="left")
        self._verdict.grid(row=0, column=0, sticky="w")
        self._check_btn = ctk.CTkButton(
            head, text=_("Проверить"), font=fonts.body(), width=110, height=34,
            fg_color="transparent", border_width=1, border_color=palette.border,
            text_color=palette.text, hover_color=palette.surface_hover, command=self.refresh)
        self._check_btn.grid(row=0, column=1, padx=(8, 0), sticky="ne")

        # Subnet-conflict (double-NAT) warning — shown above everything when the WAN
        # lease overlaps the LAN subnet. Hidden by default.
        self._conflict_box = ctk.CTkFrame(body, fg_color="transparent")
        self._conflict_box.grid(row=2, column=0, padx=32, pady=(0, 6), sticky="ew")
        self._conflict_box.grid_columnconfigure(0, weight=1)
        self._conflict_box.grid_remove()
        self._conflict: Optional[net.SubnetConflict] = None

        # Green "Далее →" to match the other wizard steps' proceed button (palette.ok).
        self._next_btn = ctk.CTkButton(body, text=_("Далее →"), font=fonts.heading(), height=42,
                                       fg_color=palette.ok, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                       command=on_done)
        self._next_btn.grid(row=3, column=0, padx=32, pady=(0, 8), sticky="ew")
        self._next_btn.grid_remove()

        self._choices = ctk.CTkFrame(body, fg_color="transparent")
        self._choices.grid(row=4, column=0, padx=0, sticky="ew")
        self._choices.grid_columnconfigure(0, weight=1)
        self._status = ctk.CTkLabel(body, text="", font=fonts.small(), text_color=palette.text_muted,
                                    anchor="w", wraplength=560, justify="left")
        self._status.grid(row=5, column=0, padx=32, pady=(4, 12), sticky="w")
        self.refresh()

    # ----- check --------------------------------------------------------

    def refresh(self) -> None:
        self._verdict.configure(text=_("Проверяю доступ в интернет…"), text_color=self.p.text_muted)
        self._check_btn.configure(state="disabled", text=_("Проверяю…"))
        self._next_btn.grid_remove()
        self._sel = None
        for w in self._choices.winfo_children():
            w.destroy()
        client = self._client

        def task() -> dict[str, Any]:
            # Detect the double-NAT subnet clash regardless of whether ping works —
            # it can break routing even when a lease was obtained.
            conflict = net.detect_subnet_conflict(client)
            if net.check_internet(client):
                return {"ok": True, "conflict": conflict}
            return {"ok": False, "wan": net.wan_info(client), "radios": net.list_radios(client),
                    "conflict": conflict}

        run_async(self, task, self._render, self._err)

    def _err(self, e: BaseException) -> None:
        self._verdict.configure(text=_("Ошибка проверки: {0}").format(e), text_color=self.p.fail)
        self._check_btn.configure(state="normal", text=_("Проверить"))

    def _render(self, d: dict[str, Any]) -> None:
        p = self.p
        self._check_btn.configure(state="normal", text=_("Проверить"))
        self._conflict = d.get("conflict")
        if d["ok"]:
            self._verdict.configure(text=_("✓ Интернет есть — можно продолжать"), text_color=p.ok)
            self._next_btn.configure(text=_("Далее →"))
            self._next_btn.grid()
        else:
            if self._allow_skip:
                self._verdict.configure(
                    text=_("Роутер пока без интернета. Можно заранее задать параметры подключения "
                         "(они применятся, когда появится кабель) и продолжить."),
                    text_color=p.text_muted)
            else:
                self._verdict.configure(
                    text=_("✗ Роутер не в интернете. Выберите, как подключить:"), text_color=p.warn)
            self._radios = d["radios"]
            self._wan = d["wan"]
            self._build_options()
            if self._allow_skip:
                self._next_btn.configure(text=_("Продолжить без интернета →"))
                self._next_btn.grid()
        self._render_conflict()

    def _render_conflict(self) -> None:
        for w in self._conflict_box.winfo_children():
            w.destroy()
        c = self._conflict
        if c is None:
            self._conflict_box.grid_remove()
            return
        p = self.p
        card = ctk.CTkFrame(self._conflict_box, fg_color=p.surface, corner_radius=12)
        card.grid(row=0, column=0, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=_("⚠ Конфликт адресов сети"), font=fonts.heading(),
                     text_color=p.warn).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            card,
            text=(_("Роутер провайдера выдал WAN адрес {0} из той же подсети {1}, что используется для домашней сети ({2}). Из-за наложения подсетей маршрутизация ломается и интернет через роутер работать не будет.\n\nРешение — перенести роутер на свободный адрес. Ниже предложен подходящий, при желании укажите свой (частный адрес из другой подсети).").format(c.wan_ip, c.wan_subnet, c.lan_ip)),
            font=fonts.small(), text_color=p.text_muted, wraplength=520,
            justify="left").grid(row=1, column=0, padx=16, sticky="w")
        ctk.CTkLabel(
            card,
            text=(_("ВАЖНО: после смены приложение потеряет связь с роутером — это нормально. Подождите 20–30 секунд (компьютер получит новый адрес) и переподключитесь к роутеру по адресу {0}.").format(c.suggested_lan_ip)),
            font=fonts.small(), text_color=p.warn, wraplength=520, justify="left").grid(
            row=2, column=0, padx=16, pady=(6, 0), sticky="w")
        fixrow = ctk.CTkFrame(card, fg_color="transparent")
        fixrow.grid(row=3, column=0, padx=16, pady=(8, 12), sticky="w")
        ctk.CTkLabel(fixrow, text=_("Новый адрес роутера:"), font=fonts.small(),
                     text_color=p.text_muted).grid(row=0, column=0, padx=(0, 8), sticky="w")
        self._lan_entry = ctk.CTkEntry(fixrow, font=fonts.body(), width=150)
        self._lan_entry.insert(0, c.suggested_lan_ip)
        self._lan_entry.grid(row=0, column=1, padx=(0, 8))
        self._fix_btn = ctk.CTkButton(
            fixrow, text=_("Сменить и переподключиться"), font=fonts.body(),
            fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover, command=self._fix_conflict)
        self._fix_btn.grid(row=0, column=2)
        self._conflict_box.grid()

    # ----- options ------------------------------------------------------

    def _build_options(self) -> None:
        p = self.p
        wan = self._wan
        assert wan is not None

        # --- Wired ------------------------------------------------------
        wired = ctk.CTkFrame(self._choices, fg_color=p.surface, corner_radius=12)
        wired.grid(row=0, column=0, padx=32, pady=(0, 10), sticky="ew")
        wired.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(wired, text=_("🔌  Кабельное подключение (рекомендуется)"), font=fonts.heading(),
                     text_color=p.text).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        if wan.carrier:
            cable_txt = (_("Кабель в WAN-порту обнаружен, но интернета нет. Обычно подходит DHCP; "
                         "если провайдер требует — выберите PPPoE (логин/пароль) или статический IP."))
        else:
            cable_txt = (_("Кабель в WAN-порту не обнаружен. Можно заранее ввести данные провайдера "
                         "(PPPoE/статический IP) — они применятся, как только вы вставите кабель в порт WAN."))
        ctk.CTkLabel(wired, text=cable_txt, font=fonts.small(), text_color=p.text_muted,
                     wraplength=520, justify="left").grid(row=1, column=0, padx=16, sticky="w")

        # WAN fields are available regardless of carrier: the router may sit away
        # from the ISP socket while the user pre-enters PPPoE/static details (and
        # sets up the AP). The settings apply now; internet appears once the cable
        # is in. Proxy/software steps stay gated on real connectivity downstream.
        self._proto_label = {lab: pr for pr, lab in net.WAN_PROTOCOLS}
        self._proto_menu = ctk.CTkOptionMenu(
            wired, values=[lab for _pr, lab in net.WAN_PROTOCOLS], font=fonts.body(),
            fg_color=p.surface_hover, button_color=p.accent, button_hover_color=p.accent_hover,
            command=lambda _v: self._rebuild_wan_fields())
        self._proto_menu.grid(row=2, column=0, padx=16, pady=(8, 2), sticky="ew")
        self._wan_fields = ctk.CTkFrame(wired, fg_color="transparent")
        self._wan_fields.grid(row=3, column=0, padx=16, pady=2, sticky="ew")
        self._wan_fields.grid_columnconfigure(0, weight=1)
        self._wan_entries: dict[str, ctk.CTkEntry] = {}
        ctk.CTkButton(wired, text=_("Применить"), font=fonts.body(), fg_color=p.accent, text_color=p.accent_fg,
                      hover_color=p.accent_hover, command=self._do_wan).grid(
            row=4, column=0, padx=16, pady=(6, 12), sticky="w")
        self._rebuild_wan_fields()

        # Wi-Fi-client uplink — always shown; it's the main option when there's
        # no cable at all.
        self._build_wifi_card()

    def _rebuild_wan_fields(self) -> None:
        proto = self._proto_label[self._proto_menu.get()]
        for w in self._wan_fields.winfo_children():
            w.destroy()
        self._wan_entries = {}
        spec: list[tuple[str, str, bool]] = []
        if proto == "pppoe":
            spec = [("username", _("Логин (PPPoE)"), False), ("password", _("Пароль (PPPoE)"), True)]
        elif proto == "static":
            spec = [("ipaddr", _("IP-адрес, напр. 192.168.0.10"), False),
                    ("netmask", _("Маска (255.255.255.0)"), False),
                    ("gateway", _("Шлюз, напр. 192.168.0.1"), False),
                    ("dns", _("DNS (через пробел), напр. 1.1.1.1"), False)]
        for i, (key, ph, secret) in enumerate(spec):
            e = ctk.CTkEntry(self._wan_fields, font=fonts.body(), placeholder_text=ph,
                             show="•" if secret else "")
            e.grid(row=i, column=0, pady=3, sticky="ew")
            self._wan_entries[key] = e

    def _build_wifi_card(self) -> None:
        p = self.p
        # --- Wi-Fi client ----------------------------------------------
        wifi = ctk.CTkFrame(self._choices, fg_color=p.surface, corner_radius=12)
        wifi.grid(row=1, column=0, padx=32, pady=(0, 10), sticky="ew")
        wifi.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(wifi, text=_("📶  Wi-Fi-клиент (временно)"), font=fonts.heading(),
                     text_color=p.text).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(wifi, text=_("Подключение к существующей Wi-Fi-сети как временное решение. "
                     "Для стабильной работы рекомендуется проводное подключение роутера к интернету."),
                     font=fonts.small(), text_color=p.warn, wraplength=520, justify="left").grid(
            row=1, column=0, padx=16, sticky="w")
        # No Wi-Fi radio (e.g. a VM) — can't be a Wi-Fi client; say so and stop.
        if not self._radios:
            ctk.CTkLabel(wifi, text=_("На этом устройстве нет Wi-Fi-радио — этот способ недоступен. "
                         "Используйте кабель."), font=fonts.body(), text_color=p.text_muted,
                         wraplength=520, justify="left").grid(row=2, column=0, padx=16, pady=(6, 12),
                                                              sticky="w")
            return
        self._scan_btn = ctk.CTkButton(wifi, text=_("Сканировать сети"), font=fonts.body(),
                                       fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                                       command=self._do_scan)
        self._scan_btn.grid(row=2, column=0, padx=16, pady=(8, 4), sticky="w")

        # Scanned-network list (filled by _do_scan).
        self._netlist = ctk.CTkFrame(wifi, fg_color="transparent")
        self._netlist.grid(row=3, column=0, padx=8, pady=2, sticky="ew")
        self._netlist.grid_columnconfigure(0, weight=1)

        # Connect row (password + button), revealed once a network is selected.
        self._connbox = ctk.CTkFrame(wifi, fg_color="transparent")
        self._connbox.grid(row=4, column=0, padx=16, pady=(2, 12), sticky="ew")
        self._connbox.grid_columnconfigure(0, weight=1)
        self._sel_label = ctk.CTkLabel(self._connbox, text="", font=fonts.small(),
                                       text_color=p.text, anchor="w")
        self._sel_label.grid(row=0, column=0, sticky="w", pady=(2, 2))
        self._key = ctk.CTkEntry(self._connbox, font=fonts.body(), show="•",
                                 placeholder_text=_("Пароль Wi-Fi"))
        self._key.grid(row=1, column=0, pady=4, sticky="ew")
        self._conn_btn = ctk.CTkButton(self._connbox, text=_("Подключиться"), font=fonts.body(),
                                       fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                                       command=self._do_wifi)
        self._conn_btn.grid(row=2, column=0, pady=(4, 0), sticky="w")
        self._connbox.grid_remove()

    # ----- scan ---------------------------------------------------------

    def _do_scan(self) -> None:
        self._scan_btn.configure(state="disabled", text=_("Сканирую… (~10 сек)"))
        for w in self._netlist.winfo_children():
            w.destroy()
        self._connbox.grid_remove()
        client = self._client
        run_async(self, lambda: net.scan_networks(client), self._show_nets, self._scan_err)

    def _scan_err(self, e: BaseException) -> None:
        self._scan_btn.configure(state="normal", text=_("Сканировать сети"))
        self._status.configure(text=_("Скан не удался: {0}").format(e), text_color=self.p.fail)

    def _show_nets(self, nets: list[net.WifiNetwork]) -> None:
        p = self.p
        self._scan_btn.configure(state="normal", text=_("Сканировать заново"))
        if not nets:
            ctk.CTkLabel(self._netlist, text=_("Сети не найдены. Попробуйте ещё раз."),
                         font=fonts.small(), text_color=p.text_muted).grid(row=0, column=0, sticky="w")
            return
        for i, n in enumerate(nets):
            lock = "🔒" if not n.open else "🔓"
            txt = _("{0}  {1}    {2} ГГц  {3}").format(_signal_bars(n.signal), n.ssid, n.band, lock)
            ctk.CTkButton(self._netlist, text=txt, font=fonts.body(), anchor="w",
                          fg_color=p.surface_hover, hover_color=p.accent_hover, text_color=p.text,
                          command=lambda net_=n: self._select(net_)).grid(
                row=i, column=0, padx=8, pady=2, sticky="ew")

    def _select(self, n: net.WifiNetwork) -> None:
        self._sel = n
        self._sel_label.configure(text=_("Сеть: {0} · {1} ГГц · ").format(n.ssid, n.band)
                                  + (_("открытая") if n.open else n.encryption))
        if n.open:
            self._key.grid_remove()
        else:
            self._key.grid()
            self._key.delete(0, "end")
        self._connbox.grid()

    # ----- actions ------------------------------------------------------

    def _do_wan(self) -> None:
        proto = self._proto_label[self._proto_menu.get()]
        vals = {k: e.get().strip() for k, e in self._wan_entries.items()}
        if proto == "pppoe" and not vals.get("username"):
            self._status.configure(text=_("Введите логин PPPoE."), text_color=self.p.warn)
            return
        if proto == "static" and not vals.get("ipaddr"):
            self._status.configure(text=_("Введите IP-адрес."), text_color=self.p.warn)
            return
        self._status.configure(text=_("Поднимаю кабельное подключение…"), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: net.configure_wan(
            client, proto=proto, username=vals.get("username", ""),
            password=vals.get("password", ""), ipaddr=vals.get("ipaddr", ""),
            netmask=vals.get("netmask", ""), gateway=vals.get("gateway", ""),
            dns=vals.get("dns", "")), self._after_uplink, self._err)

    def _do_wifi(self) -> None:
        n = self._sel
        if n is None:
            self._status.configure(text=_("Выберите сеть из списка."), text_color=self.p.warn)
            return
        key = "" if n.open else self._key.get()
        if not n.open and not key:
            self._status.configure(text=_("Введите пароль Wi-Fi."), text_color=self.p.warn)
            return
        radio = net.radio_for_band(self._radios, n.band)
        self._status.configure(text=_("Подключаюсь к «{0}» (до 10 сек)…").format(n.ssid),
                               text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: net.configure_wifi_sta(
            client, ssid=n.ssid, key=key, radio=radio, encryption=n.uci_encryption),
            self._after_uplink, self._err)

    def _after_uplink(self, ok: bool) -> None:
        if ok:
            # Re-check: refresh() shows the "Интернет есть" verdict + "Далее →" at
            # the TOP, so scroll back up — otherwise the user is left staring at
            # the (now empty) options area and has to scroll up to find the button.
            # Don't also write a bottom "Интернет появился" — that was a confusing
            # duplicate of the top verdict.
            self._scroll_to_top()
            self.refresh()
        else:
            self._status.configure(
                text=_("Пока без интернета. Проверьте кабель/пароль или попробуйте другой вариант."),
                text_color=self.p.fail)

    def _fix_conflict(self) -> None:
        c = self._conflict
        if c is None:
            return
        new_ip = self._lan_entry.get().strip()
        err = net.validate_new_lan_ip(new_ip, c.wan_subnet)
        if err:
            self._status.configure(text=err, text_color=self.p.warn)
            return
        from tkinter import messagebox

        agreed = messagebox.askyesno(
            _("Сменить адрес роутера"),
            _("Адрес роутера будет изменён с {0} на {1}, чтобы убрать конфликт с сетью провайдера ({2}).\n\nПосле смены приложение ПОТЕРЯЕТ связь с роутером — это нормально и ожидаемо. Через 20–30 секунд компьютер получит новый адрес, и нужно будет переподключиться к роутеру по адресу {3}.\n\nПродолжить?").format(c.lan_ip, new_ip, c.wan_subnet, new_ip))
        if not agreed:
            return
        self._fix_btn.configure(state="disabled", text=_("Меняю адрес…"))
        self._status.configure(text=_("Меняю адрес роутера…"), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: net.change_lan_ip(client, new_ip),
                  self._lan_changed, self._fix_err)

    def _lan_changed(self, new_ip: str) -> None:
        # The SSH link is about to drop (background reload) — nothing more can run on
        # the router from here. Strip the screen down to a single clear instruction.
        for w in self._choices.winfo_children():
            w.destroy()
        self._choices.grid_remove()
        self._next_btn.grid_remove()
        self._conflict_box.grid_remove()
        self._status.configure(text="")
        self._verdict.configure(
            text=(_("✓ Адрес роутера изменён на {0}.\n\nСвязь с роутером сейчас разорвётся — это нормально. Подождите 20–30 секунд, пока компьютер получит новый адрес, затем переподключитесь к роутеру по адресу {1} (заново откройте подключение в приложении).").format(new_ip, new_ip)),
            text_color=self.p.ok)

    def _fix_err(self, exc: BaseException) -> None:
        self._fix_btn.configure(state="normal", text=_("Сменить и переподключиться"))
        self._status.configure(text=_("Не удалось сменить адрес: {0}").format(exc), text_color=self.p.fail)

    def _scroll_to_top(self) -> None:
        try:
            self._scroll._parent_canvas.yview_moveto(0.0)
        except Exception:  # noqa: BLE001 — scrolling is cosmetic, never fatal
            pass
