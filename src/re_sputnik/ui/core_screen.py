# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Core settings section — pick the active core + show "Управление ядром" info.

Scope: select which INSTALLED core is active (uci ``preferred_core``) and show
read-only environment facts (package manager, arch, free space, versions).
Installing a NEW core is the multi-step core_mgmt.uc flow and belongs to the
Quick-Setup software phase — surfaced here only as a note, not performed.

Changing the active core requires a config regenerate + service restart to take
effect (generate_client.uc mirrors preferred_core), so we set the value and
offer a deliberate restart rather than doing it silently.
"""

from __future__ import annotations

from typing import Any, Optional

import customtkinter as ctk

from ..engine import byedpi as bd
from ..engine import core_health, install_app, preinstall
from ..engine import zapret as zp
from ..router import RouterClient, RouterState
from . import kit
from .theme import Palette, fonts
from .worker import post_to, run_async
from ..i18n import N_, _, luci_lang

# uci preferred_core value -> display label + one-line protocol difference.
# Shared source of truth for the core captions — also used on the Quick-Setup
# software step (software_screen) so both screens read identically.
CORE_OPTIONS = [
    ("hiddify", "hiddify-core",
     N_("Если пользуетесь приложением Hiddify — поддержка всех его протоколов. Не поддерживает AmneziaWG.")),
    ("singbox", "sing-box-extended",
     N_("Если нужен AmneziaWG и все протоколы sing-box: VLESS, Hysteria2, Mieru, TrustTunnel.")),
]


def _clean_version(v: str) -> str:
    """Pull a readable version from a noisy core version string (build tags etc.)."""
    import re

    if not v:
        return "—"
    m = re.search(r"\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?", v)
    if m:
        return m.group(0)
    first = v.splitlines()[0].strip()
    return first[:24] or "—"


class CoreScreen(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        palette: Palette,
        client: RouterClient,
        state: RouterState,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._state = state
        self._core_info: dict[str, Any] = {}
        self._choice = ctk.StringVar(value=state.preferred_core or "")
        self._busy = False  # an install/update is running — gate the action buttons

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=0, column=0, padx=24, pady=16, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)

        self._build_static()
        # Re-wrap text to the real card width on resize, so long hints/notes never
        # push the card past the viewport (which clipped them on the right).
        self._body.bind("<Configure>", self._on_resize)
        self._load_core_info()
        self._load_app_version()
        self._load_tools()

    # ----- layout -------------------------------------------------------

    def _build_static(self) -> None:
        p = self.p
        ctk.CTkLabel(self._body, text=_("Ядро"), font=fonts.title(), text_color=p.text,
                     image=kit.icon(kit._ICON_FOR["core"], 26), compound="left").grid(
            row=0, column=0, pady=(4, 12), sticky="w"
        )
        self._status = ctk.CTkLabel(
            self._body, text=_("Считываю состояние ядра…"), font=fonts.small(),
            text_color=p.text_muted, anchor="w",
        )
        self._status.grid(row=1, column=0, sticky="w", pady=(0, 8))

        # Config-error explainer card — hidden unless the core won't start because
        # of a bad node. Names the offending server so the user can remove it.
        self._fail_card = ctk.CTkFrame(self._body, fg_color=p.surface, corner_radius=12,
                                       border_width=1, border_color=p.warn)
        self._fail_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._fail_card.grid_columnconfigure(0, weight=1)
        self._fail_lbl = ctk.CTkLabel(self._fail_card, text="", font=fonts.small(),
                                      text_color=p.warn, anchor="w", justify="left", wraplength=560)
        self._fail_lbl.grid(row=0, column=0, padx=16, pady=12, sticky="w")
        self._fail_card.grid_remove()

        # Active-core selection card.
        self._sel_card = ctk.CTkFrame(self._body, fg_color=p.surface, corner_radius=12)
        self._sel_card.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self._sel_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self._sel_card, text=_("Активное ядро"), font=fonts.heading(), text_color=p.text
        ).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        self._radios: dict[str, ctk.CTkRadioButton] = {}
        self._radio_hints: dict[str, ctk.CTkLabel] = {}
        self._core_btns: dict[str, ctk.CTkButton] = {}
        for i, (key, label, sub) in enumerate(CORE_OPTIONS, start=1):
            rb = ctk.CTkRadioButton(
                self._sel_card, text=label, value=key, variable=self._choice,
                font=fonts.body(), fg_color=p.accent, hover_color=p.accent_hover,
                command=self._on_pick, state="disabled",  # enabled in _render_info once loaded
            )
            rb.grid(row=i * 2 - 1, column=0, padx=16, pady=(8, 0), sticky="w")
            # wraplength bounds the column-0 width so the text wraps instead of
            # forcing the card wider than the viewport (the action button sits in
            # column 1, so unbounded text would push everything off the right edge).
            hint = ctk.CTkLabel(self._sel_card, text=_(sub), font=fonts.small(),
                                text_color=p.text_muted, wraplength=300, justify="left")
            hint.grid(row=i * 2, column=0, padx=(40, 16), pady=(0, 2), sticky="w")
            # Per-core action: "Установить" (if missing) / "Обновить до последней"
            # (if installed) — text/colour set in _render_info once we know the state.
            btn = ctk.CTkButton(
                self._sel_card, text="…", font=fonts.small(), width=190, height=30,
                state="disabled", command=lambda k=key: self._core_action(k))
            btn.grid(row=i * 2 - 1, column=1, rowspan=2, padx=(8, 16), sticky="e")
            self._radios[key] = rb
            self._radio_hints[key] = hint
            self._core_btns[key] = btn

        self._warn_lbl = ctk.CTkLabel(
            self._sel_card,
            text=_("⚠ Выбор серверов зависит от ядра (матрица совместимости протоколов). "
            "Смена ядра применяется после перезапуска сервиса."),
            font=fonts.small(), text_color=p.warn, wraplength=520, justify="left")
        # span both columns: this row has no action button, so it gets full width.
        self._warn_lbl.grid(row=len(CORE_OPTIONS) * 2 + 1, column=0, columnspan=2,
                            padx=16, pady=(6, 4), sticky="w")

        self._apply_row = ctk.CTkFrame(self._sel_card, fg_color="transparent")
        self._apply_row.grid(row=len(CORE_OPTIONS) * 2 + 2, column=0, columnspan=2,
                             padx=16, pady=(0, 12), sticky="w")
        self._restart_btn = ctk.CTkButton(
            self._apply_row, text=_("Применить изменения"), font=fonts.body(), width=200,
            fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover, command=self._restart, state="disabled",
        )
        self._restart_btn.grid(row=0, column=0)
        self._apply_note = ctk.CTkLabel(self._apply_row, text="", font=fonts.small(), text_color=p.text_muted)
        self._apply_note.grid(row=0, column=1, padx=10)

        # App (luci-app-re-homeproxy) update card.
        self._app_card = ctk.CTkFrame(self._body, fg_color=p.surface, corner_radius=12)
        self._app_card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        self._app_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._app_card, text=_("Приложение Re:HomeProxy"), font=fonts.heading(),
                     text_color=p.text).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        self._app_ver = ctk.CTkLabel(self._app_card, text=_("Проверяю версию приложения…"),
                                     font=fonts.small(), text_color=p.text_muted, anchor="w",
                                     wraplength=330, justify="left")
        self._app_ver.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")
        self._app_btn = ctk.CTkButton(
            self._app_card, text="…", font=fonts.small(), width=190, height=30,
            state="disabled", command=self._update_app)
        self._app_btn.grid(row=0, column=1, rowspan=2, padx=(8, 16), sticky="e")

        # "Управление ядром" info panel.
        self._info_card = ctk.CTkFrame(self._body, fg_color=p.surface, corner_radius=12)
        self._info_card.grid(row=5, column=0, sticky="ew", pady=(0, 12))
        self._info_card.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            self._info_card, text=_("Управление ядром"), font=fonts.heading(), text_color=p.text
        ).grid(row=0, column=0, columnspan=2, padx=16, pady=(12, 6), sticky="w")
        self._info_rows = ctk.CTkFrame(self._info_card, fg_color="transparent")
        self._info_rows.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="ew")
        self._info_rows.grid_columnconfigure(1, weight=1)

        # DPI-bypass tools (ByeDPI, Zapret) — install / update / delete. Configured
        # on the AntiDPI screen; managed (package lifecycle) here next to the core.
        self._tools_card = ctk.CTkFrame(self._body, fg_color=p.surface, corner_radius=12)
        self._tools_card.grid(row=6, column=0, sticky="ew", pady=(0, 12))
        self._tools_card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._tools_card, text=_("Инструменты обхода DPI"), font=fonts.heading(),
                     text_color=p.text).grid(row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(self._tools_card, text=_("Настройка — на странице AntiDPI. Здесь — установка и удаление."),
                     font=fonts.small(), text_color=p.text_muted).grid(row=1, column=0, padx=16, sticky="w")
        self._tools_rows = ctk.CTkFrame(self._tools_card, fg_color="transparent")
        self._tools_rows.grid(row=2, column=0, padx=16, pady=(6, 12), sticky="ew")
        self._tools_rows.grid_columnconfigure(1, weight=1)
        self._tool_btns: list[ctk.CTkButton] = []

        # Progress log for install/update actions — pinned to the BOTTOM of the
        # screen (a direct child of self, NOT the scrollable body) so it stays fully
        # visible while an action runs, instead of being clipped below the fold of
        # the scroll frame. Hidden until one runs.
        self._oplog = ctk.CTkTextbox(self, font=ctk.CTkFont(family="Consolas", size=12),
                                     height=150, fg_color=p.surface, text_color=p.text_muted,
                                     wrap="word", corner_radius=10)
        self._oplog.grid(row=1, column=0, sticky="ew", padx=24, pady=(0, 16))
        self._oplog.configure(state="disabled")
        self._oplog.grid_remove()

    def _on_resize(self, event: Any) -> None:
        # The card stretches to the body width; wrap labels to fit it. Hints share
        # their row with the ~190px action button (column 1), so they get less width
        # than the full-width warn/app-version rows. Card width tracks the parent,
        # not the label, so updating wraplength here can't feed back into a resize.
        w = event.width
        if w <= 1:
            return
        hint_wl = max(w - 190 - 96, 160)   # minus button column + paddings
        full_wl = max(w - 80, 160)
        for h in self._radio_hints.values():
            h.configure(wraplength=hint_wl)
        self._warn_lbl.configure(wraplength=full_wl)
        self._app_ver.configure(wraplength=hint_wl)

    # ----- data ---------------------------------------------------------

    def _load_core_info(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            info = client.ubus_homeproxy("diag_core_check", timeout=15)
            # When the core is installed but down, find out WHY (a bad node?) so we
            # can name the offending server instead of just "остановлено".
            failure = None
            if isinstance(info, dict) and not info.get("running") and \
                    (info.get("singbox_installed") or info.get("hiddify_installed")):
                try:
                    failure = core_health.diagnose_core_failure(client, core=info)
                except Exception:
                    failure = None
            if isinstance(info, dict):
                info["_failure"] = failure
            return info

        run_async(self, task, self._render_info, self._on_error)

    def _on_error(self, exc: BaseException) -> None:
        self._status.configure(text=_("Ошибка чтения ядра: {0}").format(exc), text_color=self.p.fail)

    def _render_info(self, info: dict[str, Any]) -> None:
        self._core_info = info
        p = self.p
        installed = {
            "hiddify": bool(info.get("hiddify_installed")),
            "singbox": bool(info.get("singbox_installed")),
        }
        # Enable only installed cores; annotate the rest; set each core's action
        # button to Install (missing) or Update-to-latest (present).
        for key, (k, label, sub) in zip(("hiddify", "singbox"), CORE_OPTIONS):
            present = installed[k]
            self._radios[k].configure(state="normal" if present else "disabled")
            # Reset hint to the base text first (so repeated renders don't stack
            # "· не установлен" onto an already-annotated label).
            self._radio_hints[k].configure(text=_(sub) + ("" if present else _("  · не установлен")))
            if self._busy:
                continue  # an action is running — leave buttons disabled
            btn = self._core_btns[k]
            if present:
                btn.configure(text=_("Обновить до последней"), state="normal",
                              fg_color=p.surface_hover, hover_color=p.border, text_color=p.text)
            else:
                btn.configure(text=_("Установить"), state="normal",
                              fg_color=p.accent, hover_color=p.accent_hover, text_color=p.accent_fg)
        # If no explicit preferred_core, preselect the active one (auto precedence: hiddify first).
        if not self._choice.get():
            self._choice.set("hiddify" if installed["hiddify"] else ("singbox" if installed["singbox"] else ""))
        self._initial_choice = self._choice.get()

        running = _("запущено 🟢") if info.get("running") else _("остановлено 🔴")
        self._status.configure(text=_("Состояние: {0}").format(running), text_color=p.text_muted)

        # Config-error explainer: if the core is down because of a bad node, name it.
        failure = info.get("_failure")
        if failure:
            head, steps = core_health.failure_message(failure)
            self._fail_lbl.configure(text="⚠ " + head + "\n\n• " + "\n• ".join(steps))
            self._fail_card.grid()
        else:
            self._fail_card.grid_remove()

        rows = [
            (_("Менеджер пакетов"), self._state.package_manager.value),
            (_("Архитектура"), self._state.arch or "—"),
            (_("Свободно /tmp"), f"{self._state.free_tmp_mb} MB" if self._state.free_tmp_mb is not None else "—"),
            ("Свободно overlay", f"{self._state.free_overlay_mb} MB" if self._state.free_overlay_mb is not None else "—"),
            (_("Версия ядра"), _clean_version(info.get("version", ""))),
        ]
        for i, (k, v) in enumerate(rows):
            color = p.text
            if k == "Свободно overlay" and self._state.free_overlay_mb is not None and self._state.free_overlay_mb < 10:
                color = p.fail
            ctk.CTkLabel(self._info_rows, text=k, font=fonts.small(), text_color=p.text_muted).grid(
                row=i, column=0, padx=(0, 12), pady=3, sticky="w"
            )
            ctk.CTkLabel(self._info_rows, text=v, font=fonts.body(), text_color=color, anchor="e").grid(
                row=i, column=1, pady=3, sticky="e"
            )

    # ----- actions ------------------------------------------------------

    def _on_pick(self) -> None:
        choice = self._choice.get()
        changed = choice != getattr(self, "_initial_choice", choice)
        if not changed:
            self._restart_btn.configure(state="disabled")
            self._apply_note.configure(text="")
            return
        # Persist the setting immediately (uci); restart applies it.
        client = self._client

        def task() -> None:
            client.uci_set("homeproxy.config.preferred_core", choice)
            client.uci_commit("homeproxy")

        def done(_r: Any) -> None:
            self._restart_btn.configure(state="normal")
            self._apply_note.configure(
                text=_("Ядро выбрано. Нажмите «Применить изменения»."), text_color=self.p.warn
            )

        run_async(self, task, done, self._on_error)

    def _restart(self) -> None:
        self._restart_btn.configure(state="disabled", text=_("Применяю…"))
        client = self._client
        run_async(self, lambda: client.ubus_homeproxy("diag_service_restart", timeout=40),
                  self._after_restart, self._on_error)

    def _after_restart(self, res: dict[str, Any]) -> None:
        ok = bool(res.get("result"))
        self._restart_btn.configure(text=_("Применить изменения"))
        if ok:
            self._initial_choice = self._choice.get()
            self._apply_note.configure(text=_("Изменения применены."), text_color=self.p.ok)
            self._load_core_info()
        else:
            self._restart_btn.configure(state="normal")
            self._apply_note.configure(text=_("Не удалось применить изменения."), text_color=self.p.fail)

    # ----- install / update actions -------------------------------------

    def _load_app_version(self) -> None:
        client = self._client

        def task() -> tuple[str, str]:
            ti = preinstall.get_target_info(client)
            return install_app.app_versions(client, ti)

        run_async(self, task, self._render_app_version, lambda _e: None)

    def _render_app_version(self, vers: tuple[str, str]) -> None:
        if self._busy:
            return
        inst, latest = vers
        p = self.p
        if not inst:
            self._app_ver.configure(text=_("Приложение не установлено."), text_color=p.warn)
            self._app_btn.configure(text=_("Установить"), state="normal", fg_color=p.accent,
                                    hover_color=p.accent_hover, text_color=p.accent_fg)
        elif install_app.is_newer(latest, inst):
            self._app_ver.configure(text=_("Установлено {0} · доступно {1}").format(inst, latest), text_color=p.warn)
            self._app_btn.configure(text=_("Обновить приложение"), state="normal", fg_color=p.accent,
                                    hover_color=p.accent_hover, text_color=p.accent_fg)
        else:
            shown = _("{0} (последняя версия)").format(inst) if latest else inst
            self._app_ver.configure(text=_("Установлено {0}").format(shown),
                                    text_color=p.ok if latest else p.text_muted)
            self._app_btn.configure(text=_("Переустановить"), state="normal",
                                    fg_color=p.surface_hover, hover_color=p.border, text_color=p.text)

    def _show_log(self) -> None:
        self._oplog.grid()
        self._oplog.configure(state="normal")
        self._oplog.delete("1.0", "end")
        self._oplog.configure(state="disabled")

    def _append_log(self, msg: str) -> None:
        self._oplog.configure(state="normal")
        self._oplog.insert("end", msg + "\n")
        self._oplog.see("end")
        self._oplog.configure(state="disabled")

    def _lock(self) -> None:
        self._busy = True
        for b in self._core_btns.values():
            b.configure(state="disabled")
        self._app_btn.configure(state="disabled")
        self._restart_btn.configure(state="disabled")
        for b in getattr(self, "_tool_btns", []):
            b.configure(state="disabled")

    def _core_action(self, core: str) -> None:
        if self._busy:
            return
        self._lock()
        self._show_log()
        label = next((lbl for k, lbl, _s in CORE_OPTIONS if k == core), core)
        self._append_log(f"▶ {label}…")
        client = self._client

        def task() -> tuple[bool, str]:
            ti = preinstall.get_target_info(client)
            return install_app.install_core(
                client, ti, core, progress=lambda m: post_to(self, lambda: self._append_log(m)))

        run_async(self, task, self._op_done, self._op_err)

    def _update_app(self) -> None:
        if self._busy:
            return
        self._lock()
        self._show_log()
        self._append_log(_("▶ Обновление приложения…"))
        client = self._client

        def task() -> tuple[bool, str]:
            ti = preinstall.get_target_info(client)
            return install_app.update_app(
                client, ti, language=luci_lang(),
                progress=lambda m: post_to(self, lambda: self._append_log(m)))

        run_async(self, task, self._op_done, self._op_err)

    def _op_done(self, res: tuple[bool, str]) -> None:
        ok, msg = res
        self._append_log(("✓ " if ok else "✗ ") + msg)
        self._refresh_all()

    def _op_err(self, exc: BaseException) -> None:
        self._append_log(_("✗ Ошибка: {0}").format(exc))
        self._refresh_all()

    def _refresh_all(self) -> None:
        self._busy = False
        self._load_core_info()    # re-enables/relabels core buttons via _render_info
        self._load_app_version()  # re-enables/relabels the app button
        self._load_tools()        # re-enables/relabels the DPI-tool buttons

    # ----- DPI-bypass tools (ByeDPI / Zapret) ---------------------------

    def _load_tools(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            return {"byedpi": bd.get_status(client), "zapret": zp.get_status(client)}

        run_async(self, task, self._render_tools, lambda _e: None)

    def _render_tools(self, d: dict[str, Any]) -> None:
        if self._busy:
            return
        p = self.p
        for w in self._tools_rows.winfo_children():
            w.destroy()
        self._tool_btns = []
        tools = [("byedpi", "ByeDPI", d.get("byedpi") or {}),
                 ("zapret", "Zapret", d.get("zapret") or {})]
        for i, (key, name, st) in enumerate(tools):
            installed = bool(st.get("installed"))
            running = bool(st.get("running"))
            ver = st.get("version")
            ctk.CTkLabel(self._tools_rows, text=name, font=fonts.body(), text_color=p.text).grid(
                row=i, column=0, padx=(0, 10), pady=4, sticky="w")
            if installed:
                stxt = (_("🟢 запущен") if running else _("🟡 установлен")) + (f" · {ver}" if ver else "")
                scol = p.ok if running else p.warn
            else:
                stxt, scol = _("🔴 не установлен"), p.text_muted
            ctk.CTkLabel(self._tools_rows, text=stxt, font=fonts.small(), text_color=scol,
                         anchor="w").grid(row=i, column=1, pady=4, sticky="w")
            actrow = ctk.CTkFrame(self._tools_rows, fg_color="transparent")
            actrow.grid(row=i, column=2, sticky="e")
            if installed:
                upd = ctk.CTkButton(actrow, text=_("Обновить"), font=fonts.small(), width=110, height=28,
                                    fg_color=p.surface_hover, hover_color=p.border, text_color=p.text,
                                    command=lambda k=key: self._tool_install(k))
                upd.grid(row=0, column=0, padx=(0, 6))
                dele = ctk.CTkButton(actrow, text=_("Удалить"), font=fonts.small(), width=90, height=28,
                                     fg_color=p.surface_hover, hover_color=p.fail, text_color=p.text_muted,
                                     command=lambda k=key: self._tool_remove(k))
                dele.grid(row=0, column=1)
                self._tool_btns += [upd, dele]
            else:
                ins = ctk.CTkButton(actrow, text=_("Установить"), font=fonts.small(), width=110, height=28,
                                    fg_color=p.accent, hover_color=p.accent_hover, text_color=p.accent_fg,
                                    command=lambda k=key: self._tool_install(k))
                ins.grid(row=0, column=0)
                self._tool_btns.append(ins)

    def _tool_install(self, key: str) -> None:
        if self._busy:
            return
        self._lock()
        self._show_log()
        name = "ByeDPI" if key == "byedpi" else "Zapret"
        self._append_log(_("▶ Установка/обновление: {0}…").format(name))
        client = self._client
        eng = bd if key == "byedpi" else zp

        def task() -> tuple[bool, str]:
            return eng.install(client, progress=lambda m: post_to(self, lambda: self._append_log(m)))

        run_async(self, task, self._op_done, self._op_err)

    def _tool_remove(self, key: str) -> None:
        if self._busy:
            return
        self._lock()
        self._show_log()
        name = "ByeDPI" if key == "byedpi" else "Zapret"
        self._append_log(_("▶ Удаление: {0}…").format(name))
        client = self._client
        eng = bd if key == "byedpi" else zp

        def task() -> tuple[bool, str]:
            ok = eng.remove(client)
            return (ok, _("{0} удалён.").format(name) if ok else _("Не удалось удалить {0}.").format(name))

        run_async(self, task, self._op_done, self._op_err)
