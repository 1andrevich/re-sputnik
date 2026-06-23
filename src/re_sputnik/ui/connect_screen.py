# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Phase 0 — Connection screen.

The first end-to-end path: the user (or autodetect) supplies the router address
and credentials, the app connects over SSH, shows the host-key fingerprint
(TOFU), reads the router's state, and hands a connected RouterClient + state to
the next phase. All blocking work runs off the UI thread.

Real-world hints ("plug a LAN cable", "join the router's Wi-Fi") live here as
guidance text — the user is never told to open a terminal.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

import customtkinter as ctk
from PIL import Image

from .. import profiles as app_profiles
from .. import secrets as app_secrets
from ..engine import firmware, key_lease
from ..router import RouterClient, RouterError, RouterState, detect_state
from ..router.client import HostKeyMismatch
from ..router.discovery import Candidate, Identity, discover_routers
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import N_, _

# Called with a live client + its detected state when connection succeeds.
OnConnected = Callable[[RouterClient, RouterState], None]
OnBack = Callable[[], None]


class ConnectScreen(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        palette: Palette,
        *,
        on_connected: OnConnected,
        on_back: Optional[OnBack] = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._on_connected = on_connected
        self._on_back = on_back
        self._busy = False
        self._connected: tuple[RouterClient, RouterState] | None = None

        self._candidates: list[Candidate] = []

        # Quick Setup chrome (titlebar + step strip). The connect/next flow has
        # several in-content buttons, so the footer is left off for this screen.
        # Connect is the gateway/login — no chrome (no titlebar band, no step
        # strip): the banner on the mode picker already brands the entry, and a
        # second logo here only eats space on this content-heavy screen.
        self._sc = kit.WizardScaffold(self, palette, footer=False, strip=False, titlebar=False)
        self._scroll = self._sc.content
        self._build()
        # Floating help affordance, top-right corner — deliberately NOT the blue
        # accent so it reads as secondary, not the primary "Подключиться" action.
        self._help_win: Optional[ctk.CTkToplevel] = None
        self._help_img: Optional[ctk.CTkImage] = None
        self._help_btn = ctk.CTkButton(
            self, text=_("❓ Не понимаю, как подключить роутер"), font=fonts.small(), height=30,
            fg_color=palette.warn, hover_color="#D97706", text_color="#10131A",
            command=self._show_help)
        self._help_btn.place(relx=1.0, rely=0.0, x=-18, y=14, anchor="ne")  # top-right (no chrome)
        # Autodetect: enumerate + probe candidates off-thread, then fill the form.
        self._set_status(_("Поиск роутера в сети…"), "muted")
        run_async(self, discover_routers, self._fill_candidates, lambda _e: None)

    # ----- "how to connect" help popup ----------------------------------

    _HELP_STEPS = [
        (N_("1. Питание"), N_("Вставьте блок питания роутера в розетку и в круглый порт питания на "
         "роутере. Подождите ~1 минуту, пока он загрузится (индикаторы перестанут мигать).")),
        (N_("2. Кабель от провайдера"), N_("Кабель интернета, заведённый в квартиру, вставьте в порт "
         "INTERNET (обычно синий, подписан INTERNET или WAN).")),
        (N_("3. Кабель к компьютеру"), N_("Соедините Ethernet-кабелем любой жёлтый порт LAN (LAN 1–4) "
         "роутера с сетевым разъёмом вашего компьютера.")),
        (N_("Без кабеля?"), N_("Можно вместо этого подключиться к Wi-Fi роутера — имя сети и пароль "
         "обычно напечатаны на наклейке снизу роутера.")),
        (N_("4. Подключиться"), N_("Вернитесь в приложение и нажмите «Подключиться». Если адрес не "
         "подставился сам — впишите 192.168.1.1.")),
    ]

    def _show_help(self) -> None:
        if self._help_win is not None and self._help_win.winfo_exists():
            self._help_win.lift()
            self._help_win.focus()
            return
        p = self.p
        win = ctk.CTkToplevel(self)
        self._help_win = win
        win.title(_("Как подключить роутер"))
        win.configure(fg_color=p.bg)
        win.geometry("780x820")
        win.minsize(700, 560)  # don't let it shrink into an unreadable box
        win.transient(self.winfo_toplevel())
        win.after(120, win.lift)  # ensure it surfaces above the main window

        body = ctk.CTkScrollableFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=16, pady=16)
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text=_("Как подключить роутер"), font=fonts.title(),
                     text_color=p.text).grid(row=0, column=0, sticky="w", pady=(0, 8))

        # Localized router-wiring diagram (text baked into the image). The Russian
        # original is router_scheme.png; other languages have router_<code>.png.
        from ..i18n import current_language
        _imgdir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "resources", "images")
        _icode = {"zh_Hans": "zh"}.get(current_language(), current_language())
        path = next(
            (p for p in (os.path.join(_imgdir, f"router_{_icode}.png"),
                         os.path.join(_imgdir, "router_scheme.png"))
             if os.path.exists(p)), "")
        if path:
            try:
                pil = Image.open(path)
                w, h = pil.size
                disp_w = 700
                self._help_img = ctk.CTkImage(light_image=pil, dark_image=pil,
                                              size=(disp_w, int(h * disp_w / w)))
                ctk.CTkLabel(body, image=self._help_img, text="").grid(
                    row=1, column=0, pady=(0, 12))
            except Exception:  # noqa: BLE001 — a broken image shouldn't kill the popup
                pass

        for i, (title, text) in enumerate(self._HELP_STEPS, start=2):
            card = ctk.CTkFrame(body, fg_color=p.surface, corner_radius=10)
            card.grid(row=i, column=0, sticky="ew", pady=4)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=_(title), font=fonts.heading(), text_color=p.text,
                         anchor="w").grid(row=0, column=0, padx=16, pady=(10, 0), sticky="w")
            ctk.CTkLabel(card, text=_(text), font=fonts.body(), text_color=p.text_muted,
                         anchor="w", wraplength=700, justify="left").grid(
                row=1, column=0, padx=16, pady=(2, 10), sticky="w")

        ctk.CTkButton(body, text=_("Понятно"), font=fonts.body(), fg_color=p.accent, text_color=p.accent_fg,
                      hover_color=p.accent_hover, command=win.destroy).grid(
            row=len(self._HELP_STEPS) + 2, column=0, pady=(12, 4), sticky="e")

    # ----- layout -------------------------------------------------------

    def _build(self) -> None:
        p = self.p
        body = self._scroll

        ctk.CTkLabel(
            body, text=_("Подключение к роутеру"), font=fonts.title(), text_color=p.text
        ).grid(row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        ctk.CTkLabel(
            body,
            text=_("Подключите роутер к ПК кабелем (порт LAN) или войдите в его Wi-Fi, "
            "затем нажмите «Подключиться»."),
            font=fonts.body(),
            text_color=p.text_muted,
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, pady=(0, 14), padx=32, sticky="w")

        # Saved routers (WinBox-style): one-click reconnect to known devices.
        # Populated from the profiles registry; hidden when there are none.
        self._saved_card = ctk.CTkFrame(body, fg_color=p.surface, corner_radius=12,
                                        border_width=1, border_color=p.border)
        self._saved_card.grid(row=2, column=0, padx=32, pady=(0, 12), sticky="ew")
        self._saved_card.grid_columnconfigure(0, weight=1)
        self._saved_card.grid_remove()
        self._build_saved()

        form = ctk.CTkFrame(body, fg_color=p.surface, corner_radius=12, border_width=1, border_color=p.border)
        form.grid(row=3, column=0, padx=32, sticky="ew")
        form.grid_columnconfigure(1, weight=1)

        # Detected-routers selector (populated async; picking one fills the IP).
        ctk.CTkLabel(form, text=_("Найдено"), font=fonts.body(), text_color=p.text_muted).grid(
            row=0, column=0, padx=(16, 12), pady=8, sticky="w"
        )
        self._candidate_menu = ctk.CTkOptionMenu(
            form,
            values=[_("поиск…")],
            font=fonts.body(),
            fg_color=p.surface_hover,
            button_color=p.accent,
            button_hover_color=p.accent_hover,
            command=self._on_pick_candidate,
        )
        self._candidate_menu.grid(row=0, column=1, padx=(0, 16), pady=8, sticky="ew")

        self._ip = self._field(form, 1, _("Адрес роутера"), "192.168.1.1")
        self._port = self._field(form, 2, _("Порт"), "22", width=80)
        self._user = self._field(form, 3, _("Логин"), "root")
        self._password = self._field(form, 4, _("Пароль"), "", show="•",
                                     placeholder=_("пусто — если пароль ещё не задан"))
        ctk.CTkLabel(
            form,
            text=_("Новый роутер обычно без пароля — оставьте поле пустым."),
            font=fonts.small(), text_color=p.text_muted,
        ).grid(row=5, column=1, padx=(0, 16), pady=(0, 8), sticky="w")

        # Remember this router: on a successful connect, save the profile (and the
        # password into the OS keychain) so it appears in the saved list next time.
        self._remember = ctk.StringVar(value="1")
        ctk.CTkCheckBox(
            form, text=_("Запомнить роутер (адрес и пароль — в хранилище ОС)"), font=fonts.small(),
            variable=self._remember, onvalue="1", offvalue="0", fg_color=p.accent,
            hover_color=p.accent_hover,
        ).grid(row=6, column=0, columnspan=2, padx=16, pady=(0, 10), sticky="w")

        self._connect_btn = ctk.CTkButton(
            body,
            text=_("Подключиться"),
            font=fonts.heading(),
            height=42,
            fg_color=p.accent, text_color=p.accent_fg,
            hover_color=p.accent_hover,
            command=self._do_connect,
        )
        self._connect_btn.grid(row=4, column=0, padx=32, pady=(18, 6), sticky="ew")

        # "Далее →" sits right under the connect button so it's visible the moment
        # a connection succeeds — no scrolling needed. Hidden until then.
        self._next_btn = ctk.CTkButton(
            body, text=_("Далее →"), font=fonts.heading(), height=42,
            fg_color=p.ok, text_color=p.accent_fg, hover_color=p.accent_hover, command=self._proceed,
        )
        self._next_btn.grid(row=5, column=0, padx=32, pady=(0, 6), sticky="ew")
        self._next_btn.grid_remove()

        self._status = ctk.CTkLabel(
            body, text="", font=fonts.body(), text_color=p.text_muted, wraplength=560, justify="left"
        )
        self._status.grid(row=6, column=0, padx=32, sticky="w")

        # State panel (hidden until a successful connect).
        self._state_panel = ctk.CTkFrame(body, fg_color=p.surface, corner_radius=12)
        self._state_panel.grid(row=7, column=0, padx=32, pady=(10, 0), sticky="ew")
        self._state_panel.grid_columnconfigure(0, weight=1)
        self._state_panel.grid_remove()

        # Bottom bar: «Назад» on the left, a discreet «Удалить данные приложения»
        # on the right. The reset entry lives HERE (not only in Advanced) because
        # its whole point is cleaning up a borrowed/shared PC — where you may not
        # want to, or can't, connect to a router first. Shown only when there's
        # actually local data to wipe, so a clean install doesn't advertise it.
        bar = ctk.CTkFrame(body, fg_color="transparent")
        bar.grid(row=8, column=0, padx=32, pady=(12, 8), sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        if self._on_back is not None:
            ctk.CTkButton(
                bar,
                text=_("← Назад"),
                font=fonts.body(),
                fg_color="transparent",
                hover_color=p.surface_hover,
                width=80,
                command=self._on_back,
            ).grid(row=0, column=0, sticky="w")
        self._reset_btn = ctk.CTkButton(
            bar, text="🗑  " + _("Удалить данные приложения"), font=fonts.small(),
            fg_color="transparent", hover_color=p.surface_hover, text_color=p.text_muted,
            command=self._show_app_reset)
        self._reset_btn.grid(row=0, column=2, sticky="e")
        if not self._has_app_data():
            self._reset_btn.grid_remove()  # nothing stored — don't surface it

    # ----- app-data reset (local wipe; NOT the router) ------------------

    @staticmethod
    def _has_app_data() -> bool:
        """True if THIS machine holds anything worth wiping — saved router profiles
        or the app's SSH identity. Gates the reset entry so a fresh install is clean."""
        if app_profiles.list_profiles():
            return True
        return app_secrets.existing_public_key() is not None

    def _show_app_reset(self) -> None:
        """Pop a small dialog with the two-step red confirm, reusing Advanced's widget."""
        from .advanced_screen import _DangerConfirm  # lazy: avoid import-time engine load

        p = self.p
        win = ctk.CTkToplevel(self)
        win.title(_("Удалить данные приложения"))
        win.configure(fg_color=p.bg)
        win.geometry("640x440")
        win.minsize(560, 380)
        win.transient(self.winfo_toplevel())
        win.after(120, win.lift)

        body = ctk.CTkFrame(win, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=20)
        body.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(body, text=_("Удалить данные приложения (не роутера)"), font=fonts.title(),
                     text_color=p.text).grid(row=0, column=0, sticky="w", pady=(0, 8))
        ctk.CTkLabel(body, text=_("Стирает с ЭТОГО компьютера все данные Re:Sputnik: SSH-ключ "
                     "приложения, сохранённые пароли роутеров, привязки host-key и список "
                     "роутеров. Сам роутер и его настройки не трогаются. Используйте, чтобы "
                     "убрать за собой на чужом или общем компьютере."), font=fonts.body(),
                     text_color=p.text_muted, wraplength=580, justify="left",
                     anchor="w").grid(row=1, column=0, sticky="w", pady=(0, 12))
        box = ctk.CTkFrame(body, fg_color="transparent")
        box.grid(row=2, column=0, sticky="ew")
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

    def _do_app_reset(self, dc: "object") -> None:
        def done(_r: object) -> None:
            dc.set_status(_("Данные приложения удалены с этого компьютера. "
                          "Перезапустите Re:Sputnik."), self.p.ok)
            self._build_saved()  # registry now empty → the saved picker hides itself
            self._reset_btn.grid_remove()  # nothing left to wipe

        def err(e: BaseException) -> None:
            dc.reset()
            dc.set_status(_("Не удалось полностью удалить: {0}").format(e), self.p.fail)

        run_async(self, app_profiles.reset_app_data, done, err)

    def _field(
        self,
        master: ctk.CTkBaseClass,
        row: int,
        label: str,
        default: str,
        *,
        show: str = "",
        width: int = 0,
        placeholder: str = "",
    ) -> ctk.CTkEntry:
        ctk.CTkLabel(master, text=label, font=fonts.body(), text_color=self.p.text_muted).grid(
            row=row, column=0, padx=(16, 12), pady=8, sticky="w"
        )
        entry = ctk.CTkEntry(master, font=fonts.body(), show=show, fg_color=self.p.field_bg,
                             border_color=self.p.border, corner_radius=8,
                             placeholder_text_color=self.p.text_faint, placeholder_text=placeholder)
        if default:
            entry.insert(0, default)
        if width:
            entry.configure(width=width)
            entry.grid(row=row, column=1, padx=(0, 16), pady=8, sticky="w")
        else:
            entry.grid(row=row, column=1, padx=(0, 16), pady=8, sticky="ew")
        return entry

    # ----- saved routers ------------------------------------------------

    _SAVED_PLACEHOLDER = N_("— выбрать сохранённый —")

    def _build_saved(self) -> None:
        """(Re)build the saved-routers picker as a compact dropdown; hide when empty."""
        p = self.p
        for w in self._saved_card.winfo_children():
            w.destroy()
        profiles = app_profiles.list_profiles()
        if not profiles:
            self._saved_card.grid_remove()  # nothing saved yet — don't take space
            return
        self._saved_card.grid()
        self._saved_card.grid_columnconfigure(0, weight=0)
        self._saved_card.grid_columnconfigure(1, weight=1)  # the dropdown expands, not the label
        self._prof_by_label = {f"{pr.title}  ·  {pr.endpoint}": pr for pr in profiles}
        ctk.CTkLabel(self._saved_card, text=_("Сохранённые"), font=fonts.small(),
                     text_color=p.text_muted).grid(row=0, column=0, padx=(16, 12), pady=10, sticky="w")
        self._saved_menu = ctk.CTkOptionMenu(
            self._saved_card, values=[_(self._SAVED_PLACEHOLDER)] + list(self._prof_by_label),
            font=fonts.body(), fg_color=p.field_bg, button_color=p.accent,
            button_hover_color=p.accent_hover, dropdown_fg_color=p.surface,
            command=self._on_saved_pick)
        self._saved_menu.set(_(self._SAVED_PLACEHOLDER))
        self._saved_menu.grid(row=0, column=1, padx=(0, 8), pady=10, sticky="ew")
        ctk.CTkButton(self._saved_card, text="✕", width=32, font=fonts.body(),
                      fg_color="transparent", hover_color=p.fail, text_color=p.text_faint,
                      command=self._forget_selected).grid(row=0, column=2, padx=(0, 12))

    def _on_saved_pick(self, label: str) -> None:
        prof = getattr(self, "_prof_by_label", {}).get(label)
        if prof is not None:
            self._apply_profile(prof)

    def _forget_selected(self) -> None:
        prof = getattr(self, "_prof_by_label", {}).get(self._saved_menu.get())
        if prof is not None:
            self._forget_profile(prof)  # forget_profile rebuilds the picker

    def _apply_profile(self, prof: app_profiles.RouterProfile) -> None:
        """Fill the form from a saved profile + pull its password from the keychain."""
        for entry, value in ((self._ip, prof.host), (self._port, str(prof.port)),
                             (self._user, prof.user)):
            entry.delete(0, "end")
            entry.insert(0, value)
        self._password.delete(0, "end")
        pw = app_secrets.get_router_password(prof.host)
        if pw:
            self._password.insert(0, pw)
        self._set_status(_("Готово к подключению: {0}").format(prof.endpoint), "muted")

    def _forget_profile(self, prof: app_profiles.RouterProfile) -> None:
        app_profiles.forget_profile(prof.host, prof.port)  # also clears keychain secrets
        self._build_saved()
        self._set_status(_("Роутер {0} удалён из сохранённых.").format(prof.title), "muted")

    # ----- behavior -----------------------------------------------------

    def _fill_candidates(self, candidates: list[Candidate]) -> None:
        # "Найдено" should list only routers that actually answered. Drop the
        # unreachable probes (e.g. the default 192.168.1.1 when nothing's there) —
        # listing "192.168.1.1 — нет ответа" under "Найдено" is self-contradictory.
        # The address field keeps its manual default so it can still be tried by hand.
        reachable = [c for c in candidates if c.identity is not Identity.UNREACHABLE]
        self._candidates = reachable
        if not reachable:
            self._candidate_menu.configure(values=[_("— не найдено —")])
            self._candidate_menu.set(_("— не найдено —"))
            self._set_status(_("Роутер не найден автоматически — введите адрес вручную."), "warn")
            return

        labels = [c.label for c in reachable]
        self._candidate_menu.configure(values=labels)

        # Pre-select the first OpenWRT-identified candidate, else the first reachable one.
        chosen = next((c for c in reachable if c.is_openwrt), reachable[0])
        self._candidate_menu.set(chosen.label)
        self._apply_candidate(chosen)

        openwrt = [c for c in reachable if c.is_openwrt]
        if openwrt:
            c = openwrt[0]
            where = f"{c.hostname} ({c.ip})" if c.hostname else c.ip
            self._set_status(_("Найден OpenWrt: {0}").format(where), "ok")
        else:
            self._set_status(
                _("SSH отвечает, но баннер не OpenWrt — проверьте адрес или выберите кандидата."),
                "warn",
            )

    def _on_pick_candidate(self, label: str) -> None:
        for c in self._candidates:
            if c.label == label:
                self._apply_candidate(c)
                return

    def _apply_candidate(self, candidate: Candidate) -> None:
        self._ip.delete(0, "end")
        self._ip.insert(0, candidate.ip)
        self._port.delete(0, "end")
        self._port.insert(0, str(candidate.port))

    def _set_status(self, text: str, kind: str = "muted") -> None:
        color = {
            "muted": self.p.text_muted,
            "ok": self.p.ok,
            "warn": self.p.warn,
            "fail": self.p.fail,
        }[kind]
        self._status.configure(text=text, text_color=color)

    def _do_connect(self) -> None:
        if self._busy:
            return
        host = self._ip.get().strip()
        if not host:
            self._set_status(_("Укажите адрес роутера."), "fail")
            return
        try:
            port = int(self._port.get().strip() or "22")
        except ValueError:
            self._set_status(_("Порт должен быть числом."), "fail")
            return
        user = self._user.get().strip() or "root"
        password = self._password.get()

        self._busy = True
        self._pending = (host, port, user, password)
        self._connect_btn.configure(state="disabled", text=_("Подключение…"))
        self._next_btn.grid_remove()
        self._state_panel.grid_remove()
        self._set_status(_("Подключаюсь к {0}:{1}…").format(host, port), "muted")

        def task() -> tuple[RouterClient, RouterState, firmware.CompatReport]:
            pub = app_secrets.existing_public_key()
            # If our key is already installed (returning router) use it; otherwise
            # rely on the password. An EMPTY password is passed AS-IS so a fresh,
            # password-less OpenWrt root is actually reachable — `None` would make
            # paramiko skip password auth entirely.
            pkey = app_secrets.load_or_create_app_identity().pkey if pub else None
            pin = app_secrets.get_hostkey_pin(host)
            client = RouterClient(host, port=port, username=user, password=password,
                                  pkey=pkey, expected_fingerprint=pin)
            client.connect()  # may raise HostKeyMismatch
            fp = client.host_key_fingerprint
            if fp and not pin:
                app_secrets.pin_hostkey(host, fp)  # TOFU: pin on first sight
            state = detect_state(client, our_public_key=pub)
            report = firmware.check_compat(client)  # warn about broken firmware early
            if pub:
                key_lease.renew(client)  # bump the 1-year lease on every connect (best-effort)
            return client, state, report

        run_async(self, task, self._on_success, self._on_failure)

    def _on_failure(self, exc: BaseException) -> None:
        self._busy = False
        self._connect_btn.configure(state="normal", text=_("Подключиться"))
        if isinstance(exc, HostKeyMismatch):
            self._show_hostkey_mismatch(exc)
            return
        msg = str(exc) if isinstance(exc, RouterError) else _("Ошибка: {0}").format(exc)
        self._set_status(msg, "fail")

    def _show_hostkey_mismatch(self, exc: HostKeyMismatch) -> None:
        """Warn that the host key changed and let the user accept the new one."""
        p = self.p
        self._set_status(_("⚠ Отпечаток ключа роутера изменился."), "warn")
        for w in self._state_panel.winfo_children():
            w.destroy()
        self._state_panel.grid()
        self._state_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self._state_panel,
            text=_("Это нормально после сброса роутера к заводским настройкам, но также может "
            "означать подмену устройства в сети. Принимайте новый ключ, только если вы только "
            "что сбрасывали роутер."),
            font=fonts.small(), text_color=p.warn, wraplength=520, justify="left",
        ).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        ctk.CTkLabel(self._state_panel, text=_("Был:   {0}").format(exc.expected), font=fonts.small(),
                     text_color=p.text_muted, anchor="w").grid(row=1, column=0, padx=16, sticky="w")
        ctk.CTkLabel(self._state_panel, text=_("Стал:  {0}").format(exc.got), font=fonts.small(),
                     text_color=p.text, anchor="w").grid(row=2, column=0, padx=16, pady=(0, 8), sticky="w")
        btns = ctk.CTkFrame(self._state_panel, fg_color="transparent")
        btns.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(btns, text=_("Принять новый ключ"), font=fonts.body(), fg_color=p.warn,
                      hover_color=p.accent_hover, command=lambda: self._accept_new_key(exc)).grid(
            row=0, column=0, padx=(0, 8))
        ctk.CTkButton(btns, text=_("Отмена"), font=fonts.body(), fg_color="transparent",
                      hover_color=p.surface_hover, command=self._state_panel.grid_remove).grid(
            row=0, column=1)

    def _accept_new_key(self, exc: HostKeyMismatch) -> None:
        app_secrets.pin_hostkey(exc.host, exc.got)  # re-pin to the new key
        self._state_panel.grid_remove()
        self._set_status(_("Новый ключ принят. Переподключаюсь…"), "muted")
        self._do_connect()

    def _on_success(self, payload: tuple[RouterClient, RouterState, firmware.CompatReport]) -> None:
        client, state, report = payload
        self._busy = False
        self._connected = (client, state)
        self._connect_btn.configure(state="normal", text=_("Переподключиться"))
        self._set_status(_("Подключено."), "ok")
        # Remember this router for one-click reconnect next time (consented via the
        # checkbox). Non-secret metadata → profiles registry; password → keychain.
        if self._remember.get() == "1" and getattr(self, "_pending", None):
            host, port, user, password = self._pending
            app_profiles.save_profile(host, port, user)
            if password:
                app_secrets.store_router_password(host, password)
            self._build_saved()
        # A hard block (e.g. no nftables) means HomeProxy can't work — warn loudly
        # but don't trap: an exotic-yet-working firmware shouldn't be a dead end.
        if report.blocked:
            self._next_btn.configure(text=_("Всё равно продолжить →"), fg_color=self.p.fail)
        else:
            self._next_btn.configure(text=_("Далее →"), fg_color=self.p.ok)
        self._next_btn.grid()  # reveal under the connect button
        self._render_state(client, state)
        self._render_compat(report)

    def _proceed(self) -> None:
        if self._connected is not None:
            self._on_connected(*self._connected)

    def _render_state(self, client: RouterClient, state: RouterState) -> None:
        p = self.p
        for w in self._state_panel.winfo_children():
            w.destroy()
        self._state_panel.grid()

        readiness = {
            "clean": (_("Чистый роутер — потребуется полная настройка"), p.warn),
            "partial": (_("ПО установлено, нужна настройка серверов"), p.warn),
            "configured": (_("Роутер уже настроен — режим управления"), p.ok),
        }[state.readiness.value]

        # Keep it focused on what matters at connect time; tech details (package
        # manager, core, free space, key fingerprint) live in Core/Diagnostics.
        rows = [
            ("OpenWrt", (state.openwrt_version or _("не определён")) + (f" · {state.board}" if state.board else ""), p.text),
            ("Re:HomeProxy", _("установлен") if state.homeproxy_installed else _("не установлен"),
             p.ok if state.homeproxy_installed else p.text_muted),
            (_("Состояние"), readiness[0], readiness[1]),
        ]
        for i, (label, value, color) in enumerate(rows):
            ctk.CTkLabel(self._state_panel, text=label, font=fonts.small(), text_color=p.text_muted).grid(
                row=i, column=0, padx=(16, 12), pady=6, sticky="w"
            )
            ctk.CTkLabel(self._state_panel, text=value, font=fonts.body(), text_color=color, anchor="e").grid(
                row=i, column=1, padx=(0, 16), pady=6, sticky="e"
            )
        self._state_panel.grid_columnconfigure(1, weight=1)
        self._compat_base_row = len(rows)  # firmware warnings append below the state

    def _render_compat(self, report: firmware.CompatReport) -> None:
        """Append firmware-compatibility warnings/blocks under the state panel."""
        if not report.issues:
            return
        p = self.p
        r = getattr(self, "_compat_base_row", 3)
        ctk.CTkLabel(self._state_panel, text=_("Совместимость прошивки"), font=fonts.small(),
                     text_color=p.text_muted).grid(
            row=r, column=0, columnspan=2, padx=16, pady=(10, 2), sticky="w")
        r += 1
        for issue in report.issues:
            blocked = issue.severity == firmware.BLOCK
            color = p.fail if blocked else p.warn
            icon = "⛔" if blocked else "⚠"
            ctk.CTkLabel(self._state_panel, text=f"{icon}  {issue.title}", font=fonts.body(),
                         text_color=color, anchor="w", wraplength=500, justify="left").grid(
                row=r, column=0, columnspan=2, padx=16, sticky="w")
            r += 1
            detail = issue.detail + (_("\nРешение: {0}").format(issue.fix) if issue.fix else "")
            ctk.CTkLabel(self._state_panel, text=detail, font=fonts.small(),
                         text_color=p.text_muted, anchor="w", wraplength=500, justify="left").grid(
                row=r, column=0, columnspan=2, padx=16, pady=(0, 6), sticky="w")
            r += 1
