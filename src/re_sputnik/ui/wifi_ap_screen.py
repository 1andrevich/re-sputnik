# SPDX-License-Identifier: GPL-2.0-only
"""Пошаговая настройка — phase «Точка доступа».

Sets up the router's own Wi-Fi (the home network devices connect to): one SSID +
password across all suitable radios. Optional — a wired-only setup can skip it.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from ..engine import network as net
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async

OnDone = Callable[[], None]


class WifiApScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, on_done: OnDone, on_back: Optional[OnDone] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_done = on_done
        self._on_back = on_back

        self._sc = kit.WizardScaffold(self, palette, step=6, label="Wi-Fi", footer=False)
        self._scroll = self._sc.content
        b = self._scroll

        ctk.CTkLabel(b, text="Точка доступа", font=fonts.title(), text_color=palette.text).grid(
            row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        ctk.CTkLabel(b, text="Создайте Wi-Fi-сеть роутера, к которой будут подключаться ваши "
                     "устройства. Можно пропустить, если используете только провод.",
                     font=fonts.body(), text_color=palette.text_muted, wraplength=560,
                     justify="left").grid(row=1, column=0, pady=(0, 8), padx=32, sticky="w")

        # Prominent notice shown right above the form when there's no Wi-Fi radio
        # (a VM or wired-only device) — so the greyed-out fields are explained.
        self._banner = ctk.CTkLabel(b, text="", font=fonts.body(), text_color=palette.warn,
                                    wraplength=560, justify="left", anchor="w")
        self._banner.grid(row=2, column=0, padx=32, pady=(0, 8), sticky="ew")
        self._banner.grid_remove()

        card = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        card.grid(row=3, column=0, padx=32, sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="Имя сети (SSID)", font=fonts.small(),
                     text_color=palette.text_muted).grid(row=0, column=0, padx=16, pady=(12, 0),
                                                         sticky="w")
        self._ssid = ctk.CTkEntry(card, font=fonts.body(), placeholder_text="Моя сеть")
        self._ssid.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        ctk.CTkLabel(card, text="Пароль (не менее 8 символов)", font=fonts.small(),
                     text_color=palette.text_muted).grid(row=2, column=0, padx=16, pady=(6, 0),
                                                         sticky="w")
        pwrow = ctk.CTkFrame(card, fg_color="transparent")
        pwrow.grid(row=3, column=0, padx=16, pady=4, sticky="ew")
        pwrow.grid_columnconfigure(0, weight=1)
        self._key = ctk.CTkEntry(pwrow, font=fonts.body(), show="•", placeholder_text="Пароль Wi-Fi")
        self._key.grid(row=0, column=0, sticky="ew")
        self._pw_visible = False
        self._eye = ctk.CTkButton(pwrow, text="👁", font=fonts.body(), width=40,
                                  fg_color=palette.surface_hover, hover_color=palette.border,
                                  command=self._toggle_pw)
        self._eye.grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(pwrow, text="Сгенерировать", font=fonts.small(), width=120,
                      fg_color=palette.surface_hover, hover_color=palette.border,
                      command=self._gen_pw).grid(row=0, column=2, padx=(6, 0))
        # 6 GHz is handled automatically (every supported band is enabled; if a
        # band — usually 6 GHz — doesn't come up, we report it in the result).
        self._create = ctk.CTkButton(card, text="Создать сеть", font=fonts.heading(), height=40,
                                     fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                     command=self._do_create)
        self._create.grid(row=5, column=0, padx=16, pady=(8, 12), sticky="ew")

        self._next = ctk.CTkButton(b, text="Далее →", font=fonts.heading(), height=42,
                                   fg_color=palette.ok, hover_color=palette.accent_hover,
                                   command=on_done)
        self._next.grid(row=4, column=0, padx=32, pady=(14, 4), sticky="ew")
        self._next.grid_remove()

        skiprow = ctk.CTkFrame(b, fg_color="transparent")
        skiprow.grid(row=5, column=0, padx=32, pady=(4, 8), sticky="w")
        ctk.CTkButton(skiprow, text="Пропустить", font=fonts.body(), fg_color="transparent",
                      hover_color=palette.surface_hover, command=on_done).grid(row=0, column=0)
        if on_back is not None:
            ctk.CTkButton(skiprow, text="← Назад", font=fonts.body(), fg_color="transparent",
                          hover_color=palette.surface_hover, width=90, command=on_back).grid(
                row=0, column=1, padx=(8, 0))

        self._status = ctk.CTkLabel(b, text="", font=fonts.small(), text_color=palette.text_muted,
                                    anchor="w", wraplength=560, justify="left")
        self._status.grid(row=6, column=0, padx=32, pady=(4, 12), sticky="w")

        self._load_status()

    # ----- status -------------------------------------------------------

    def _load_status(self) -> None:
        client = self._client

        def task() -> dict:
            return {"ap": net.ap_status(client), "radios": net.list_radios(client)}

        run_async(self, task, self._render_status, lambda _e: None)

    def _render_status(self, d: dict) -> None:
        # No Wi-Fi radio (e.g. a VirtualBox VM, or a wired-only device): there's
        # nothing to configure, so disable the form and let the user continue
        # instead of showing a broken-looking "no suitable radio" failure.
        if not d["radios"]:
            for w in (self._ssid, self._key, self._eye, self._create):
                w.configure(state="disabled")
            self._banner.configure(
                text="⚠ На этом устройстве не найден Wi-Fi-чип — точку доступа создать нельзя. "
                     "Подключайте устройства по кабелю. Этот шаг можно пропустить.")
            self._banner.grid()
            self._next.grid()
            return
        st = d["ap"]
        if st.ssid:
            self._ssid.insert(0, st.ssid)
            bands_txt = net.format_bands(st.bands)
            self._status.configure(
                text=f"Текущая сеть: «{st.ssid}»" + (f" — {bands_txt}." if bands_txt else "."),
                text_color=self.p.ok)
            self._next.grid()

    # ----- password helpers ---------------------------------------------

    def _toggle_pw(self) -> None:
        self._pw_visible = not self._pw_visible
        self._key.configure(show="" if self._pw_visible else "•")

    def _gen_pw(self) -> None:
        from .. import secrets as app_secrets

        pw = app_secrets.generate_wifi_passphrase()
        self._key.delete(0, "end")
        self._key.insert(0, pw)
        if not self._pw_visible:
            self._toggle_pw()  # reveal so the user can read/write it down

    # ----- actions ------------------------------------------------------

    def _do_create(self) -> None:
        ssid = self._ssid.get().strip()
        key = self._key.get()
        if not ssid:
            self._status.configure(text="Введите имя сети.", text_color=self.p.warn)
            return
        if key and len(key) < 8:
            self._status.configure(text="Пароль должен быть не короче 8 символов.",
                                   text_color=self.p.warn)
            return
        self._create.configure(state="disabled", text="Создаю…")
        self._status.configure(text="Настраиваю Wi-Fi…", text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: net.configure_ap(client, ssid=ssid, key=key),
                  self._created, self._err)

    def _created(self, res: "net.ApResult") -> None:
        self._create.configure(state="normal", text="Создать сеть")
        # Dedupe band labels and treat a band as failed ONLY if it came up on NO
        # radio. Routers with two radios on one band (e.g. two 5 GHz, or a 6 GHz
        # radio that reports "5g") otherwise show the same band as both working and
        # failed — a confusing contradiction. If the band works on any radio, it's
        # available to the user, so don't warn about it.
        ok = list(dict.fromkeys(res.enabled))
        failed = [b for b in dict.fromkeys(res.failed) if b not in ok]

        if not ok:
            self._status.configure(text="Не удалось поднять Wi-Fi — ни один диапазон не "
                                   "запустился. Возможно, радио занято Wi-Fi-подключением к "
                                   "интернету, или прошивка его блокирует. Подключите интернет "
                                   "кабелем и попробуйте снова.", text_color=self.p.warn)
            return

        ok_labels = ", ".join(net.band_label(b) for b in ok)
        text = f"Wi-Fi создан и работает (диапазоны {ok_labels})."
        color = self.p.ok
        if failed:
            bad_labels = ", ".join(net.band_label(b) for b in failed)
            text += (f"\nДиапазон {bad_labels} включить не удалось: устройства, которым нужен "
                     "именно он, эту сеть не увидят — но на остальных диапазонах Wi-Fi работает.")
            if any(b in ("6g", "6") for b in failed):
                text += (" Чаще всего так бывает с 6 ГГц — из-за устаревших настроек разрешённых "
                         "частот в прошивке роутера.")
            color = self.p.warn
        self._status.configure(text=text, text_color=color)
        self._next.grid()

    def _err(self, e: BaseException) -> None:
        self._create.configure(state="normal", text="Создать сеть")
        self._status.configure(text=f"Не удалось: {e}", text_color=self.p.fail)
