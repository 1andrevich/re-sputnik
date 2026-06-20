# SPDX-License-Identifier: GPL-2.0-only
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

OnDone = Callable[[], None]


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
        self._busy = False
        self._finished = False

        self._sc = kit.WizardScaffold(self, palette, step=3, label="Установка ПО", footer=False)
        self._scroll = self._sc.content
        body = self._scroll

        ctk.CTkLabel(body, text="Установка ПО", font=fonts.title(),
                     text_color=palette.text).grid(row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        ctk.CTkLabel(body, text="Роутер скачает и установит приложение, ядро и модули ядра. "
                     "Нужен интернет на роутере (предыдущий шаг).",
                     font=fonts.body(), text_color=palette.text_muted, wraplength=560,
                     justify="left").grid(row=1, column=0, pady=(0, 8), padx=32, sticky="w")

        # Filled in once we've probed the router (see _load_status): tells the user
        # what's already installed so they aren't forced to re-install.
        self._banner = ctk.CTkLabel(body, text="Проверяю, что уже установлено…",
                                    font=fonts.small(), text_color=palette.text_muted,
                                    wraplength=560, justify="left", anchor="w")
        self._banner.grid(row=2, column=0, padx=32, pady=(0, 10), sticky="ew")

        core_card = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        core_card.grid(row=3, column=0, padx=32, sticky="ew")
        core_card.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(core_card, palette, "core", "Ядро").grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(core_card, text="Оба ядра на базе sing-box и отличаются набором протоколов. "
                     "Несовместимые серверы приложение исключит автоматически.",
                     font=fonts.small(), text_color=palette.text_muted, wraplength=540,
                     justify="left").grid(row=1, column=0, padx=16, pady=(0, 4), sticky="w")
        # Same captions as the «Ядро» page — single source of truth in core_screen.
        r = 2
        for val, label, sub in CORE_OPTIONS:
            ctk.CTkRadioButton(core_card, text=label, value=val, variable=self._core,
                               font=fonts.body(), fg_color=palette.accent,
                               hover_color=palette.accent_hover).grid(
                row=r, column=0, padx=16, pady=(6, 0), sticky="w")
            ctk.CTkLabel(core_card, text=sub, font=fonts.small(), text_color=palette.text_muted,
                         wraplength=520, justify="left").grid(
                row=r + 1, column=0, padx=(40, 16), pady=(0, 2), sticky="w")
            r += 2
        ctk.CTkLabel(core_card, text="Размер сборки подбирается под устройство автоматически.",
                     font=fonts.small(), text_color=palette.text_muted).grid(
            row=r, column=0, padx=16, pady=(4, 12), sticky="w")

        bd_card = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        bd_card.grid(row=4, column=0, padx=32, pady=(12, 0), sticky="ew")
        bd_card.grid_columnconfigure(0, weight=1)
        ctk.CTkSwitch(bd_card, text="Также установить ByeDPI", font=fonts.body(),
                      variable=self._byedpi, onvalue="1", offvalue="0",
                      progress_color=palette.accent).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(bd_card, text="Обход DPI открывает заблокированные сайты без полного VPN: "
                     "маскирует трафик, чтобы фильтры провайдера его не распознавали. Иногда нужно "
                     "вручную подобрать параметры под вашего провайдера.", font=fonts.small(),
                     text_color=palette.text_muted, wraplength=520, justify="left", anchor="w").grid(
            row=1, column=0, padx=16, pady=(0, 12), sticky="w")

        self._go = ctk.CTkButton(body, text="Установить", font=fonts.heading(), height=42,
                                 fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                 command=self._run)
        self._go.grid(row=5, column=0, padx=32, pady=(16, 6), sticky="ew")

        self._next = ctk.CTkButton(body, text="Далее →", font=fonts.heading(), height=42,
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
            ctk.CTkButton(body, text="← Назад", font=fonts.body(), fg_color="transparent",
                          hover_color=palette.surface_hover, width=90, command=on_back).grid(
                row=8, column=0, padx=32, pady=(0, 10), sticky="w")

        self._load_status()

    # ----- pre-check ----------------------------------------------------

    def _load_status(self) -> None:
        client = self._client
        run_async(self, lambda: install_app.software_status(client), self._render_status,
                  lambda _e: self._banner.configure(
                      text="Не удалось проверить установленные пакеты — можно установить заново.",
                      text_color=self.p.text_muted))

    def _render_status(self, st: install_app.SoftwareStatus) -> None:
        if st.core:
            self._core.set(st.core)            # preselect the installed core
        if st.byedpi:
            self._byedpi.set("1")
        if st.ready:
            core_label = "hiddify-core" if st.core == "hiddify" else "sing-box-extended"
            extra = " + ByeDPI" if st.byedpi else ""
            self._banner.configure(
                text=f"✓ Уже установлено: приложение, {core_label}, модули ядра{extra}. "
                     "Можно идти дальше — или переустановить.", text_color=self.p.ok)
            self._go.configure(text="Переустановить")
            self._next.grid()                  # let the user proceed without reinstalling
        elif st.app or st.core or st.kmods:
            have = []
            if st.app:
                have.append("приложение")
            if st.core:
                have.append("hiddify-core" if st.core == "hiddify" else "sing-box-extended")
            if st.kmods:
                have.append("модули ядра")
            self._banner.configure(
                text="Частично установлено: " + ", ".join(have) +
                     ". Нажмите «Установить», чтобы доставить недостающее.",
                text_color=self.p.warn)
        else:
            self._banner.configure(text="Ничего не установлено — нажмите «Установить».",
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
        self._go.configure(state="disabled", text="Устанавливаю…")
        self._log.grid()  # reveal the log panel now that there's output
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")
        core = self._core.get()
        with_byedpi = self._byedpi.get() == "1"
        client = self._client

        def progress(m: str) -> None:
            post_to(self, lambda: self._append(m))

        def task() -> install_app.InstallResult:
            return install_app.run(client, core, with_byedpi=with_byedpi, progress=progress)

        run_async(self, task, self._done, self._err)

    def _err(self, e: BaseException) -> None:
        self._busy = False
        self._go.configure(state="normal", text="Установить")
        self._append(f"Ошибка: {e}")

    def _done(self, res: install_app.InstallResult) -> None:
        self._busy = False
        if res.ok:
            self._append("✓ Установлено: " + ", ".join(res.steps))
            self._go.grid_remove()
            self._next.grid()
        else:
            self._go.configure(state="normal", text="Повторить")
            self._append("✗ " + (res.error or "не удалось"))
