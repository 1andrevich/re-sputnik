# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Router admin security — who can log into the ROUTER.

Lists the SSH keys in dropbear's authorized_keys (flagging the one belonging to
this app/device), lets the user revoke any single key or all of them, and lets
them set the root password. Both matter: revoking keys without changing the
password is incomplete, since password login lets anyone re-add a key. All SSH
work runs off the Tk thread.
"""

from __future__ import annotations

from typing import Callable, Optional

import customtkinter as ctk

from .. import secrets as app_secrets
from ..engine import router_security as rsec
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import _

OnBack = Callable[[], None]


class SecurityScreen(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        palette: Palette,
        client: RouterClient,
        *,
        on_back: Optional[OnBack] = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_back = on_back
        self._keys: list[rsec.AuthKey] = []
        self._revoke_all_armed = False
        self._pw_visible = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=2, column=0, padx=24, pady=(0, 16), sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)
        self.refresh()

    # ----- header -------------------------------------------------------

    def _build_header(self) -> None:
        p = self.p
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, padx=24, pady=(20, 4), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text=_("Безопасность"), font=fonts.title(), text_color=p.text,
                     image=kit.icon(kit.ICON_FOR["security"], 26), compound="left").grid(
            row=0, column=0, sticky="w"
        )
        self._refresh_btn = ctk.CTkButton(
            bar, text=_("{0} Обновить страницу").format(kit.REFRESH_GLYPH), font=fonts.body(), width=180,
            fg_color=p.surface, hover_color=p.surface_hover, command=self.refresh,
        )
        self._refresh_btn.grid(row=0, column=1)

        self._status = ctk.CTkLabel(self, text="", font=fonts.small(), text_color=p.text_muted,
                                    anchor="w", wraplength=620, justify="left")
        self._status.grid(row=1, column=0, padx=24, sticky="ew")

    def _set_status(self, text: str, color: Optional[str] = None) -> None:
        self._status.configure(text=text, text_color=color or self.p.text_muted)

    # ----- refresh ------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_btn.configure(state="disabled", text="…")
        self._set_status(_("Читаю ключи доступа на роутере…"))
        client = self._client
        app_pub = app_secrets.existing_public_key()

        def task() -> list[rsec.AuthKey]:
            return rsec.list_keys(client, app_public=app_pub)

        run_async(self, task, self._render, self._on_error)

    def _on_error(self, exc: BaseException) -> None:
        self._refresh_btn.configure(state="normal", text=_("{0} Обновить страницу").format(kit.REFRESH_GLYPH))
        self._set_status(_("Ошибка: {0}").format(exc), self.p.fail)

    # ----- rendering ----------------------------------------------------

    def _render(self, keys: list[rsec.AuthKey]) -> None:
        self._keys = keys
        self._refresh_btn.configure(state="normal", text=_("{0} Обновить страницу").format(kit.REFRESH_GLYPH))
        self._set_status("")
        for w in self._body.winfo_children():
            w.destroy()

        row = 0
        row = self._render_intro(row)
        row = self._render_keys(row)
        row = self._render_stored_password(row)
        row = self._render_password(row)

        if self._on_back is not None:
            ctk.CTkButton(
                self._body, text=_("← Назад"), font=fonts.body(), fg_color="transparent",
                hover_color=self.p.surface_hover, width=90, command=self._on_back,
            ).grid(row=row, column=0, pady=(8, 8), sticky="w")

    def _card(self, title: str, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self._body, fg_color=self.p.surface, corner_radius=12)
        card.grid(row=row, column=0, pady=(0, 12), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=fonts.heading(), text_color=self.p.text).grid(
            row=0, column=0, padx=16, pady=(12, 6), sticky="w"
        )
        return card

    def _render_intro(self, row: int) -> int:
        card = ctk.CTkFrame(self._body, fg_color="transparent")
        card.grid(row=row, column=0, pady=(0, 4), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=_("Доступ к управлению роутером дают SSH-ключи и пароль root. "
                 "Чтобы полностью закрыть доступ, отзовите лишние ключи и смените "
                 "пароль — иначе вход по паролю позволит прописать новый ключ."),
            font=fonts.body(), text_color=self.p.text_muted, anchor="w",
            justify="left", wraplength=620,
        ).grid(row=0, column=0, sticky="ew")
        return row + 1

    # ----- keys ---------------------------------------------------------

    def _render_keys(self, row: int) -> int:
        card = self._card(_("SSH-ключи доступа"), row)
        if not self._keys:
            ctk.CTkLabel(card, text=_("Ключей нет — вход только по паролю."), font=fonts.body(),
                         text_color=self.p.text_muted, anchor="w").grid(
                row=1, column=0, padx=16, pady=(0, 12), sticky="w")
            return row + 1

        wrap = ctk.CTkFrame(card, fg_color="transparent")
        wrap.grid(row=1, column=0, padx=12, pady=(0, 8), sticky="ew")
        wrap.grid_columnconfigure(0, weight=1)
        for i, key in enumerate(self._keys):
            self._render_key_row(wrap, i, key)

        # Revoke-all (two-click confirm).
        self._revoke_all_btn = ctk.CTkButton(
            card, text=_("Отозвать все ключи"), font=fonts.small(), width=160,
            fg_color="transparent", hover_color=self.p.surface_hover,
            text_color=self.p.fail, command=self._on_revoke_all,
        )
        self._revoke_all_btn.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="w")
        return row + 1

    def _render_key_row(self, parent: ctk.CTkBaseClass, i: int, key: rsec.AuthKey) -> None:
        rowf = ctk.CTkFrame(parent, fg_color=self.p.bg, corner_radius=8)
        rowf.grid(row=i, column=0, pady=3, sticky="ew")
        rowf.grid_columnconfigure(0, weight=1)

        info = ctk.CTkFrame(rowf, fg_color="transparent")
        info.grid(row=0, column=0, padx=12, pady=8, sticky="ew")
        info.grid_columnconfigure(0, weight=1)

        title = key.type
        if key.comment:
            title += f"  ·  {key.comment}"
        line = ctk.CTkFrame(info, fg_color="transparent")
        line.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(line, text=title, font=fonts.body(), text_color=self.p.text,
                     anchor="w").grid(row=0, column=0, sticky="w")
        if key.is_app:
            ctk.CTkLabel(line, text=_("● это устройство"), font=fonts.small(),
                         text_color=self.p.accent).grid(row=0, column=1, padx=(10, 0))
        ctk.CTkLabel(info, text=key.fingerprint, font=fonts.mono(11),
                     text_color=self.p.text_muted, anchor="w").grid(row=1, column=0, sticky="w")

        btn = ctk.CTkButton(
            rowf, text=_("Отозвать"), font=fonts.small(), width=90,
            fg_color="transparent", hover_color=self.p.surface_hover, text_color=self.p.fail,
            command=lambda k=key: self._on_revoke_one(k),
        )
        btn.grid(row=0, column=1, padx=(0, 10))

    def _on_revoke_one(self, key: rsec.AuthKey) -> None:
        self._set_busy(True)
        warn = _("  Это ключ ТЕКУЩЕГО устройства — приложение потеряет доступ по ключу.") if key.is_app else ""
        self._set_status(_("Отзываю ключ…") + warn, self.p.warn if key.is_app else None)
        client = self._client
        is_app = key.is_app
        line = key.line

        def task() -> bool:
            removed = rsec.revoke_key(client, line)
            if removed and is_app:
                # The app's own key no longer works on THIS router — forget the
                # pin so the next connect falls back to password auth cleanly.
                app_secrets.forget_hostkey(client.host)
            return removed

        run_async(self, task,
                  lambda removed: self._after_revoke(removed, is_app),
                  self._action_err)

    def _after_revoke(self, removed: bool, was_app: bool) -> None:
        if removed and was_app:
            self._set_status(_("Ключ устройства отозван — следующее подключение потребует пароль."),
                             self.p.warn)
        elif removed:
            self._set_status(_("Ключ отозван."), self.p.ok)
        else:
            self._set_status(_("Ключ не найден (уже удалён?)."), self.p.text_muted)
        self.refresh()

    def _on_revoke_all(self) -> None:
        if not self._revoke_all_armed:
            self._revoke_all_armed = True
            self._revoke_all_btn.configure(
                text=_("Точно? Ещё раз — будут удалены ВСЕ ключи, включая ключ этого устройства"))
            return
        self._revoke_all_armed = False
        self._set_busy(True)
        self._set_status(_("Отзываю все ключи…"), self.p.warn)
        client = self._client

        def task() -> int:
            n = rsec.revoke_all_keys(client)
            app_secrets.forget_hostkey(client.host)
            return n

        run_async(self, task, self._after_revoke_all, self._action_err)

    def _after_revoke_all(self, n: int) -> None:
        self._set_status(
            _("Удалено ключей: {0}. Вход теперь только по паролю — убедитесь, что он надёжный.").format(n),
            self.p.warn if n else self.p.text_muted)
        self.refresh()

    # ----- stored password (recover a forgotten one) --------------------

    def _render_stored_password(self, row: int) -> int:
        try:
            pw = app_secrets.get_router_password(self._client.host)
        except Exception:  # noqa: BLE001 — keychain unavailable; just skip
            pw = None
        if not pw:
            return row  # nothing stored — no card
        p = self.p
        self._stored_pw = pw
        self._stored_visible = False
        card = self._card(_("Текущий пароль root (сохранён приложением)"), row)
        ctk.CTkLabel(card, text=_("Если вы его забыли — откройте глазом и скопируйте."),
                     font=fonts.small(), text_color=p.text_muted, anchor="w").grid(
            row=1, column=0, padx=16, pady=(0, 6), sticky="w")
        rowf = ctk.CTkFrame(card, fg_color="transparent")
        rowf.grid(row=2, column=0, padx=16, pady=(0, 12), sticky="ew")
        rowf.grid_columnconfigure(0, weight=1)
        self._stored_entry = ctk.CTkEntry(rowf, font=fonts.mono(13), show="•")
        self._stored_entry.insert(0, pw)
        self._stored_entry.configure(state="readonly")
        self._stored_entry.grid(row=0, column=0, sticky="ew")
        ctk.CTkButton(rowf, text="👁", width=40, font=fonts.body(), fg_color=p.surface_hover,
                      hover_color=p.border, command=self._toggle_stored).grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(rowf, text=_("Копировать"), width=110, font=fonts.small(), fg_color=p.surface_hover,
                      hover_color=p.border, command=self._copy_stored).grid(row=0, column=2, padx=(6, 0))
        return row + 1

    def _toggle_stored(self) -> None:
        self._stored_visible = not self._stored_visible
        self._stored_entry.configure(show="" if self._stored_visible else "•")

    def _copy_stored(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._stored_pw)
        self._set_status(_("Пароль скопирован в буфер обмена."), self.p.ok)

    # ----- root password ------------------------------------------------

    def _render_password(self, row: int) -> int:
        p = self.p
        card = self._card(_("Пароль root"), row)
        ctk.CTkLabel(
            card, text=_("Задайте надёжный случайный пароль администратора роутера."),
            font=fonts.small(), text_color=p.text_muted, anchor="w").grid(
            row=1, column=0, padx=16, pady=(0, 8), sticky="w")

        rowf = ctk.CTkFrame(card, fg_color="transparent")
        rowf.grid(row=2, column=0, padx=16, pady=(0, 6), sticky="ew")
        rowf.grid_columnconfigure(0, weight=1)
        self._pw_entry = ctk.CTkEntry(rowf, font=fonts.body(), show="•",
                                      placeholder_text=_("новый пароль root"),
                                      validate="key",
                                      validatecommand=(self.register(
                                          app_secrets.is_password_input_char), "%P"))
        self._pw_entry.grid(row=0, column=0, sticky="ew")
        self._pw_eye = ctk.CTkButton(rowf, text="👁", font=fonts.body(), width=40,
                                     fg_color=p.surface_hover, hover_color=p.border,
                                     command=self._toggle_pw)
        self._pw_eye.grid(row=0, column=1, padx=(6, 0))
        ctk.CTkButton(rowf, text=_("Сгенерировать"), font=fonts.small(), width=120,
                      fg_color=p.surface_hover, hover_color=p.border,
                      command=self._gen_pw).grid(row=0, column=2, padx=(6, 0))

        self._pw_store = ctk.CTkCheckBox(card, text=_("Сохранить в хранилище приложения"),
                                         font=fonts.small(), text_color=p.text_muted)
        self._pw_store.select()
        self._pw_store.grid(row=3, column=0, padx=16, pady=(2, 8), sticky="w")

        self._pw_btn = ctk.CTkButton(card, text=_("Установить пароль"), font=fonts.body(), width=160,
                                     fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                                     command=self._on_set_pw)
        self._pw_btn.grid(row=4, column=0, padx=16, pady=(0, 14), sticky="w")
        return row + 1

    def _toggle_pw(self) -> None:
        self._pw_visible = not self._pw_visible
        self._pw_entry.configure(show="" if self._pw_visible else "•")

    def _gen_pw(self) -> None:
        pw = app_secrets.generate_password()
        self._pw_entry.delete(0, "end")
        self._pw_entry.insert(0, pw)
        if not self._pw_visible:
            self._toggle_pw()

    def _on_set_pw(self) -> None:
        pw = self._pw_entry.get()
        if len(pw) < 8:
            self._set_status(_("Пароль слишком короткий (минимум 8 символов)."), self.p.fail)
            return
        problem = app_secrets.password_problem(pw)
        if problem:
            self._set_status(problem, self.p.fail)
            return
        self._set_busy(True)
        self._pw_btn.configure(state="disabled", text=_("Устанавливаю…"))
        self._set_status(_("Меняю пароль root…"))
        client = self._client
        store = bool(self._pw_store.get())

        def task() -> None:
            rsec.set_root_password(client, pw)
            if store:
                app_secrets.store_router_password(client.host, pw)

        run_async(self, task, lambda _r: self._after_set_pw(store), self._pw_err)

    def _after_set_pw(self, stored: bool) -> None:
        self._pw_btn.configure(state="normal", text=_("Установить пароль"))
        self._pw_entry.delete(0, "end")
        if self._pw_visible:
            self._toggle_pw()
        tail = _(" и сохранён в приложении.") if stored else "."
        self._set_status(_("Пароль root изменён") + tail, self.p.ok)

    def _pw_err(self, exc: BaseException) -> None:
        self._pw_btn.configure(state="normal", text=_("Установить пароль"))
        self._set_status(_("Не удалось сменить пароль: {0}").format(exc), self.p.fail)

    # ----- shared -------------------------------------------------------

    def _set_busy(self, busy: bool) -> None:
        self._refresh_btn.configure(state="disabled" if busy else "normal")

    def _action_err(self, exc: BaseException) -> None:
        self._set_status(_("Ошибка: {0}").format(exc), self.p.fail)
        self.refresh()
