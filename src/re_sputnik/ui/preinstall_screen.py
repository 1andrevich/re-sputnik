# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Option 3 — «Предустановить пакеты» screen.

Pick a core (+ optional ByeDPI); the PC downloads the packages and pushes them
to the router for an offline install. For staging a router to be deployed
somewhere without internet.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from ..engine import preinstall
from ..router import RouterClient
from . import kit
from .core_screen import CORE_OPTIONS
from .theme import Palette, fonts
from .worker import post_to, run_async
from ..i18n import _, luci_lang

OnDone = Callable[[], None]


class PreinstallScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, on_done: OnDone, on_continue: Optional[OnDone] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_done = on_done
        # Optional next step after a successful staging: pre-configure WAN + AP so
        # the device can be deployed with minimal work on-site.
        self._on_continue = on_continue
        self._core = ctk.StringVar(value="singbox")
        self._app = ctk.StringVar(value="1")
        self._byedpi = ctk.StringVar(value="0")
        self._zapret = ctk.StringVar(value="0")
        self._busy = False

        self._sc = kit.WizardScaffold(self, palette, step=4, label=_("Компоненты"), footer=False)
        self._scroll = self._sc.content
        body = self._scroll

        ctk.CTkLabel(body, text=_("Предустановить пакеты"), font=fonts.title(),
                     text_color=palette.text).grid(row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        ctk.CTkLabel(body, text=_("Пакеты скачает этот компьютер и передаст на роутер — "
                     "для подготовки устройства к установке без интернета."),
                     font=fonts.body(), text_color=palette.text_muted, wraplength=560,
                     justify="left").grid(row=1, column=0, pady=(0, 8), padx=32, sticky="w")

        # Filled in by _load_status: what the router already has, so an already-set-up
        # device isn't forced through a pointless re-stage.
        self._banner = ctk.CTkLabel(body, text=_("Проверяю, что уже установлено на роутере…"),
                                    font=fonts.small(), text_color=palette.text_muted,
                                    wraplength=560, justify="left", anchor="w")
        self._banner.grid(row=2, column=0, padx=32, pady=(0, 10), sticky="ew")

        # Core selection.
        core_card = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        core_card.grid(row=3, column=0, padx=32, sticky="ew")
        core_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(core_card, text=_("Ядро (с модулями ядра)"), font=fonts.heading(),
                     text_color=palette.text).grid(row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        # Same options + captions as the «Ядро» page and Quick Setup — single
        # source of truth in core_screen.CORE_OPTIONS, so the help text matches.
        for i, (val, label, sub) in enumerate(CORE_OPTIONS, start=1):
            ctk.CTkRadioButton(core_card, text=label, value=val, variable=self._core,
                               font=fonts.body(), fg_color=palette.accent,
                               hover_color=palette.accent_hover).grid(
                row=i * 2 - 1, column=0, padx=16, pady=(8, 0), sticky="w")
            ctk.CTkLabel(core_card, text=_(sub), font=fonts.small(), text_color=palette.text_muted,
                         justify="left", wraplength=740).grid(
                row=i * 2, column=0, padx=(40, 16), pady=(0, 2), sticky="w")
        ctk.CTkLabel(core_card, text=_("Обязательно: kmod-nft-tproxy + kmod-tun."), font=fonts.small(),
                     text_color=palette.text_muted).grid(
                row=len(CORE_OPTIONS) * 2 + 1, column=0, padx=16, pady=(2, 12), sticky="w")

        # LuCI app.
        app_card = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        app_card.grid(row=4, column=0, padx=32, pady=(12, 0), sticky="ew")
        app_card.grid_columnconfigure(0, weight=1)
        ctk.CTkSwitch(app_card, text=_("Установить LuCI-приложение Re:HomeProxy (+ русский язык)"),
                      font=fonts.body(), variable=self._app, onvalue="1", offvalue="0",
                      progress_color=palette.accent).grid(row=0, column=0, padx=16, pady=(12, 2),
                                                          sticky="w")
        ctk.CTkLabel(app_card, text=_("Без него на роутере будет только ядро, но не сам HomeProxy "
                     "(веб-настройки и импорт серверов работать не будут). Оставьте включённым для "
                     "полной офлайн-установки."), font=fonts.small(), text_color=palette.text_muted,
                     wraplength=520, justify="left").grid(row=1, column=0, padx=16, pady=(0, 12),
                                                          sticky="w")

        # ByeDPI.
        bd_card = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        bd_card.grid(row=5, column=0, padx=32, pady=(12, 0), sticky="ew")
        bd_card.grid_columnconfigure(0, weight=1)
        ctk.CTkSwitch(bd_card, text=_("Также установить ByeDPI"), font=fonts.body(),
                      variable=self._byedpi, onvalue="1", offvalue="0",
                      progress_color=palette.accent).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(bd_card, text=_("Обход DPI открывает заблокированные сайты без полного VPN: "
                     "маскирует трафик, чтобы фильтры провайдера его не распознавали. Иногда нужно "
                     "вручную подобрать параметры под вашего провайдера."), font=fonts.small(),
                     text_color=palette.text_muted, wraplength=520, justify="left", anchor="w").grid(
            row=1, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkSwitch(bd_card, text=_("Также установить Zapret"), font=fonts.body(),
                      variable=self._zapret, onvalue="1", offvalue="0",
                      progress_color=palette.accent).grid(row=2, column=0, padx=16, pady=(0, 2), sticky="w")
        ctk.CTkLabel(bd_card, text=_("Другой движок обхода DPI: умеет ещё видео (QUIC) и звонки, "
                     "с которыми ByeDPI не справляется. Нужный модуль ядра (kmod-nft-queue) "
                     "скачивается и ставится вместе с ним."), font=fonts.small(),
                     text_color=palette.text_muted, wraplength=520, justify="left", anchor="w").grid(
            row=3, column=0, padx=16, pady=(0, 12), sticky="w")

        self._go = ctk.CTkButton(body, text=_("Скачать и установить"), font=fonts.heading(), height=42,
                                 fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                 command=self._run)
        self._go.grid(row=6, column=0, padx=32, pady=(16, 6), sticky="ew")

        self._log = ctk.CTkTextbox(body, font=ctk.CTkFont(family="Consolas", size=12),
                                   fg_color=palette.bg, text_color=palette.text_muted, height=180)
        self._log.grid(row=7, column=0, padx=32, pady=(0, 6), sticky="ew")
        self._log.configure(state="disabled")
        self._log.grid_remove()  # hidden until work runs (no empty void)

        # Revealed after a successful staging when an on_continue step is wired —
        # lets the installer pre-configure WAN + Wi-Fi before handing off the device.
        self._continue_btn = ctk.CTkButton(
            body, text=_("Далее: интернет (WAN) и Wi-Fi →"), font=fonts.heading(), height=42,
            fg_color=palette.ok, text_color=palette.accent_fg, hover_color=palette.accent_hover, command=self._continue)
        self._continue_btn.grid(row=8, column=0, padx=32, pady=(6, 6), sticky="ew")
        self._continue_btn.grid_remove()

        ctk.CTkButton(body, text=_("← Назад"), font=fonts.body(), fg_color="transparent",
                      hover_color=palette.surface_hover, width=90, command=on_done).grid(
            row=9, column=0, padx=32, pady=(4, 10), sticky="w")

        self._load_status()

    # ----- pre-check ----------------------------------------------------

    def _load_status(self) -> None:
        from ..engine import install_app
        client = self._client
        run_async(self, lambda: install_app.software_status(client), self._render_status,
                  lambda _e: self._banner.configure(
                      text=_("Не удалось проверить роутер — можно предустановить заново."),
                      text_color=self.p.text_muted))

    def _render_status(self, st) -> None:  # st: install_app.SoftwareStatus
        if st.core:
            self._core.set(st.core)
        self._app.set("0" if st.app else "1")
        if st.byedpi:
            self._byedpi.set("1")
        if st.zapret:
            self._zapret.set("1")
        if st.ready:
            core_label = "hiddify-core" if st.core == "hiddify" else "sing-box-extended"
            extra = "".join(x for x, on in ((" + ByeDPI", st.byedpi), (" + Zapret", st.zapret)) if on)
            self._banner.configure(
                text=_("✓ На роутере уже есть: приложение, {0}, модули ядра{1}. Предустановка не нужна — можно сразу к настройке.").format(core_label, extra) if self._on_continue
                     else _("✓ На роутере уже всё установлено ({0}{1}).").format(core_label, extra),
                text_color=self.p.ok)
            self._go.configure(text=_("Предустановить заново"))
            if self._on_continue is not None:
                self._continue_btn.grid()
        elif st.app or st.core or st.kmods:
            have = []
            if st.app:
                have.append(_("приложение"))
            if st.core:
                have.append("hiddify-core" if st.core == "hiddify" else "sing-box-extended")
            if st.kmods:
                have.append(_("модули ядра"))
            self._banner.configure(
                text=_("Частично установлено: ") + ", ".join(have) +
                     _(". Предустановка доставит недостающее."), text_color=self.p.warn)
        else:
            self._banner.configure(text=_("На роутере ничего не установлено."),
                                   text_color=self.p.text_muted)

    # ----- run ----------------------------------------------------------

    def _append(self, msg: str) -> None:
        self._log.configure(state="normal")
        self._log.insert("end", msg + "\n")
        self._log.see("end")
        self._log.configure(state="disabled")

    def _run(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._go.configure(state="disabled", text=_("Работаю…"))
        self._log.grid()  # reveal the log panel now that there's output
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        core = self._core.get()
        with_byedpi = self._byedpi.get() == "1"
        with_zapret = self._zapret.get() == "1"
        with_app = self._app.get() == "1"
        client = self._client

        def progress(m: str) -> None:
            post_to(self, lambda: self._append(m))

        def task() -> preinstall.PreinstallResult:
            return preinstall.run(client, core, with_byedpi=with_byedpi,
                                  with_zapret=with_zapret, with_app=with_app,
                                  language=luci_lang(), progress=progress)

        run_async(self, task, self._done, self._err)

    def _err(self, e: BaseException) -> None:
        self._busy = False
        self._go.configure(state="normal", text=_("Скачать и установить"))
        self._append(_("Ошибка: {0}").format(e))

    def _continue(self) -> None:
        if self._on_continue is not None:
            self._on_continue()

    def _done(self, res: preinstall.PreinstallResult) -> None:
        self._busy = False
        self._go.configure(state="normal", text=_("Скачать и установить"))
        if res.ok:
            self._append(_("✓ Установлено: ") + ", ".join(res.installed))
            if self._on_continue is not None:
                self._append(_("Можно заранее настроить интернет (WAN) и Wi-Fi — кнопка ниже."))
                self._continue_btn.grid()
        else:
            self._append("✗ " + (res.error or _("не удалось")))
