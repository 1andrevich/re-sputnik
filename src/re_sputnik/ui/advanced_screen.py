# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Advanced ("Дополнительно") section — risky router maintenance.

Four cards, every destructive action gated by an explicit second confirmation
("Применить" → warning → "Подтвердить"):

- Резервная копия — download a full config backup; restore one from a file.
- Сеть LAN и DHCP — change the router IP/mask and DHCP range/lease.
- Постоянный IP — pin a device to a fixed address (low-risk static lease).
- Сброс к заводским — wipe the device back to firmware defaults.
"""

from __future__ import annotations

import datetime
from tkinter import filedialog
from typing import Any, Callable

import customtkinter as ctk

from ..engine import access as access_engine
from ..engine import lan as lan_engine
from ..engine import maintenance
from ..engine import network as net_engine
from ..engine import nodes as nodeng
from ..engine import overview as ov_engine
from ..engine import rules as ruleng
from ..engine import sqm as sqm_engine
from ..engine import upnp as upnp_engine
from ..router import RouterClient
from .. import profiles
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import N_, _


class _DangerConfirm(ctk.CTkFrame):
    """A two-step action: trigger button → warning + «Подтвердить»/«Отмена».

    ``command`` runs only after the second click; it receives this widget so the
    caller can call ``.busy()`` / ``.reset()`` around the async work.
    """

    def __init__(self, master: ctk.CTkBaseClass, p: Palette, *, label: str,
                 confirm_label: str, warning: str,
                 command: "Callable[[_DangerConfirm], None]", accent: bool = False,
                 read_values: "Callable[[], str | None] | None" = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = p
        self._command = command
        self._warning = warning
        self._confirm_label = confirm_label
        self._read_values = read_values  # optional pre-arm validation, returns error|None
        self.grid_columnconfigure(0, weight=1)
        color = p.accent if accent else p.fail
        hover = p.accent_hover if accent else "#DC2626"
        tcol = p.accent_fg if accent else "#FFFFFF"
        self._trigger = ctk.CTkButton(self, text=label, font=fonts.body(), fg_color=color,
                                      hover_color=hover, text_color=tcol, width=220,
                                      command=self._arm)
        self._trigger.grid(row=0, column=0, sticky="w")
        # height=1 so the empty (un-armed) box doesn't reserve CTkFrame's 200px default.
        self._box = ctk.CTkFrame(self, fg_color="transparent", height=1)
        self._box.grid(row=1, column=0, sticky="ew")
        self._status: ctk.CTkLabel | None = None

    def _arm(self) -> None:
        if self._read_values is not None:
            err = self._read_values()
            if err:
                self.set_status(err, self.p.fail)
                return
        self._trigger.grid_remove()
        for w in self._box.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._box, text=self._warning, font=fonts.small(), text_color=self.p.fail,
                     wraplength=540, justify="left", anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))
        self._confirm_btn = ctk.CTkButton(self._box, text=self._confirm_label, font=fonts.body(),
                                          fg_color=self.p.fail, hover_color="#DC2626",
                                          text_color="#FFFFFF", width=200, command=self._go)
        self._confirm_btn.grid(row=1, column=0, sticky="w")
        self._cancel_btn = ctk.CTkButton(self._box, text=_("Отмена"), font=fonts.body(),
                                         fg_color="transparent", hover_color=self.p.surface_hover,
                                         text_color=self.p.text, width=90, command=self.reset)
        self._cancel_btn.grid(row=1, column=1, padx=10, sticky="w")

    def _go(self) -> None:
        self.busy()
        self._command(self)

    def busy(self) -> None:
        if self._box.winfo_children():
            self._confirm_btn.configure(state="disabled", text=_("Выполняю…"))
            self._cancel_btn.configure(state="disabled")

    def reset(self) -> None:
        for w in self._box.winfo_children():
            w.destroy()
        self._trigger.grid()

    def set_status(self, text: str, color: str) -> None:
        if self._status is None:
            self._status = ctk.CTkLabel(self, text="", font=fonts.small(), anchor="w",
                                        wraplength=540, justify="left")
            self._status.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self._status.configure(text=text, text_color=color)


class AdvancedScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 on_router_reset: "Callable[[], None] | None" = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        # Called after a factory reset so the app can drop back to the connection
        # page — the router is wiped, so the current session is no longer valid.
        self._on_router_reset = on_router_reset
        self._lan: lan_engine.LanSettings | None = None
        self._devices: list = []
        self._leases: list = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=0, column=0, padx=24, pady=16, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self._body, text=_("Дополнительно"), font=fonts.title(),
                     image=kit.icon("mode_advanced", 26), compound="left",
                     text_color=palette.text).grid(row=0, column=0, pady=(4, 4), sticky="w")
        ctk.CTkLabel(self._body, text=_("Опасные операции с роутером. Делайте только при "
                     "необходимости и сначала скачайте резервную копию."), font=fonts.small(),
                     text_color=palette.text_muted, wraplength=620, justify="left",
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(0, 10))
        self._status = ctk.CTkLabel(self._body, text=_("Считываю настройки…"), font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w")
        self._status.grid(row=2, column=0, sticky="w", pady=(0, 8))

        self._cards = ctk.CTkFrame(self._body, fg_color="transparent")
        self._cards.grid(row=3, column=0, sticky="ew")
        self._cards.grid_columnconfigure(0, weight=1)
        self.refresh()

    def _card(self, row: int, title: str) -> ctk.CTkFrame:
        c = ctk.CTkFrame(self._cards, fg_color=self.p.surface, corner_radius=12)
        c.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        c.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text=title, font=fonts.heading(), text_color=self.p.text).grid(
            row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        return c

    # ----- read ---------------------------------------------------------

    def refresh(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            mode = ruleng.normalize_mode(client.uci_get("homeproxy.config.routing_mode") or "")
            routing: dict[str, Any] = {"mode": mode}
            if ruleng.is_selective(mode):
                dns_key = ruleng.DNS_PRESETS[mode][0]
                routing["dns_key"] = dns_key
                routing["dns_val"] = client.uci_get(f"homeproxy.config.{dns_key}") or ruleng.DNS_PRESETS[mode][1]
                if mode in ("bypass_cn", "bypass_ir"):  # UDP-node picker is cn/ir only
                    routing["udp"] = client.uci_get("homeproxy.config.main_udp_node") or "same"
                    routing["nodes"] = nodeng.list_nodes(client)
            return {
                "hostname": client.uci_get("system.@system[0].hostname") or "",
                "net_mode": lan_engine.detect_network_mode(client),
                "lan": lan_engine.get_lan_settings(client),
                "devices": access_engine.list_devices(client),
                "leases": lan_engine.list_static_leases(client),
                "wifi": net_engine.list_radio_wifi(client),
                "upnp": upnp_engine.get_status(client),
                "sqm": sqm_engine.get_settings(client),
                "sqm_ifaces": sqm_engine.wan_candidates(client),
                "routing": routing,
            }

        run_async(self, task, self._render,
                  lambda e: self._status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail))

    def _render(self, d: dict[str, Any]) -> None:
        self._status.grid_remove()
        self._hostname = d["hostname"]
        self._net_mode = d["net_mode"]
        self._lan = d["lan"]
        self._devices = d["devices"]
        self._leases = d["leases"]
        self._wifi = d["wifi"]
        self._upnp = d["upnp"]
        self._sqm = d["sqm"]
        self._sqm_ifaces = d["sqm_ifaces"]
        self._routing = d.get("routing") or {"mode": ""}
        for w in self._cards.winfo_children():
            w.destroy()
        # Running row counter so the optional UPnP/SQM cards (shown only when the
        # package is installed) don't leave gaps.
        row = 0
        for builder in (self._build_name_card, self._build_backup_card,
                        self._build_wifi_card, self._build_static_card):
            builder(row)
            row += 1
        if ruleng.is_selective(self._routing.get("mode", "")):
            self._build_routing_card(row)
            row += 1
        if self._upnp.installed:
            self._build_upnp_card(row)
            row += 1
        if self._sqm.installed:
            self._build_sqm_card(row)
            row += 1
        self._build_lan_card(row)
        row += 1
        self._build_reset_card(row)
        self._build_app_reset_card(row + 1)

    # ----- router name --------------------------------------------------

    def _build_name_card(self, row: int) -> None:
        p = self.p
        c = self._card(row, _("Имя роутера"))
        ctk.CTkLabel(c, text=_("Под этим именем роутер виден в сети и в приложении. Латинские "
                     "буквы, цифры и дефис, без пробелов."), font=fonts.small(),
                     text_color=p.text_muted, wraplength=560, justify="left",
                     anchor="w").grid(row=1, column=0, padx=16, sticky="w")
        rowf = ctk.CTkFrame(c, fg_color="transparent")
        rowf.grid(row=2, column=0, padx=16, pady=(8, 6), sticky="w")
        self._name_var = ctk.StringVar(value=self._hostname)
        ctk.CTkEntry(rowf, textvariable=self._name_var, font=fonts.body(), width=220,
                     fg_color=p.surface_hover).grid(row=0, column=0)
        ctk.CTkButton(rowf, text=_("Переименовать"), font=fonts.body(), fg_color=p.accent,
                      hover_color=p.accent_hover, text_color=p.accent_fg, width=150,
                      command=self._rename).grid(row=0, column=1, padx=10)
        self._name_status = ctk.CTkLabel(c, text="", font=fonts.small(), anchor="w",
                                         wraplength=560, justify="left")
        self._name_status.grid(row=3, column=0, padx=16, pady=(0, 10), sticky="w")

    def _rename(self) -> None:
        name = self._name_var.get().strip()
        if name == self._hostname:
            self._name_status.configure(text=_("Имя не изменилось."), text_color=self.p.text_muted)
            return
        self._name_status.configure(text=_("Переименовываю…"), text_color=self.p.text_muted)
        client = self._client

        def done(applied: str) -> None:
            self._hostname = applied
            self._name_status.configure(text=_("Готово — роутер переименован в «{0}».").format(applied),
                                        text_color=self.p.ok)

        def err(e: BaseException) -> None:
            self._name_status.configure(text=f"{e}", text_color=self.p.fail)

        run_async(self, lambda: ov_engine.set_hostname(client, name), done, err)

    # ----- backup / restore --------------------------------------------

    def _build_backup_card(self, row: int) -> None:
        p = self.p
        c = self._card(row, _("Резервная копия настроек"))
        ctk.CTkLabel(c, text=_("Полная копия настроек роутера (как в LuCI). Сохраните её перед "
                     "любыми изменениями на этой странице."), font=fonts.small(),
                     text_color=p.text_muted, wraplength=560, justify="left",
                     anchor="w").grid(row=1, column=0, padx=16, sticky="w")
        btns = ctk.CTkFrame(c, fg_color="transparent")
        btns.grid(row=2, column=0, padx=16, pady=(8, 10), sticky="w")
        ctk.CTkButton(btns, text=_("Скачать резервную копию"), font=fonts.body(),
                      fg_color=p.accent, hover_color=p.accent_hover, text_color=p.accent_fg,
                      width=220, command=self._download_backup).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(btns, text=_("Восстановить из файла…"), font=fonts.body(),
                      fg_color="transparent", hover_color=p.surface_hover, text_color=p.text,
                      border_width=1, border_color=p.text_muted, width=200,
                      command=self._pick_restore).grid(row=0, column=1, padx=10, sticky="w")
        self._backup_status = ctk.CTkLabel(c, text="", font=fonts.small(), anchor="w",
                                           wraplength=560, justify="left")
        self._backup_status.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="w")
        self._restore_box = ctk.CTkFrame(c, fg_color="transparent", height=1)
        self._restore_box.grid(row=4, column=0, padx=16, pady=(0, 10), sticky="ew")
        self._restore_box.grid_columnconfigure(0, weight=1)

    def _download_backup(self) -> None:
        self._backup_status.configure(text=_("Создаю резервную копию…"), text_color=self.p.text_muted)
        client = self._client

        def done(data: bytes) -> None:
            stamp = datetime.datetime.now().strftime("%Y-%m-%d")
            path = filedialog.asksaveasfilename(
                defaultextension=".tar.gz",
                filetypes=[(_("Архив резервной копии"), "*.tar.gz"), (_("Все файлы"), "*.*")],
                initialfile=f"router-backup-{stamp}.tar.gz")
            if not path:
                self._backup_status.configure(text=_("Отменено."), text_color=self.p.text_muted)
                return
            try:
                with open(path, "wb") as f:
                    f.write(data)
                self._backup_status.configure(text=_("Сохранено: {0} ({1} КБ)").format(path, len(data) // 1024),
                                              text_color=self.p.ok)
            except OSError as exc:
                self._backup_status.configure(text=_("Не удалось сохранить: {0}").format(exc),
                                              text_color=self.p.fail)

        run_async(self, lambda: maintenance.create_backup(client), done,
                  lambda e: self._backup_status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail))

    def _pick_restore(self) -> None:
        path = filedialog.askopenfilename(
            filetypes=[(_("Архив резервной копии"), "*.tar.gz"), (_("Все файлы"), "*.*")])
        if not path:
            return
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError as exc:
            self._backup_status.configure(text=_("Не удалось прочитать файл: {0}").format(exc),
                                          text_color=self.p.fail)
            return
        if data[:2] != b"\x1f\x8b":
            self._backup_status.configure(text=_("Это не похоже на резервную копию (.tar.gz)."),
                                          text_color=self.p.fail)
            return
        self._backup_status.configure(text="")
        for w in self._restore_box.winfo_children():
            w.destroy()
        name = path.replace("\\", "/").rsplit("/", 1)[-1]
        dc = _DangerConfirm(
            self._restore_box, self.p,
            label=_("Восстановить"), confirm_label=_("Подтвердить восстановление"),
            warning=_("Файл: {0}. Настройки роутера будут заменены содержимым копии, после чего роутер перезагрузится. Текущие настройки будут потеряны. Приложение отключится — возможно, потребуется переподключение по другому адресу.").format(name),
            command=lambda dc, d=data: self._do_restore(dc, d))
        dc.grid(row=0, column=0, sticky="ew")

    def _do_restore(self, dc: _DangerConfirm, data: bytes) -> None:
        client = self._client

        def done(_r: Any) -> None:
            dc.set_status(_("Копия восстановлена. Роутер перезагружается — переподключитесь через "
                          "минуту (возможно, по адресу из копии)."), self.p.ok)

        def err(e: BaseException) -> None:
            dc.reset()
            self._backup_status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)

        run_async(self, lambda: maintenance.restore_backup(client, data), done, err)

    # ----- Wi-Fi networks ----------------------------------------------

    # Encryption choices: human label ↔ uci value.
    _ENC_OPTIONS = [
        (N_("Открытая (без пароля)"), "none"),
        ("WPA2", "psk2"),
        ("WPA2 / WPA3", "sae-mixed"),
        ("WPA3", "sae"),
    ]

    def _build_wifi_card(self, row: int) -> None:
        p = self.p
        c = self._card(row, _("Wi-Fi сети"))
        radios = self._wifi
        if not radios:
            ctk.CTkLabel(c, text=_("На этом устройстве не найден Wi-Fi-чип — настраивать нечего."),
                         font=fonts.small(), text_color=p.warn, wraplength=560, justify="left",
                         anchor="w").grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")
            return
        ctk.CTkLabel(c, text=_("Имя сети, пароль, шифрование и канал — отдельно для каждого "
                     "диапазона. Изменения применяются сразу; подключённые устройства "
                     "переподключатся. QR-код и данные на «Обзоре» обновятся при следующем "
                     "открытии."), font=fonts.small(), text_color=p.text_muted, wraplength=560,
                     justify="left", anchor="w").grid(row=1, column=0, padx=16, sticky="w")
        box = ctk.CTkFrame(c, fg_color="transparent")
        box.grid(row=2, column=0, padx=16, pady=(8, 12), sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        self._wifi_widgets: dict[str, dict] = {}
        for i, rw in enumerate(radios):
            self._build_radio_block(box, i, rw)

    def _build_radio_block(self, parent: ctk.CTkBaseClass, i: int, rw) -> None:
        p = self.p
        blk = ctk.CTkFrame(parent, fg_color=p.surface_hover, corner_radius=10)
        blk.grid(row=i, column=0, sticky="ew", pady=(0, 8))
        blk.grid_columnconfigure(0, weight=1)

        # Header: status dot + band + radio + state text.
        head = ctk.CTkFrame(blk, fg_color="transparent")
        head.grid(row=0, column=0, padx=12, pady=(10, 2), sticky="ew")
        up = rw.up and not rw.radio_disabled
        dot_color = p.ok if up else p.fail
        state_txt = _("включено, вещает") if up else (
            _("выключено") if rw.radio_disabled else _("не вещает"))
        ctk.CTkLabel(head, text="●", font=fonts.body(), text_color=dot_color).grid(
            row=0, column=0, padx=(0, 6))
        ctk.CTkLabel(head, text=f"{net_engine.band_label(rw.band)} · {rw.radio}",
                     font=fonts.heading(), text_color=p.text).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(head, text=f"— {state_txt}", font=fonts.small(),
                     text_color=dot_color).grid(row=0, column=2, padx=(6, 0), sticky="w")

        # A radio used as the Wi-Fi uplink (STA) can't also be an AP — show read-only.
        if rw.is_sta:
            ctk.CTkLabel(blk, text=_("Этот диапазон сейчас занят подключением роутера к интернету по "
                         "Wi-Fi, поэтому раздавать сеть на нём нельзя."), font=fonts.small(),
                         text_color=p.text_muted, wraplength=520, justify="left",
                         anchor="w").grid(row=1, column=0, padx=12, pady=(2, 10), sticky="w")
            return

        # No real channel list (iwinfo couldn't report — radio down/unavailable):
        # we have no trustworthy basis to configure this radio, so don't offer
        # editing. Mark it orange instead of guessing a channel list.
        if not rw.channels:
            ctk.CTkLabel(blk, text=_("⚠ Не удалось получить список каналов от этого радио "
                         "(возможно, оно выключено или недоступно). Настройка этого диапазона "
                         "сейчас недоступна — включите радио и обновите страницу."),
                         font=fonts.small(), text_color=p.warn, wraplength=520, justify="left",
                         anchor="w").grid(row=1, column=0, padx=12, pady=(2, 10), sticky="w")
            return

        body = ctk.CTkFrame(blk, fg_color="transparent")
        body.grid(row=1, column=0, padx=12, pady=(2, 10), sticky="ew")
        body.grid_columnconfigure(1, weight=1)

        ssid_var = ctk.StringVar(value=rw.ssid)
        key_var = ctk.StringVar(value=rw.key)
        enc_label = self._enc_label_for(rw.encryption)
        enc_menu_var = ctk.StringVar(value=enc_label)
        # Real per-radio channels polled via iwinfo (like LuCI) — works for every
        # band incl. 6 GHz / Wi-Fi 7. Guaranteed non-empty here (the guard above
        # returned for radios whose list couldn't be read).
        chan_opts = list(rw.channels)
        cur_chan = rw.channel or "auto"
        if cur_chan not in chan_opts:
            chan_opts = chan_opts + [cur_chan]
        chan_var = ctk.StringVar(value=cur_chan)

        r = 0
        ctk.CTkLabel(body, text=_("Имя сети (SSID)"), font=fonts.small(),
                     text_color=p.text).grid(row=r, column=0, sticky="w", pady=(4, 0))
        ctk.CTkEntry(body, textvariable=ssid_var, font=fonts.body(), fg_color=p.surface).grid(
            row=r, column=1, sticky="ew", pady=(4, 0), padx=(10, 0))
        r += 1
        ctk.CTkLabel(body, text=_("Пароль"), font=fonts.small(),
                     text_color=p.text).grid(row=r, column=0, sticky="w", pady=(6, 0))
        pwrow = ctk.CTkFrame(body, fg_color="transparent")
        pwrow.grid(row=r, column=1, sticky="ew", pady=(6, 0), padx=(10, 0))
        pwrow.grid_columnconfigure(0, weight=1)
        key_entry = ctk.CTkEntry(pwrow, textvariable=key_var, font=fonts.body(), show="•",
                                 fg_color=p.surface)
        key_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(pwrow, text="👁", font=fonts.body(), width=40, fg_color=p.surface,
                      hover_color=p.border,
                      command=lambda e=key_entry: e.configure(
                          show="" if e.cget("show") else "•")).grid(row=0, column=1, padx=(6, 0))
        r += 1
        ctk.CTkLabel(body, text=_("Шифрование"), font=fonts.small(),
                     text_color=p.text).grid(row=r, column=0, sticky="w", pady=(6, 0))
        ctk.CTkOptionMenu(body, variable=enc_menu_var,
                          values=[_(lbl) for lbl, _v in self._ENC_OPTIONS], font=fonts.small(),
                          fg_color=p.surface, button_color=p.accent,
                          button_hover_color=p.accent_hover).grid(
            row=r, column=1, sticky="w", pady=(6, 0), padx=(10, 0))
        r += 1
        ctk.CTkLabel(body, text=_("Канал"), font=fonts.small(),
                     text_color=p.text).grid(row=r, column=0, sticky="w", pady=(6, 0))
        ctk.CTkOptionMenu(body, variable=chan_var, values=chan_opts, font=fonts.small(),
                          width=110, fg_color=p.surface, button_color=p.accent,
                          button_hover_color=p.accent_hover).grid(
            row=r, column=1, sticky="w", pady=(6, 0), padx=(10, 0))
        r += 1
        # Channel width — real options polled per radio (like LuCI). Only shown when
        # the radio actually reports widths; each label maps to the best uci htmode.
        width_var = None
        width_map = {lbl: hm for lbl, hm in rw.widths}
        if rw.widths:
            width_opts = [lbl for lbl, _ in rw.widths]
            digits = "".join(ch for ch in rw.htmode if ch.isdigit())
            cur_w = _("{0} МГц").format(digits) if digits and _("{0} МГц").format(digits) in width_map else width_opts[-1]
            width_var = ctk.StringVar(value=cur_w)
            ctk.CTkLabel(body, text=_("Ширина канала"), font=fonts.small(),
                         text_color=p.text).grid(row=r, column=0, sticky="w", pady=(6, 0))
            ctk.CTkOptionMenu(body, variable=width_var, values=width_opts, font=fonts.small(),
                              width=110, fg_color=p.surface, button_color=p.accent,
                              button_hover_color=p.accent_hover).grid(
                row=r, column=1, sticky="w", pady=(6, 0), padx=(10, 0))
            r += 1
        apply_row = ctk.CTkFrame(body, fg_color="transparent")
        apply_row.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        apply_btn = ctk.CTkButton(apply_row, text=_("Применить"), font=fonts.body(),
                                  fg_color=p.accent, hover_color=p.accent_hover,
                                  text_color=p.accent_fg, width=140,
                                  command=lambda rn=rw.radio: self._apply_radio(rn))
        apply_btn.grid(row=0, column=0, sticky="w")
        status = ctk.CTkLabel(apply_row, text="", font=fonts.small(), anchor="w",
                              wraplength=380, justify="left")
        status.grid(row=0, column=1, padx=(10, 0), sticky="w")

        self._wifi_widgets[rw.radio] = {
            "band": rw.band, "ssid": ssid_var, "key": key_var, "enc": enc_menu_var,
            "chan": chan_var, "width": width_var, "width_map": width_map,
            "btn": apply_btn, "status": status, "dot": None,
        }

    def _enc_label_for(self, enc: str) -> str:
        norm = net_engine.normalize_encryption(enc)
        for lbl, val in self._ENC_OPTIONS:
            if val == norm:
                return _(lbl)
        return _(self._ENC_OPTIONS[1][0])  # WPA2 fallback

    def _apply_radio(self, radio: str) -> None:
        w = self._wifi_widgets.get(radio)
        if w is None:
            return
        ssid = w["ssid"].get().strip()
        key = w["key"].get()
        enc = {_(lbl): val for lbl, val in self._ENC_OPTIONS}.get(w["enc"].get(), "psk2")
        channel = w["chan"].get()
        htmode = w["width_map"].get(w["width"].get(), "") if w.get("width") else ""
        if not ssid:
            w["status"].configure(text=_("Введите имя сети."), text_color=self.p.fail)
            return
        if enc != "none" and len(key) < 8:
            w["status"].configure(text=_("Пароль не короче 8 символов."), text_color=self.p.fail)
            return
        w["btn"].configure(state="disabled", text=_("Применяю…"))
        w["status"].configure(text=_("Настраиваю Wi-Fi…"), text_color=self.p.text_muted)
        client = self._client

        def done(came_up: bool) -> None:
            w["btn"].configure(state="normal", text=_("Применить"))
            if came_up:
                w["status"].configure(text=_("Готово — сеть обновлена."), text_color=self.p.ok)
            else:
                w["status"].configure(
                    text=_("Применено, но диапазон не поднялся — возможно, канал не разрешён "
                    "в этом регионе. Попробуйте другой канал."), text_color=self.p.warn)

        def err(e: BaseException) -> None:
            w["btn"].configure(state="normal", text=_("Применить"))
            w["status"].configure(text=f"{e}", text_color=self.p.fail)

        run_async(self, lambda: net_engine.set_radio_wifi(
            client, radio, ssid=ssid, key=key, encryption=enc, channel=channel,
            htmode=htmode), done, err)

    # ----- LAN / DHCP ---------------------------------------------------

    def _build_lan_card(self, row: int) -> None:
        p = self.p
        s = self._lan
        c = self._card(row, _("Сеть LAN и DHCP"))
        # OpenWrt SNAPSHOT: network config format is unstable — don't touch it.
        if self._net_mode == lan_engine.NET_SNAPSHOT:
            ctk.CTkLabel(
                c, text=_("На сборке OpenWrt SNAPSHOT формат сетевых настроек может отличаться, "
                "поэтому менять адрес роутера и DHCP отсюда небезопасно. Настройте сеть "
                "самостоятельно — через веб-интерфейс роутера (браузер) или консоль."),
                font=fonts.small(), text_color=p.warn, wraplength=560, justify="left",
                anchor="w").grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")
            return
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.grid(row=1, column=0, padx=16, pady=(4, 8), sticky="ew")
        grid.grid_columnconfigure(0, weight=1)
        self._lan_vars: dict[str, ctk.StringVar] = {}
        self._lan_row = 0
        # digits-only filter for the lease-time fields (idiot-proofing).
        digits3 = (self.register(lambda P: P == "" or (P.isdigit() and len(P) <= 3)), "%P")
        digits2 = (self.register(lambda P: P == "" or (P.isdigit() and len(P) <= 2)), "%P")

        # Address fields differ by OpenWrt version: one CIDR field (>= 25.12) vs a
        # separate IP + netmask pair (<= 24.10).
        if self._net_mode == lan_engine.NET_CIDR:
            var = ctk.StringVar(value=lan_engine.cidr_of(s.ipaddr, s.netmask))
            self._lan_vars["cidr"] = var
            self._lan_field(
                grid, _("IP-адрес роутера с маской (CIDR)"),
                _("Адрес роутера вместе с размером подсети через «/», например 192.168.1.1/24. "
                "По этому адресу открываются настройки; его же вы вводите в приложении."),
                entry_var=var)
        else:
            ip_var = ctk.StringVar(value=s.ipaddr)
            self._lan_vars["ipaddr"] = ip_var
            self._lan_field(
                grid, _("IP-адрес роутера"),
                _("Адрес, по которому открываются настройки роутера; его же вы вводите в "
                "приложении. Обычно 192.168.1.1."), entry_var=ip_var)
            mask_var = ctk.StringVar(value=s.netmask)
            self._lan_vars["netmask"] = mask_var
            self._lan_field(
                grid, _("Маска подсети"),
                _("Размер локальной сети. Если не уверены — оставьте 255.255.255.0."),
                entry_var=mask_var)

        for key, label, val, hint in (
            ("dhcp_start", _("DHCP: начало диапазона"), str(s.dhcp_start),
             _("С какого адреса роутер начинает раздавать IP. 100 означает 192.168.1.100. Адреса "
             "до него (1–99) остаются свободными — их удобно отдавать под постоянные IP устройств.")),
            ("dhcp_limit", _("DHCP: сколько адресов раздавать"), str(s.dhcp_limit),
             _("Максимум устройств, которым роутер выдаст адрес автоматически (размер диапазона).")),
        ):
            var = ctk.StringVar(value=val)
            self._lan_vars[key] = var
            self._lan_field(grid, label, hint, entry_var=var)

        # lease time as a ЧЧ:ММ form (two numeric boxes)
        hh, mm = lan_engine.leasetime_to_hm(s.leasetime)
        self._lease_h = ctk.StringVar(value=f"{hh:02d}")
        self._lease_m = ctk.StringVar(value=f"{mm:02d}")
        ctk.CTkLabel(grid, text=_("Время аренды адреса (ЧЧ:ММ)"), font=fonts.small(),
                     text_color=p.text, anchor="w").grid(
            row=self._lan_row, column=0, sticky="w", pady=(6, 0))
        self._lan_row += 1
        hmrow = ctk.CTkFrame(grid, fg_color="transparent")
        hmrow.grid(row=self._lan_row, column=0, sticky="w", pady=(2, 0))
        self._lan_row += 1
        ctk.CTkEntry(hmrow, textvariable=self._lease_h, font=fonts.body(), width=56, justify="center",
                     fg_color=p.surface_hover, validate="key", validatecommand=digits3).grid(row=0, column=0)
        ctk.CTkLabel(hmrow, text=":", font=fonts.heading(), text_color=p.text).grid(row=0, column=1, padx=6)
        ctk.CTkEntry(hmrow, textvariable=self._lease_m, font=fonts.body(), width=56, justify="center",
                     fg_color=p.surface_hover, validate="key", validatecommand=digits2).grid(row=0, column=2)
        ctk.CTkLabel(grid, text=_("Через какое время устройство заново запрашивает свой адрес. "
                     "Например 12:00 — каждые 12 часов. Слишком малое значение нагружает сеть."),
                     font=fonts.small(), text_color=p.text_muted, anchor="w", wraplength=540,
                     justify="left").grid(row=self._lan_row, column=0, sticky="w", pady=(1, 2))
        self._lan_row += 1

        apply_box = ctk.CTkFrame(c, fg_color="transparent")
        apply_box.grid(row=2, column=0, padx=16, pady=(2, 12), sticky="ew")
        apply_box.grid_columnconfigure(0, weight=1)
        self._lan_confirm = _DangerConfirm(
            apply_box, p, label=_("Применить изменения"), confirm_label=_("Подтвердить"),
            warning=_("Изменение адреса роутера, маски или DHCP отключит ВСЕ устройства, включая "
                    "это. Может потребоваться полный сброс роутера. Делайте только при крайней "
                    "необходимости — приложение отключится и переподключится по новому адресу."),
            command=self._do_lan_apply, read_values=self._validate_lan)
        self._lan_confirm.grid(row=0, column=0, sticky="ew")

    def _lan_field(self, grid: ctk.CTkBaseClass, label: str, hint: str, *,
                   entry_var: ctk.StringVar) -> None:
        """One labelled LAN entry with a muted explanatory hint underneath."""
        p = self.p
        ctk.CTkLabel(grid, text=label, font=fonts.small(), text_color=p.text, anchor="w").grid(
            row=self._lan_row, column=0, sticky="w", pady=(6, 0))
        self._lan_row += 1
        ctk.CTkEntry(grid, textvariable=entry_var, font=fonts.body(), width=200,
                     fg_color=p.surface_hover).grid(row=self._lan_row, column=0, sticky="w", pady=(2, 0))
        self._lan_row += 1
        ctk.CTkLabel(grid, text=hint, font=fonts.small(), text_color=p.text_muted, anchor="w",
                     wraplength=540, justify="left").grid(row=self._lan_row, column=0, sticky="w", pady=(1, 2))
        self._lan_row += 1

    def _lease_string(self) -> str:
        return lan_engine.hm_to_leasetime(int(self._lease_h.get() or 0), int(self._lease_m.get() or 0))

    def _lan_ip_mask(self) -> "tuple[str, str] | None":
        """Resolve (ip, netmask) from the address field(s) for the current mode;
        None if the CIDR field is malformed."""
        if self._net_mode == lan_engine.NET_CIDR:
            return lan_engine.parse_cidr(self._lan_vars["cidr"].get())
        return self._lan_vars["ipaddr"].get(), self._lan_vars["netmask"].get()

    def _validate_lan(self) -> "str | None":
        err = lan_engine.validate_hm(self._lease_h.get(), self._lease_m.get())
        if err:
            return err
        pair = self._lan_ip_mask()
        if pair is None:
            return _("Неверный адрес. Укажите IP с маской через «/», например 192.168.1.1/24.")
        ip, mask = pair
        v = self._lan_vars
        return lan_engine.validate_lan_settings(
            ip, mask, v["dhcp_start"].get(), v["dhcp_limit"].get(), self._lease_string())

    def _do_lan_apply(self, dc: _DangerConfirm) -> None:
        pair = self._lan_ip_mask()
        if pair is None:  # guarded by _validate_lan, but stay safe
            dc.reset()
            self._lan_confirm.set_status(_("Неверный адрес."), self.p.fail)
            return
        ip, mask = pair
        v = self._lan_vars
        new = lan_engine.LanSettings(
            ipaddr=ip.strip(), netmask=mask.strip(),
            dhcp_start=int(v["dhcp_start"].get()), dhcp_limit=int(v["dhcp_limit"].get()),
            leasetime=self._lease_string(), dhcp_enabled=self._lan.dhcp_enabled)
        cidr_mode = self._net_mode == lan_engine.NET_CIDR
        client = self._client

        def done(_r: Any) -> None:
            dc.set_status(_("Применяется. Роутер переедет на {0} — приложение отключится, переподключитесь по новому адресу.").format(new.ipaddr), self.p.ok)

        def err(e: BaseException) -> None:
            dc.reset()
            self._lan_confirm.set_status(_("Ошибка: {0}").format(e), self.p.fail)

        run_async(self, lambda: lan_engine.apply_lan_settings(client, new, cidr_mode=cidr_mode),
                  done, err)

    # ----- static lease -------------------------------------------------

    def _build_static_card(self, row: int) -> None:
        p = self.p
        c = self._card(row, _("Постоянный IP-адрес для устройства"))
        ctk.CTkLabel(c, text=_("Закрепите за устройством его текущий адрес — роутер всегда будет "
                     "выдавать ему один и тот же IP."), font=fonts.small(), text_color=p.text_muted,
                     wraplength=560, justify="left", anchor="w").grid(row=1, column=0, padx=16, sticky="w")
        pinned = {l.mac.strip().lower() for l in self._leases}
        free = [d for d in self._devices if d.mac and d.mac.strip().lower() not in pinned]
        pick = ctk.CTkFrame(c, fg_color="transparent")
        pick.grid(row=2, column=0, padx=16, pady=(8, 6), sticky="w")
        self._static_status = ctk.CTkLabel(c, text="", font=fonts.small(), anchor="w",
                                           wraplength=560, justify="left")
        self._static_status.grid(row=3, column=0, padx=16, sticky="w")
        if free:
            self._dev_labels = {f"{d.hostname} · {d.ip}": d for d in free}
            self._dev_menu = ctk.CTkOptionMenu(pick, values=list(self._dev_labels), font=fonts.small(),
                                               width=240, fg_color=p.surface_hover, button_color=p.accent,
                                               button_hover_color=p.accent_hover)
            self._dev_menu.grid(row=0, column=0, sticky="w")
            ctk.CTkButton(pick, text=_("Закрепить адрес"), font=fonts.body(), fg_color=p.accent,
                          hover_color=p.accent_hover, text_color=p.accent_fg, width=160,
                          command=self._pin_device).grid(row=0, column=1, padx=10, sticky="w")
        else:
            ctk.CTkLabel(pick, text=_("Все известные устройства уже закреплены или нет устройств с MAC."),
                         font=fonts.small(), text_color=p.text_muted).grid(row=0, column=0, sticky="w")
        # existing reservations
        if self._leases:
            box = ctk.CTkFrame(c, fg_color="transparent")
            box.grid(row=4, column=0, padx=16, pady=(6, 12), sticky="ew")
            box.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(box, text=_("Закреплённые:"), font=fonts.small(), text_color=p.text_muted,
                         anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 2))
            for i, l in enumerate(self._leases, start=1):
                line = ctk.CTkFrame(box, fg_color="transparent")
                line.grid(row=i, column=0, sticky="ew", pady=1)
                line.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(line, text=f"{l.name or l.mac} → {l.ip}", font=fonts.small(),
                             text_color=p.text, anchor="w").grid(row=0, column=0, sticky="w")
                ctk.CTkButton(line, text=_("Убрать"), font=fonts.small(), width=70, height=24,
                              fg_color="transparent", hover_color=p.surface_hover,
                              text_color=p.text_muted, border_width=1, border_color=p.text_muted,
                              command=lambda mac=l.mac: self._unpin_device(mac)).grid(row=0, column=1)
        else:
            ctk.CTkLabel(c, text="", height=2).grid(row=4, column=0, pady=(0, 8))

    def _pin_device(self) -> None:
        dev = self._dev_labels.get(self._dev_menu.get())
        if dev is None:
            return
        self._static_status.configure(text=_("Закрепляю адрес…"), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: lan_engine.add_static_lease(
            client, name=dev.hostname, mac=dev.mac, ip=dev.ip),
            lambda _r: self.refresh(),
            lambda e: self._static_status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail))

    def _unpin_device(self, mac: str) -> None:
        client = self._client
        run_async(self, lambda: lan_engine.remove_static_lease(client, mac),
                  lambda _r: self.refresh(),
                  lambda e: self._static_status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail))

    # ----- UPnP ---------------------------------------------------------

    def _build_upnp_card(self, row: int) -> None:
        p = self.p
        st = self._upnp
        c = self._card(row, _("UPnP / переадресация портов"))
        ctk.CTkLabel(c, text=_("Позволяет программам и играм самим открывать нужные порты на "
                     "роутере (онлайн-игры, торренты, видеозвонки). Удобно, но снижает контроль "
                     "над тем, какие порты открыты."), font=fonts.small(), text_color=p.text_muted,
                     wraplength=560, justify="left", anchor="w").grid(
            row=1, column=0, padx=16, sticky="w")
        # status dot
        head = ctk.CTkFrame(c, fg_color="transparent")
        head.grid(row=2, column=0, padx=16, pady=(8, 2), sticky="w")
        running = st.enabled and st.running
        ctk.CTkLabel(head, text="●", font=fonts.body(),
                     text_color=p.ok if running else p.fail).grid(row=0, column=0, padx=(0, 6))
        ctk.CTkLabel(head, text=(_("Служба включена и работает") if running else
                                 (_("Включена, но не запущена") if st.enabled else _("Отключена"))),
                     font=fonts.small(),
                     text_color=p.ok if running else p.text_muted).grid(row=0, column=1, sticky="w")
        self._upnp_var = ctk.StringVar(value="1" if st.enabled else "0")
        ctk.CTkSwitch(c, text=_("Включить UPnP"), font=fonts.body(), variable=self._upnp_var,
                      onvalue="1", offvalue="0", progress_color=p.accent,
                      command=self._toggle_upnp).grid(row=3, column=0, padx=16, pady=(4, 4),
                                                      sticky="w")
        self._upnp_status = ctk.CTkLabel(c, text="", font=fonts.small(), anchor="w",
                                         wraplength=560, justify="left")
        self._upnp_status.grid(row=4, column=0, padx=16, sticky="w")
        # active redirects
        box = ctk.CTkFrame(c, fg_color="transparent")
        box.grid(row=5, column=0, padx=16, pady=(6, 12), sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(box, text=_("Активные переадресации:"), font=fonts.small(),
                     text_color=p.text_muted, anchor="w").grid(row=0, column=0, sticky="w")
        if st.redirects:
            for i, r in enumerate(st.redirects, start=1):
                txt = f"•  {r.proto} :{r.ext_port} → {r.int_ip}:{r.int_port}"
                if r.desc:
                    txt += f"  ({r.desc})"
                ctk.CTkLabel(box, text=txt, font=fonts.small(), text_color=p.text, anchor="w").grid(
                    row=i, column=0, sticky="w", pady=1)
        else:
            ctk.CTkLabel(box, text=_("нет активных переадресаций"), font=fonts.small(),
                         text_color=p.text_muted, anchor="w").grid(row=1, column=0, sticky="w")

    def _toggle_upnp(self) -> None:
        on = self._upnp_var.get() == "1"
        self._upnp_status.configure(text=_("Применяю…"), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: upnp_engine.set_enabled(client, on),
                  lambda _r: self.refresh(),
                  lambda e: self._upnp_status.configure(text=_("Ошибка: {0}").format(e),
                                                        text_color=self.p.fail))

    # ----- SQM ----------------------------------------------------------

    def _build_sqm_card(self, row: int) -> None:
        p = self.p
        s = self._sqm
        c = self._card(row, _("SQM — сглаживание буфера (bufferbloat)"))
        ctk.CTkLabel(c, text=_("Убирает «залипания» интернета, когда кто-то качает или грузит "
                     "канал (видеозвонки, игры перестают тормозить). Ограничивает скорость чуть "
                     "ниже реальной, чтобы роутер управлял очередью пакетов. Требователен к "
                     "производительности роутера: на тарифах с высокой скоростью (500+ Мбит/с) "
                     "может занижать скорость из-за нехватки мощности."), font=fonts.small(),
                     text_color=p.text_muted, wraplength=560, justify="left", anchor="w").grid(
            row=1, column=0, padx=16, sticky="w")
        grid = ctk.CTkFrame(c, fg_color="transparent")
        grid.grid(row=2, column=0, padx=16, pady=(6, 4), sticky="ew")
        grid.grid_columnconfigure(0, weight=1)
        self._sqm_row = 0
        digits = (self.register(lambda P: P == "" or (P.isdigit() and len(P) <= 9)), "%P")
        digits3 = (self.register(lambda P: P == "" or (P.isdigit() and len(P) <= 3)), "%P")

        # WAN interface — default to the detected/resolved device (s.interface),
        # ensuring it's selectable even if it's not a plain physical netdev
        # (e.g. pppoe-wan). Never hardcode eth1.
        ifaces = list(self._sqm_ifaces)
        if s.interface and s.interface not in ifaces:
            ifaces.insert(0, s.interface)
        if not ifaces:
            ifaces = [s.interface or "eth1"]
        cur_if = s.interface if s.interface in ifaces else ifaces[0]
        self._sqm_if = ctk.StringVar(value=cur_if)
        self._sqm_field(grid, _("WAN-интерфейс (что ограничиваем)"),
                        _("Устройство, через которое роутер выходит в интернет. Обычно определяется "
                        "автоматически."), widget=ctk.CTkOptionMenu(
                            grid, variable=self._sqm_if, values=ifaces, font=fonts.small(),
                            width=160, fg_color=p.surface_hover, button_color=p.accent,
                            button_hover_color=p.accent_hover))

        self._sqm_down = ctk.StringVar(value=str(s.download or ""))
        self._sqm_field(grid, _("Скорость приёма, кбит/с"),
                        _("Поставьте ~90–95% от тарифной скорости загрузки, либо на 1–2 Мбит/с меньше "
                        "реально измеренной. Например, при тарифе 100 Мбит/с — около 90000–95000."),
                        widget=ctk.CTkEntry(
                            grid, textvariable=self._sqm_down, font=fonts.body(), width=160,
                            fg_color=p.surface_hover, validate="key", validatecommand=digits))
        self._sqm_up = ctk.StringVar(value=str(s.upload or ""))
        self._sqm_field(grid, _("Скорость отдачи, кбит/с"),
                        _("Так же: ~90–95% от тарифной скорости отдачи (upload) или на 1–2 Мбит/с "
                        "меньше измеренной."), widget=ctk.CTkEntry(
                            grid, textvariable=self._sqm_up, font=fonts.body(), width=160,
                            fg_color=p.surface_hover, validate="key", validatecommand=digits))

        self._sqm_qdisc = ctk.StringVar(value=s.qdisc if s.qdisc in sqm_engine.QDISCS else "cake")
        self._sqm_field(grid, _("Дисциплина очереди"),
                        _("cake — современная, рекомендуется (сама управляет приоритетами). "
                        "fq_codel — проще и легче, для слабых роутеров."), widget=ctk.CTkOptionMenu(
                            grid, variable=self._sqm_qdisc, values=sqm_engine.QDISCS,
                            font=fonts.small(), width=160, fg_color=p.surface_hover,
                            button_color=p.accent, button_hover_color=p.accent_hover))

        self._sqm_script_map = {lbl: val for val, lbl in sqm_engine.SCRIPTS}
        cur_script_lbl = next((lbl for val, lbl in sqm_engine.SCRIPTS if val == s.script),
                              sqm_engine.SCRIPTS[0][1])
        self._sqm_script = ctk.StringVar(value=cur_script_lbl)
        self._sqm_field(grid, _("Шаблон настройки очереди"),
                        _("Простой подходит почти всем. «С приоритизацией» отдаёт приоритет звонкам "
                        "и играм перед загрузками, но чуть тяжелее."), widget=ctk.CTkOptionMenu(
                            grid, variable=self._sqm_script,
                            values=[lbl for _v, lbl in sqm_engine.SCRIPTS], font=fonts.small(),
                            width=280, fg_color=p.surface_hover, button_color=p.accent,
                            button_hover_color=p.accent_hover))

        self._sqm_overhead = ctk.StringVar(value=str(s.overhead))
        self._sqm_field(grid, _("Накладные расходы на пакет, байт"),
                        _("Запас на служебные данные канала. 44 подходит для большинства подключений "
                        "(Ethernet/оптика/кабель). Для DSL может быть иначе — если не уверены, "
                        "оставьте 44."), widget=ctk.CTkEntry(
                            grid, textvariable=self._sqm_overhead, font=fonts.body(), width=80,
                            fg_color=p.surface_hover, validate="key", validatecommand=digits3))

        self._sqm_enabled = ctk.StringVar(value="1" if s.enabled else "0")
        ctk.CTkSwitch(c, text=_("Включить SQM"), font=fonts.body(), variable=self._sqm_enabled,
                      onvalue="1", offvalue="0", progress_color=p.accent).grid(
            row=3, column=0, padx=16, pady=(4, 4), sticky="w")
        applyrow = ctk.CTkFrame(c, fg_color="transparent")
        applyrow.grid(row=4, column=0, padx=16, pady=(2, 12), sticky="w")
        self._sqm_measure_btn = ctk.CTkButton(
            applyrow, text=_("Измерить"), font=fonts.body(), fg_color=p.surface_hover,
            hover_color=p.border, text_color=p.text, border_width=1, border_color=p.text_muted,
            width=120, command=self._measure_sqm)
        self._sqm_measure_btn.grid(row=0, column=0, sticky="w")
        self._sqm_btn = ctk.CTkButton(applyrow, text=_("Применить"), font=fonts.body(),
                                      fg_color=p.accent, hover_color=p.accent_hover,
                                      text_color=p.accent_fg, width=140, command=self._apply_sqm)
        self._sqm_btn.grid(row=0, column=1, padx=(10, 0), sticky="w")
        self._sqm_status = ctk.CTkLabel(c, text="", font=fonts.small(), anchor="w",
                                        wraplength=540, justify="left")
        self._sqm_status.grid(row=5, column=0, padx=16, pady=(0, 12), sticky="w")

    def _sqm_field(self, grid: ctk.CTkBaseClass, label: str, hint: str, *,
                   widget: ctk.CTkBaseClass) -> None:
        p = self.p
        ctk.CTkLabel(grid, text=label, font=fonts.small(), text_color=p.text, anchor="w").grid(
            row=self._sqm_row, column=0, sticky="w", pady=(6, 0))
        self._sqm_row += 1
        widget.grid(row=self._sqm_row, column=0, sticky="w", pady=(2, 0))
        self._sqm_row += 1
        ctk.CTkLabel(grid, text=hint, font=fonts.small(), text_color=p.text_muted, anchor="w",
                     wraplength=540, justify="left").grid(row=self._sqm_row, column=0, sticky="w",
                                                          pady=(1, 2))
        self._sqm_row += 1

    def _measure_sqm(self) -> None:
        self._sqm_measure_btn.configure(state="disabled", text=_("Измеряю…"))
        self._sqm_status.configure(
            text=_("Измеряю скорость загрузки (несколько секунд, скачается часть тестового "
            "файла)…"), text_color=self.p.text_muted)
        client = self._client

        def done(res: tuple) -> None:
            down, up = res
            self._sqm_measure_btn.configure(state="normal", text=_("Измерить"))
            self._sqm_down.set(str(down))
            self._sqm_up.set(str(up))
            self._sqm_status.configure(
                text=_("Измерено: приём ≈ {0} кбит/с (−2% к замеру). Отдачу прикинул как {1} кбит/с (половина приёма) — уточните под свой тариф и нажмите «Применить».").format(down, up),
                text_color=self.p.ok)

        def err(e: BaseException) -> None:
            self._sqm_measure_btn.configure(state="normal", text=_("Измерить"))
            self._sqm_status.configure(text=f"{e}", text_color=self.p.fail)

        run_async(self, lambda: sqm_engine.measure_speeds(client), done, err)

    def _apply_sqm(self) -> None:
        s = self._sqm
        new = sqm_engine.SqmSettings(
            installed=True, exists=s.exists,
            enabled=self._sqm_enabled.get() == "1",
            interface=self._sqm_if.get(),
            download=int(self._sqm_down.get() or 0),
            upload=int(self._sqm_up.get() or 0),
            qdisc=self._sqm_qdisc.get(),
            script=self._sqm_script_map.get(self._sqm_script.get(), "piece_of_cake.qos"),
            # Force ethernet link layer so the per-packet overhead actually applies
            # ('none' — the stock value — makes SQM ignore overhead entirely).
            linklayer="ethernet",
            overhead=int(self._sqm_overhead.get() or 44))
        self._sqm_btn.configure(state="disabled", text=_("Применяю…"))
        self._sqm_status.configure(text=_("Настраиваю очередь…"), text_color=self.p.text_muted)
        client = self._client

        def done(_r: object) -> None:
            self._sqm_btn.configure(state="normal", text=_("Применить"))
            self._sqm_status.configure(text=_("Готово — настройки SQM применены."),
                                       text_color=self.p.ok)

        def err(e: BaseException) -> None:
            self._sqm_btn.configure(state="normal", text=_("Применить"))
            self._sqm_status.configure(text=f"{e}", text_color=self.p.fail)

        run_async(self, lambda: sqm_engine.apply_settings(client, new), done, err)

    # ----- proxy routing (region DNS + dedicated UDP node) --------------

    def _build_routing_card(self, row: int) -> None:
        p = self.p
        mode = self._routing["mode"]
        c = self._card(row, _("Маршрутизация прокси"))

        # Domestic DNS resolver (region presets): resolves the region's own sites
        # directly, without the proxy. Backend defaults it, so this is fine-tuning.
        dns_key, _default, presets = ruleng.DNS_PRESETS[mode]
        cur_dns = self._routing.get("dns_val", "")
        label_by_val = {v: lbl for v, lbl in presets}
        val_by_label = {lbl: v for v, lbl in presets}
        options = [lbl for _v, lbl in presets]
        cur_label = label_by_val.get(cur_dns, cur_dns)
        if cur_label and cur_label not in options:
            options.append(cur_label)  # keep a custom value visible
        dns_title = {
            "proxy_banned_ru": _("DNS для российских сайтов (напрямую)"),
            "bypass_cn": _("DNS для китайских сайтов (напрямую)"),
            "bypass_ir": _("DNS для иранских сайтов (напрямую)"),
        }.get(mode, _("Региональный DNS"))
        ctk.CTkLabel(c, text=dns_title, font=fonts.body(), text_color=p.text_muted).grid(
            row=1, column=0, padx=16, pady=(8, 2), sticky="w")
        self._dns_menu = ctk.CTkOptionMenu(
            c, values=options, font=fonts.body(), fg_color=p.surface_hover,
            button_color=p.accent, button_hover_color=p.accent_hover,
            command=lambda lbl: self._apply_routing(dns_key, val_by_label.get(lbl, lbl)))
        self._dns_menu.set(cur_label or options[0])
        self._dns_menu.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="w")

        # Dedicated UDP node (voice/games) — reverse modes only. 'same' = no
        # dedicated node (UDP rides the main outbound).
        if mode in ("bypass_cn", "bypass_ir"):
            nodes = self._routing.get("nodes") or []
            udp_opts = [("same", _("Как основной узел")), ("urltest", _("Отдельный URLTest"))]
            udp_opts += [(n.section, f"{n.label or n.section} ({n.type})") for n in nodes]
            udp_val_by_label = {lbl: v for v, lbl in udp_opts}
            udp_label_by_val = {v: lbl for v, lbl in udp_opts}
            cur_udp = self._routing.get("udp", "same")
            cur_udp_label = udp_label_by_val.get(cur_udp, cur_udp)
            ctk.CTkLabel(c, text=_("Отдельный сервер для UDP (звонки, игры)"),
                         font=fonts.body(), text_color=p.text_muted).grid(
                row=3, column=0, padx=16, pady=(8, 2), sticky="w")
            ctk.CTkLabel(c, text=_("По умолчанию UDP идёт через основной узел. Можно выделить "
                         "отдельный сервер — иногда стабильнее для голоса и игр."),
                         font=fonts.small(), text_color=p.text_muted, wraplength=540,
                         justify="left").grid(row=4, column=0, padx=16, pady=(0, 4), sticky="w")
            udp_options = [lbl for _v, lbl in udp_opts]
            if cur_udp_label not in udp_options:
                udp_options.append(cur_udp_label)
            self._udp_menu = ctk.CTkOptionMenu(
                c, values=udp_options, font=fonts.body(), fg_color=p.surface_hover,
                button_color=p.accent, button_hover_color=p.accent_hover,
                command=lambda lbl: self._apply_routing("main_udp_node", udp_val_by_label.get(lbl, lbl)))
            self._udp_menu.set(cur_udp_label or udp_options[0])
            self._udp_menu.grid(row=5, column=0, padx=16, pady=(0, 8), sticky="w")

        self._routing_status = ctk.CTkLabel(c, text="", font=fonts.small(), anchor="w",
                                            wraplength=560, justify="left")
        self._routing_status.grid(row=6, column=0, padx=16, pady=(0, 10), sticky="w")

    def _apply_routing(self, key: str, value: str) -> None:
        self._routing_status.configure(text=_("Применяю…"), text_color=self.p.text_muted)
        client = self._client

        def task() -> None:
            client.uci_set(f"homeproxy.config.{key}", value)
            client.uci_commit("homeproxy")
            client.ubus_homeproxy("diag_service_restart", timeout=40)

        run_async(self, task,
                  lambda _r: self._routing_status.configure(
                      text=_("Готово — настройки применены."), text_color=self.p.ok),
                  lambda e: self._routing_status.configure(
                      text=_("Ошибка: {0}").format(e), text_color=self.p.fail))

    # ----- factory reset ------------------------------------------------

    def _build_reset_card(self, row: int) -> None:
        p = self.p
        c = self._card(row, _("Сброс к заводским настройкам"))
        ctk.CTkLabel(c, text=_("Полностью стирает все настройки роутера и возвращает его к "
                     "состоянию «из коробки» (обычно адрес 192.168.1.1, без пароля). "
                     "HomeProxy, ключи, Wi-Fi — всё будет удалено."), font=fonts.small(),
                     text_color=p.text_muted, wraplength=560, justify="left",
                     anchor="w").grid(row=1, column=0, padx=16, sticky="w")
        box = ctk.CTkFrame(c, fg_color="transparent")
        box.grid(row=2, column=0, padx=16, pady=(8, 12), sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        _DangerConfirm(
            box, p, label=_("Сбросить устройство"), confirm_label=_("Подтвердить сброс"),
            warning=_("Все настройки будут безвозвратно удалены, роутер перезагрузится в заводском "
                    "состоянии. Приложение потеряет связь. Убедитесь, что у вас есть резервная "
                    "копия."), command=self._do_reset).grid(row=0, column=0, sticky="ew")

    def _do_reset(self, dc: _DangerConfirm) -> None:
        client = self._client

        def done(_r: Any) -> None:
            dc.set_status(_("Сброс запущен. Роутер перезагрузится в заводском состоянии — "
                          "подключитесь заново как к новому устройству."), self.p.ok)
            # The session is dead (router wiped). Drop back to the connection page so
            # the user isn't left on settings for a device that's no longer there.
            if self._on_router_reset is not None:
                self.after(3000, self._on_router_reset)

        def err(e: BaseException) -> None:
            dc.reset()
            dc.set_status(_("Ошибка: {0}").format(e), self.p.fail)

        run_async(self, lambda: maintenance.factory_reset(client), done, err)

    # ----- app data reset (local, NOT the router) ----------------------

    def _build_app_reset_card(self, row: int) -> None:
        p = self.p
        c = self._card(row, _("Удалить данные приложения (не роутера)"))
        ctk.CTkLabel(c, text=_("Стирает с ЭТОГО компьютера все данные Re:Sputnik: SSH-ключ "
                     "приложения, сохранённые пароли роутеров, привязки host-key и список "
                     "роутеров. Сам роутер и его настройки не трогаются. Используйте, чтобы "
                     "убрать за собой на чужом или общем компьютере."), font=fonts.small(),
                     text_color=p.text_muted, wraplength=560, justify="left",
                     anchor="w").grid(row=1, column=0, padx=16, sticky="w")
        box = ctk.CTkFrame(c, fg_color="transparent")
        box.grid(row=2, column=0, padx=16, pady=(8, 12), sticky="ew")
        box.grid_columnconfigure(0, weight=1)
        _DangerConfirm(
            box, p, label=_("Удалить данные приложения"),
            confirm_label=_("Да, удалить данные"),
            warning=_("После удаления для следующего входа понадобится пароль root роутера. "
                    "Он у вас есть — его показывали при настройке, и его можно посмотреть на "
                    "устройстве в разделе «Безопасность». ВАЖНО: посмотрите/сохраните пароль "
                    "ДО удаления — после стирания его не восстановить. Сам роутер не "
                    "сбрасывается."),
            command=self._do_app_reset).grid(row=0, column=0, sticky="ew")

    def _do_app_reset(self, dc: _DangerConfirm) -> None:
        def done(_r: Any) -> None:
            dc.set_status(_("Данные приложения удалены с этого компьютера. "
                          "Перезапустите Re:Sputnik."), self.p.ok)

        def err(e: BaseException) -> None:
            dc.reset()
            dc.set_status(_("Не удалось полностью удалить: {0}").format(e), self.p.fail)

        run_async(self, profiles.reset_app_data, done, err)
