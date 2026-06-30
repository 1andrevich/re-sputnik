# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Phase 1 — first-run setup screen (consent UI).

Shows exactly what will change on the router (install SSH key, set root
password) and asks for explicit consent via the Apply button. Password defaults
to a generated max-entropy value; the user may supply their own. All device work
runs off the UI thread.

Laid out on the shared Quick Setup chrome (kit.WizardScaffold) — titlebar band,
9-step strip, scrolling content, footer action bar.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from .. import secrets as app_secrets
from ..engine import FirstRunPlan, FirstRunResult, apply_firstrun
from ..router import RouterClient, RouterState
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import _

OnDone = Callable[[RouterClient, RouterState], None]
OnBack = Callable[[], None]


class FirstRunScreen(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        palette: Palette,
        client: RouterClient,
        state: RouterState,
        *,
        on_done: OnDone,
        on_back: Optional[OnBack] = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._state = state
        self._on_done = on_done
        self._on_back = on_back
        self._busy = False
        self._pw_mode = ctk.StringVar(value="random")
        self._remember = ctk.StringVar(value="1")  # install permanent SSH key
        self._build()

    # ----- layout -------------------------------------------------------

    def _build(self) -> None:
        p = self.p
        self._sc = kit.WizardScaffold(self, p, step=1, label=_("Безопасность"))
        body = self._sc.content

        ctk.CTkLabel(
            body, text=_("Приложение внесёт изменения на роутер. Просмотрите и подтвердите."),
            font=fonts.body(), text_color=p.text_muted, wraplength=620, justify="left",
        ).grid(row=0, column=0, padx=28, pady=(16, 12), sticky="w")

        # SSH key card (informational — required for safe, password-less access).
        keycard = kit.Card(body, p)
        keycard.grid(row=1, column=0, padx=28, pady=(0, 12), sticky="ew")
        keycard.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(keycard, p, "ssh", _("SSH-ключ доступа")).grid(
            row=0, column=0, padx=16, pady=(14, 2), sticky="w")
        ctk.CTkLabel(
            keycard,
            text=_("Ключ приложения позволяет входить без пароля. Сначала ставим ключ и "
            "проверяем его, и только потом меняем пароль — так доступ не потеряется."),
            font=fonts.small(), text_color=p.text_muted, wraplength=600, justify="left",
        ).grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        kit.check(
            keycard, p, _("Запомнить это устройство — установить постоянный ключ (вход без пароля)"),
            variable=self._remember, onvalue="1", offvalue="0", command=self._on_remember,
        ).grid(row=2, column=0, padx=16, pady=(0, 6), sticky="w")
        self._remember_note = ctk.CTkLabel(
            keycard, text="", font=fonts.small(), text_color=p.warn, wraplength=600, justify="left")
        self._remember_note.grid(row=3, column=0, padx=16, pady=(0, 14), sticky="w")

        # If root already has a password, never offer to change it.
        self._has_pw_card = not self._state.root_has_password
        if not self._has_pw_card:
            existing = kit.Card(body, p)
            existing.grid(row=2, column=0, padx=28, pady=(0, 12), sticky="ew")
            existing.grid_columnconfigure(0, weight=1)
            kit.SectionHeader(existing, p, "password", _("Пароль root")).grid(
                row=0, column=0, padx=16, pady=(14, 2), sticky="w")
            ctk.CTkLabel(
                existing, text=_("Пароль уже задан на роутере — оставляем без изменений."),
                font=fonts.small(), text_color=p.text_muted, wraplength=600, justify="left",
            ).grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")
            self._build_status(body, row=3)
            self._setup_footer()
            return

        # Password card.
        pwcard = kit.Card(body, p)
        pwcard.grid(row=2, column=0, padx=28, pady=(0, 12), sticky="ew")
        pwcard.grid_columnconfigure(1, weight=1)
        kit.SectionHeader(pwcard, p, "password", _("Пароль root")).grid(
            row=0, column=0, columnspan=2, padx=16, pady=(14, 6), sticky="w")

        kit.radio(pwcard, p, _("Сгенерировать надёжный (рекомендуется)"), value="random",
                  variable=self._pw_mode, command=self._on_pw_mode).grid(
            row=1, column=0, columnspan=2, padx=16, pady=4, sticky="w")

        self._pw_entry = kit.field(pwcard, p, mono=True)
        self._pw_entry.grid(row=2, column=0, columnspan=2, padx=(40, 16), pady=4, sticky="ew")
        links = ctk.CTkFrame(pwcard, fg_color="transparent")
        links.grid(row=3, column=0, columnspan=2, padx=(40, 16), pady=(0, 4), sticky="w")
        self._regen_btn = kit.link_button(links, p, _("↻ Сгенерировать заново"), self._regen, accent=True)
        self._regen_btn.pack(side="left", padx=(0, 14))
        self._copy_btn = kit.link_button(links, p, _("Копировать"), self._copy_pw, accent=True)
        self._copy_btn.pack(side="left")

        kit.radio(pwcard, p, _("Задать свой пароль"), value="own",
                  variable=self._pw_mode, command=self._on_pw_mode).grid(
            row=4, column=0, columnspan=2, padx=16, pady=(8, 4), sticky="w")

        # Dedicated input for a user-supplied password (separate from the generated
        # field above, so it's obvious where to type). Active only in "own" mode.
        self._own_entry = kit.field(pwcard, p, placeholder=_("Введите свой пароль (минимум 8 символов)"))
        self._own_entry.grid(row=5, column=0, columnspan=2, padx=(40, 16), pady=4, sticky="ew")
        # Allow only English-layout (ASCII) characters into the password fields;
        # a Cyrillic/other layout is blocked at the keystroke (digits still pass).
        _vcmd = (self.register(app_secrets.is_password_input_char), "%P")
        for _e in (self._pw_entry, self._own_entry):
            _e.configure(validate="key", validatecommand=_vcmd)
        self._own_show = kit.check(pwcard, p, _("Показать пароль"), command=self._toggle_own_show)
        self._own_show.grid(row=6, column=0, columnspan=2, padx=(40, 16), pady=(0, 4), sticky="w")

        ctk.CTkLabel(
            pwcard,
            text=_("Любой пароль — сгенерированный или ваш — сохраняется в хранилище Windows "
            "(Credential Manager) и доступен в разделе «Безопасность»."),
            font=fonts.small(), text_color=p.text_muted, wraplength=600, justify="left",
        ).grid(row=7, column=0, columnspan=2, padx=16, pady=(2, 14), sticky="w")

        self._build_status(body, row=3)
        self._setup_footer()
        self._regen()  # seed a generated password
        self._on_pw_mode()

    def _build_status(self, body: ctk.CTkBaseClass, row: int) -> None:
        self._status = ctk.CTkLabel(
            body, text="", font=fonts.body(), text_color=self.p.text_muted,
            wraplength=620, justify="left")
        self._status.grid(row=row, column=0, padx=28, pady=(0, 10), sticky="w")

    def _setup_footer(self) -> None:
        self._apply_btn = self._sc.footer.set_primary(_("Применить"), self._apply)
        if self._on_back is not None:
            self._sc.footer.set_link(_("← Назад"), self._on_back)

    def _on_remember(self) -> None:
        if self._remember.get() == "1":
            self._remember_note.configure(text="")
        else:
            self._remember_note.configure(
                text=_("Без ключа каждое подключение будет запрашивать пароль root "
                     "(он сохранится в хранилище — посмотреть можно в разделе «Безопасность»)."))

    # ----- password mode ------------------------------------------------

    def _on_pw_mode(self) -> None:
        random_mode = self._pw_mode.get() == "random"
        # Generated-password controls: live only in "random" mode.
        for w in (self._regen_btn, self._copy_btn, self._pw_entry):
            w.configure(state="normal" if random_mode else "disabled")
        if random_mode and not self._pw_entry.get():
            self._regen()
        # Own-password field: live only in "own" mode.
        self._own_entry.configure(state="normal" if not random_mode else "disabled")
        self._own_show.configure(state="normal" if not random_mode else "disabled")
        self._own_entry.configure(show="" if self._own_show.get() else "•")
        if not random_mode:
            self._own_entry.focus_set()

    def _toggle_own_show(self) -> None:
        self._own_entry.configure(show="" if self._own_show.get() else "•")

    def _regen(self) -> None:
        self._pw_entry.delete(0, "end")
        self._pw_entry.insert(0, app_secrets.generate_password())

    def _copy_pw(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._pw_entry.get())
        self._set_status(_("Пароль скопирован в буфер обмена."), "muted")

    # ----- apply --------------------------------------------------------

    def _set_status(self, text: str, kind: str = "muted") -> None:
        color = {"muted": self.p.text_muted, "ok": self.p.ok,
                 "warn": self.p.warn, "fail": self.p.fail}[kind]
        self._status.configure(text=text, text_color=color)

    def _apply(self) -> None:
        if self._busy:
            return
        install_key = self._remember.get() == "1"
        if not install_key and not self._has_pw_card:
            # Nothing to do: no key, and the password already exists / isn't changed.
            self._set_status(_("Ничего менять не нужно — ключ не ставим, пароль уже задан."), "warn")
            self._apply_btn.configure(text=_("Далее →"), fg_color=self.p.ok,
                                      hover_color=self.p.accent_hover,
                                      command=lambda: self._on_done(self._client, self._state))
            return
        if self._has_pw_card:
            own_mode = self._pw_mode.get() == "own"
            password = (self._own_entry if own_mode else self._pw_entry).get().strip()
            if not password:
                self._set_status(_("Введите пароль или выберите генерацию."), "fail")
                return
            if len(password) < 8:
                self._set_status(_("Пароль слишком короткий (минимум 8 символов)."), "fail")
                return
            problem = app_secrets.password_problem(password)
            if problem:
                self._set_status(problem, "fail")
                return
            # Always store the password (it's the recovery path, especially when
            # no key is installed) — see the Security screen to view it later.
            plan = FirstRunPlan(install_key=install_key, set_password=True, password=password,
                                store_in_keychain=True)
        else:
            # Root already has a password — install the key only.
            plan = FirstRunPlan(install_key=install_key, set_password=False, password="",
                                store_in_keychain=False)
        self._busy = True
        self._apply_btn.configure(state="disabled", text=_("Применяю…"))
        self._set_status(_("Устанавливаю ключ и пароль…"), "muted")

        client = self._client

        def task() -> FirstRunResult:
            return apply_firstrun(client, plan)

        run_async(self, task, self._on_result, self._on_error)

    def _on_error(self, exc: BaseException) -> None:
        self._busy = False
        self._apply_btn.configure(state="normal", text=_("Применить"))
        self._set_status(_("Ошибка: {0}").format(exc), "fail")

    def _on_result(self, result: FirstRunResult) -> None:
        self._busy = False
        self._apply_btn.configure(state="normal", text=_("Применить"))
        if not result.ok:
            self._set_status(result.error or _("Не удалось завершить настройку."), "fail")
            return
        bits = [_("ключ установлен")] if result.key_installed else [_("без постоянного ключа")]
        if result.password_set:
            bits.append(_("пароль изменён"))
        if result.password_stored:
            bits.append(_("сохранён в хранилище"))
        self._set_status(_("Готово: ") + ", ".join(bits) + ".", "ok")
        # Switch from the blue "Применить" action to a GREEN "Далее →" — matches the
        # proceed button on the other wizard steps (software/wifi/rules/connect use
        # palette.ok), so a completed step reads as done rather than another action.
        self._apply_btn.configure(text=_("Далее →"), fg_color=self.p.ok,
                                  hover_color=self.p.accent_hover, state="normal",
                                  command=lambda: self._on_done(self._client, self._state))
