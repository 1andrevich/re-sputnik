# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Quick-Setup phase 2 — install Re:HomeProxy software on a clean router.

Online flow (router already has internet from the previous phase): installs the
LuCI app, the chosen core (size-gated by the app's own core_mgmt), kernel
modules, and optionally ByeDPI — then enables the service. Drives
``engine.install_app``; streams progress into a log.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from ..engine import install_app
from ..router import RouterClient
from . import kit
from .core_screen import CORE_OPTIONS
from .theme import Palette, fonts
from .worker import post_to, run_async
from ..i18n import _, luci_lang

OnDone = Callable[[], None]

# A failure where the ROUTER couldn't download (GitHub+mirror or the OpenWrt feed
# unreachable/throttled) is the case Pre-install solves — the PC does the download
# (where the user can have a VPN up) and pushes to the router. Excludes causes
# Pre-install can't help (out of space → same disk).
_DOWNLOAD_FAIL = ("скачать", "скачивание", "download", "wget", "resolve",
                  "temporary failure", "timed out", "timeout", "unreachable",
                  "connection", "network")
_NOT_CONNECTIVITY = ("места", "no space", "only have", "available on filesystem")


def _looks_like_download_failure(err: str) -> bool:
    low = (err or "").lower()
    if any(s in low for s in _NOT_CONNECTIVITY):
        return False
    return any(s in low for s in _DOWNLOAD_FAIL)


class SoftwareScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, on_done: OnDone, on_back: Optional[OnDone] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_done = on_done
        self._on_back = on_back
        self._core = ctk.StringVar(value="singbox")
        self._byedpi = ctk.StringVar(value="0")
        self._zapret = ctk.StringVar(value="0")
        self._busy = False
        self._finished = False

        self._sc = kit.WizardScaffold(self, palette, step=3, label=_("Установка ПО"), footer=False)
        self._scroll = self._sc.content
        body = self._scroll

        ctk.CTkLabel(body, text=_("Установка ПО"), font=fonts.title(),
                     text_color=palette.text).grid(row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        ctk.CTkLabel(body, text=_("Роутер скачает и установит приложение, ядро и модули ядра. "
                     "Нужен интернет на роутере (предыдущий шаг)."),
                     font=fonts.body(), text_color=palette.text_muted, wraplength=560,
                     justify="left").grid(row=1, column=0, pady=(0, 8), padx=32, sticky="w")

        # Filled in once we've probed the router (see _load_status): tells the user
        # what's already installed so they aren't forced to re-install.
        self._banner = ctk.CTkLabel(body, text=_("Проверяю, что уже установлено…"),
                                    font=fonts.small(), text_color=palette.text_muted,
                                    wraplength=560, justify="left", anchor="w")
        self._banner.grid(row=2, column=0, padx=32, pady=(0, 10), sticky="ew")

        core_card = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        core_card.grid(row=3, column=0, padx=32, sticky="ew")
        core_card.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(core_card, palette, "core", _("Ядро")).grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(core_card, text=_("Оба ядра на базе sing-box и отличаются набором протоколов. "
                     "Несовместимые серверы приложение исключит автоматически."),
                     font=fonts.small(), text_color=palette.text_muted, wraplength=540,
                     justify="left").grid(row=1, column=0, padx=16, pady=(0, 4), sticky="w")
        # Same captions as the «Ядро» page — single source of truth in core_screen.
        r = 2
        for val, label, sub in CORE_OPTIONS:
            ctk.CTkRadioButton(core_card, text=label, value=val, variable=self._core,
                               font=fonts.body(), fg_color=palette.accent,
                               hover_color=palette.accent_hover).grid(
                row=r, column=0, padx=16, pady=(6, 0), sticky="w")
            ctk.CTkLabel(core_card, text=_(sub), font=fonts.small(), text_color=palette.text_muted,
                         wraplength=520, justify="left").grid(
                row=r + 1, column=0, padx=(40, 16), pady=(0, 2), sticky="w")
            r += 2
        ctk.CTkLabel(core_card, text=_("Размер сборки подбирается под устройство автоматически."),
                     font=fonts.small(), text_color=palette.text_muted).grid(
            row=r, column=0, padx=16, pady=(4, 12), sticky="w")

        bd_card = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        bd_card.grid(row=4, column=0, padx=32, pady=(12, 0), sticky="ew")
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
                     "с которыми ByeDPI не справляется. Тоже бесплатно и без VPN; нужные модули ядра "
                     "ставятся автоматически. Что сработает — зависит от провайдера, можно включить оба."),
                     font=fonts.small(), text_color=palette.text_muted, wraplength=520, justify="left",
                     anchor="w").grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")

        self._go = ctk.CTkButton(body, text=_("Установить"), font=fonts.heading(), height=42,
                                 fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                 command=self._run)
        self._go.grid(row=5, column=0, padx=32, pady=(16, 6), sticky="ew")

        self._next = ctk.CTkButton(body, text=_("Далее →"), font=fonts.heading(), height=42,
                                   fg_color=palette.ok, hover_color=palette.accent_hover,
                                   command=self._on_done)
        self._next.grid(row=6, column=0, padx=32, pady=(0, 6), sticky="ew")
        self._next.grid_remove()

        self._log = ctk.CTkTextbox(body, font=ctk.CTkFont(family="Consolas", size=12),
                                   fg_color=palette.bg, text_color=palette.text_muted, height=180)
        self._log.grid(row=7, column=0, padx=32, pady=(0, 6), sticky="ew")
        self._log.configure(state="disabled")
        self._log.grid_remove()  # hidden until an install runs (no empty void)

        if on_back is not None:
            ctk.CTkButton(body, text=_("← Назад"), font=fonts.body(), fg_color="transparent",
                          hover_color=palette.surface_hover, width=90, command=on_back).grid(
                row=8, column=0, padx=32, pady=(0, 10), sticky="w")

        self._load_status()

    # ----- pre-check ----------------------------------------------------

    def _load_status(self) -> None:
        client = self._client
        run_async(self, lambda: install_app.software_status(client), self._render_status,
                  lambda _e: self._banner.configure(
                      text=_("Не удалось проверить установленные пакеты — можно установить заново."),
                      text_color=self.p.text_muted))

    def _render_status(self, st: install_app.SoftwareStatus) -> None:
        if st.core:
            self._core.set(st.core)            # preselect the installed core
        if st.byedpi:
            self._byedpi.set("1")
        if st.zapret:
            self._zapret.set("1")
        if st.ready:
            core_label = "hiddify-core" if st.core == "hiddify" else "sing-box-extended"
            extra = "".join(x for x, on in ((" + ByeDPI", st.byedpi), (" + Zapret", st.zapret)) if on)
            self._banner.configure(
                text=_("✓ Уже установлено: приложение, {0}, модули ядра{1}. Можно идти дальше — или переустановить.").format(core_label, extra), text_color=self.p.ok)
            self._go.configure(text=_("Переустановить"))
            self._next.grid()                  # let the user proceed without reinstalling
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
                     _(". Нажмите «Установить», чтобы доставить недостающее."),
                text_color=self.p.warn)
        else:
            self._banner.configure(text=_("Ничего не установлено — нажмите «Установить»."),
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
        self._go.configure(state="disabled", text=_("Устанавливаю…"))
        self._log.grid()  # reveal the log panel now that there's output
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        core = self._core.get()
        with_byedpi = self._byedpi.get() == "1"
        with_zapret = self._zapret.get() == "1"
        client = self._client

        def progress(m: str) -> None:
            post_to(self, lambda: self._append(m))

        def task() -> install_app.InstallResult:
            return install_app.run(client, core, with_byedpi=with_byedpi,
                                   with_zapret=with_zapret, language=luci_lang(), progress=progress)

        run_async(self, task, self._done, self._err)

    def _err(self, e: BaseException) -> None:
        self._busy = False
        self._go.configure(state="normal", text=_("Установить"))
        self._append(_("Ошибка: {0}").format(e))

    def _done(self, res: install_app.InstallResult) -> None:
        self._busy = False
        if res.ok:
            self._append(_("✓ Установлено: ") + ", ".join(res.steps))
            self._go.grid_remove()
            self._next.grid()
        else:
            self._go.configure(state="normal", text=_("Повторить"))
            self._append("✗ " + (res.error or _("не удалось")))
            # The error stays above; this only ADDS a path forward when the router
            # couldn't reach the download servers (restricted network).
            if _looks_like_download_failure(res.error or ""):
                self._append(_("Роутер не смог скачать пакеты. Если доступ к ресурсам "
                               "ограничен, включите VPN на этом компьютере и воспользуйтесь "
                               "предустановкой («Предустановить пакеты»): она скачивает "
                               "пакеты на компьютере и передаёт их на роутер."))
