# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""AntiDPI screen — local DPI bypass via two engines, ByeDPI and Zapret.

Two stacked section cards on one page: ByeDPI (SOCKS-level desync) and Zapret
(packet-level nfqws2, which can also carry QUIC video and Discord calls). Each
section has its own status, enable switch, strategy picker and live tester; the
Zapret section adds install-on-enable, a Discord-calls switch, and a full-test
sweep over every candidate (the same client-driven loop as the LuCI page).
"""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ..engine import byedpi as bd
from ..engine import zapret as zp
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import N_, _

_REASON = {"dns": "DNS", "refused": N_("отказ"), "timeout": N_("таймаут"), "tls": "TLS",
           "fail": N_("сбой")}


class AntiDPIScreen(ctk.CTkFrame):
    """Page shell: title + the two stacked DPI-bypass sections."""

    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, padx=24, pady=16, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(body, text="AntiDPI", font=fonts.title(), text_color=palette.text,
                     image=kit.icon(kit.ICON_FOR["byedpi"], 26), compound="left").grid(
            row=0, column=0, pady=(4, 4), sticky="w")
        ctk.CTkLabel(body, text=_("Обход DPI для сервисов, где не нужен полный VPN. "
                     "Два инструмента — попробуйте оба, что сработает, зависит от провайдера."),
                     font=fonts.small(), text_color=palette.text_muted, justify="left",
                     wraplength=560, anchor="w").grid(row=1, column=0, sticky="w", pady=(0, 10))

        _ByeDPISection(body, palette, client).grid(row=2, column=0, sticky="ew", pady=(0, 16))
        _ZapretSection(body, palette, client).grid(row=3, column=0, sticky="ew")


# ======================================================================
# ByeDPI section (logic preserved from the former ByeDPIScreen)
# ======================================================================


class _ByeDPISection(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self.grid_columnconfigure(0, weight=1)

        kit.SectionHeader(self, palette, "byedpi", "ByeDPI").grid(
            row=0, column=0, pady=(0, 2), sticky="w")
        self._status = ctk.CTkLabel(self, text=_("Считываю ByeDPI…"), font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w")
        self._status.grid(row=1, column=0, sticky="w", pady=(2, 8))

        self._status_card = ctk.CTkFrame(self, fg_color=palette.surface, corner_radius=12)
        self._status_card.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        self._status_card.grid_columnconfigure(1, weight=1)
        self._cfg_card = ctk.CTkFrame(self, fg_color=palette.surface, corner_radius=12)
        self._cfg_card.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self._cfg_card.grid_columnconfigure(0, weight=1)
        self._test_card = ctk.CTkFrame(self, fg_color=palette.surface, corner_radius=12)
        self._test_card.grid(row=4, column=0, sticky="ew")
        self._test_card.grid_columnconfigure(0, weight=1)
        self.refresh()

    def refresh(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            return {"status": bd.get_status(client), "config": bd.get_config(client)}

        run_async(self, task, self._render, self._err)

    def _err(self, e: BaseException) -> None:
        self._status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)

    def _render(self, d: dict[str, Any]) -> None:
        p = self.p
        st, cfg = d["status"], d["config"]
        for card in (self._status_card, self._cfg_card, self._test_card):
            for w in card.winfo_children():
                w.destroy()

        if "error" in st:
            self._status.configure(text=st["error"], text_color=p.fail)
            return
        running = bool(st.get("running"))
        installed = bool(st.get("installed"))
        self._status.configure(
            text=(_("🟢 установлен и запущен") if running else
                  (_("🟡 установлен, остановлен") if installed else _("🔴 не установлен")))
            + (f"  ·  ciadpi {st.get('version')}" if st.get("version") else ""),
            text_color=(p.ok if running else (p.warn if installed else p.fail)))

        rows = [(_("Версия"), st.get("version") or "—"), (_("Архитектура"), st.get("arch") or "—")]
        for i, (k, v) in enumerate(rows):
            ctk.CTkLabel(self._status_card, text=k, font=fonts.small(), text_color=p.text_muted).grid(
                row=i, column=0, padx=(16, 12), pady=3, sticky="w")
            ctk.CTkLabel(self._status_card, text=v, font=fonts.body(), text_color=p.text, anchor="e").grid(
                row=i, column=1, padx=(0, 16), pady=3, sticky="e")

        self._enabled = ctk.StringVar(value="1" if cfg["enabled"] else "0")
        ctk.CTkSwitch(self._cfg_card, text=_("Включить ByeDPI"), font=fonts.body(), variable=self._enabled,
                      onvalue="1", offvalue="0", progress_color=p.accent,
                      command=self._on_enable).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        ctk.CTkLabel(self._cfg_card, text=_("Готовая стратегия:"), font=fonts.small(),
                     text_color=p.text_muted).grid(row=1, column=0, padx=16, pady=(0, 0), sticky="w")
        self._presets = {name: args for name, args in bd.STRATEGY_PRESETS}
        self._preset_menu = ctk.CTkOptionMenu(
            self._cfg_card, values=[_("— выбрать —"), *self._presets.keys()], font=fonts.body(),
            fg_color=p.surface_hover, button_color=p.accent, button_hover_color=p.accent_hover,
            command=self._on_preset, dynamic_resizing=False, width=320)
        self._preset_menu.set(_("— выбрать —"))
        self._preset_menu.grid(row=2, column=0, padx=16, pady=(2, 6), sticky="w")

        ctk.CTkLabel(self._cfg_card, text=_("Стратегия (аргументы ciadpi):"), font=fonts.small(),
                     text_color=p.text_muted).grid(row=3, column=0, padx=16, sticky="w")
        self._cmd = ctk.CTkEntry(self._cfg_card, font=fonts.mono(12))
        self._cmd.insert(0, cfg["cmd_opts"])
        self._cmd.grid(row=4, column=0, padx=16, pady=(4, 6), sticky="ew")
        row = ctk.CTkFrame(self._cfg_card, fg_color="transparent")
        row.grid(row=5, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(row, text=_("Сохранить стратегию"), font=fonts.body(), fg_color=p.accent,
                      text_color=p.accent_fg, hover_color=p.accent_hover, command=self._save_cmd).grid(row=0, column=0)
        self._restart_btn = ctk.CTkButton(row, text=_("Применить изменения"), font=fonts.body(),
                                          fg_color=p.surface_hover, hover_color=p.border,
                                          command=self._restart_service)
        self._restart_btn.grid(row=0, column=1, padx=(8, 0))
        self._save_note = ctk.CTkLabel(row, text="", font=fonts.small(), text_color=p.text_muted)
        self._save_note.grid(row=0, column=2, padx=10)

        kit.SectionHeader(self._test_card, p, "strategy", _("Тест стратегии")).grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(self._test_card, text=_("● = TLS-рукопожатие успешно, ○ = заблокировано"),
                     font=fonts.small(), text_color=p.text_muted).grid(row=1, column=0, padx=16, sticky="w")
        self._test_btn = ctk.CTkButton(self._test_card, text=_("▶ Запустить тест"), font=fonts.body(),
                                       fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                                       command=self._run_test)
        self._test_btn.grid(row=2, column=0, padx=16, pady=(8, 6), sticky="w")
        self._test_out = ctk.CTkFrame(self._test_card, fg_color="transparent", height=1)
        self._test_out.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")

    def _on_preset(self, name: str) -> None:
        args = self._presets.get(name)
        if not args:
            return
        self._cmd.delete(0, "end")
        self._cmd.insert(0, args)
        self._save_note.configure(text=_("Стратегия подставлена — нажмите «Сохранить»."),
                                  text_color=self.p.text_muted)

    def _on_enable(self) -> None:
        on = self._enabled.get() == "1"
        client = self._client
        run_async(self, lambda: bd.set_enabled(client, on),
                  lambda _r: self._save_note.configure(
                      text=_("Изменено — нажмите «Применить изменения»."), text_color=self.p.warn),
                  self._err)

    def _save_cmd(self) -> None:
        opts = self._cmd.get().strip()
        client = self._client
        run_async(self, lambda: bd.set_cmd_opts(client, opts),
                  lambda _r: self._save_note.configure(
                      text=_("Сохранено — нажмите «Применить изменения»."), text_color=self.p.warn),
                  self._err)

    def _restart_service(self) -> None:
        self._restart_btn.configure(state="disabled", text=_("Применяю…"))
        client = self._client
        run_async(self, lambda: bd.restart_service(client), self._restarted, self._restart_err)

    def _restarted(self, ok: bool) -> None:
        self._restart_btn.configure(state="normal", text=_("Применить изменения"))
        self._save_note.configure(text=_("Изменения применены.") if ok else _("Не удалось применить."),
                                  text_color=self.p.ok if ok else self.p.fail)

    def _restart_err(self, e: BaseException) -> None:
        self._restart_btn.configure(state="normal", text=_("Применить изменения"))
        self._err(e)

    def _run_test(self) -> None:
        opts = self._cmd.get().strip() or "--disorder 1"
        self._test_btn.configure(state="disabled", text=_("Тестирую… (до минуты)"))
        for w in self._test_out.winfo_children():
            w.destroy()
        client = self._client
        run_async(self, lambda: bd.run_test(client, opts), self._show_test, self._test_err)

    def _test_err(self, e: BaseException) -> None:
        self._test_btn.configure(state="normal", text=_("▶ Запустить тест"))
        self._err(e)

    def _show_test(self, res: dict[str, Any]) -> None:
        p = self.p
        self._test_btn.configure(state="normal", text=_("▶ Запустить тест"))
        if "error" in res:
            ctk.CTkLabel(self._test_out, text=res["error"], font=fonts.body(),
                         text_color=p.fail).grid(row=0, column=0, sticky="w")
            return
        results = res.get("results", [])
        for i, r in enumerate(results):
            ok = bool(r.get("ok"))
            dot = "●" if ok else "○"
            reason = "" if ok else f"  ({_(_REASON.get(r.get('reason'), r.get('reason') or '—'))})"
            ctk.CTkLabel(self._test_out, text=f"{dot}  {r.get('label')}{reason}", font=fonts.body(),
                         text_color=(p.ok if ok else p.fail), anchor="w").grid(
                row=i, column=0, sticky="w", pady=1)
        passed, total = res.get("passed", 0), res.get("total", len(results))
        ctk.CTkLabel(self._test_out, text=_("Пройдено: {0} из {1}").format(passed, total), font=fonts.small(),
                     text_color=p.text_muted).grid(row=len(results), column=0, sticky="w", pady=(6, 0))


# ======================================================================
# Zapret section
# ======================================================================

_GRP_REC = N_("··· Рекомендуемые ···")
_GRP_AUTO = N_("··· Полный набор ···")


class _ZapretSection(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._cands: list[dict[str, str]] = []
        self._full_stop = False
        self._full_running = False
        self.grid_columnconfigure(0, weight=1)

        kit.SectionHeader(self, palette, "strategy", "Zapret2").grid(
            row=0, column=0, pady=(0, 2), sticky="w")
        ctk.CTkLabel(self, text=_("Также разблокирует видео (QUIC) и звонки, с которыми ByeDPI не справляется."),
                     font=fonts.small(), text_color=palette.text_muted, anchor="w").grid(
            row=1, column=0, sticky="w")
        self._status = ctk.CTkLabel(self, text=_("Считываю Zapret…"), font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w")
        self._status.grid(row=2, column=0, sticky="w", pady=(4, 8))

        self._status_card = ctk.CTkFrame(self, fg_color=palette.surface, corner_radius=12)
        self._status_card.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self._status_card.grid_columnconfigure(1, weight=1)
        self._cfg_card = ctk.CTkFrame(self, fg_color=palette.surface, corner_radius=12)
        self._cfg_card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        self._cfg_card.grid_columnconfigure(0, weight=1)
        self._test_card = ctk.CTkFrame(self, fg_color=palette.surface, corner_radius=12)
        self._test_card.grid(row=5, column=0, sticky="ew")
        self._test_card.grid_columnconfigure(0, weight=1)
        self.refresh()

    # ----- read ---------------------------------------------------------

    def refresh(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            return {"status": zp.get_status(client), "config": zp.get_config(client),
                    "candidates": zp.load_candidates(client)}

        run_async(self, task, self._render, self._err)

    def _err(self, e: BaseException) -> None:
        self._status.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)

    def _render(self, d: dict[str, Any]) -> None:
        p = self.p
        st, cfg = d["status"], d["config"]
        self._cands = d.get("candidates") or []
        for card in (self._status_card, self._cfg_card, self._test_card):
            for w in card.winfo_children():
                w.destroy()

        if "error" in st:
            self._status.configure(text=st["error"], text_color=p.fail)
            return
        running = bool(st.get("running"))
        installed = bool(st.get("installed"))
        self._installed = installed
        self._pkg_manager = st.get("pkg_manager")
        # kmod_ok: NFQUEUE kernel module present. None = unknown (old backend) → don't warn/block.
        self._kmod_ok = st.get("kmod_ok")
        kmod_missing = installed and self._kmod_ok is False
        self._status.configure(
            text=(_("🟢 установлен и запущен") if running else
                  (_("🟡 установлен, остановлен") if installed else _("🔴 не установлен")))
            + (f"  ·  nfqws2 {st.get('version')}" if st.get("version") else "")
            + (_("   ⚠ нет модуля NFQUEUE (kmod-nft-queue)") if kmod_missing else ""),
            text_color=(p.fail if kmod_missing else
                        (p.ok if running else (p.warn if installed else p.fail))))

        rows = [(_("Версия"), st.get("version") or "—"), (_("Архитектура"), st.get("arch") or "—")]
        for i, (k, v) in enumerate(rows):
            ctk.CTkLabel(self._status_card, text=k, font=fonts.small(), text_color=p.text_muted).grid(
                row=i, column=0, padx=(16, 12), pady=3, sticky="w")
            ctk.CTkLabel(self._status_card, text=v, font=fonts.body(), text_color=p.text, anchor="e").grid(
                row=i, column=1, padx=(0, 16), pady=3, sticky="e")
        # Install row — created ONLY when not installed (an empty CTkFrame would
        # otherwise reserve its default 200px and bloat the card).
        if not installed:
            self._install_box = ctk.CTkFrame(self._status_card, fg_color="transparent")
            self._install_box.grid(row=len(rows), column=0, columnspan=2, padx=16, pady=(4, 10), sticky="ew")
            self._build_install_prompt()

        # Config card.
        self._enabled = ctk.StringVar(value="1" if cfg["enabled"] else "0")
        ctk.CTkSwitch(self._cfg_card, text=_("Включить Zapret"), font=fonts.body(), variable=self._enabled,
                      onvalue="1", offvalue="0", progress_color=p.accent,
                      command=self._on_enable).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")

        ctk.CTkLabel(self._cfg_card, text=_("Готовая стратегия:"), font=fonts.small(),
                     text_color=p.text_muted).grid(row=1, column=0, padx=16, sticky="w")
        self._preset_map, values = self._build_preset_values()
        self._preset_menu = ctk.CTkOptionMenu(
            self._cfg_card, values=values, font=fonts.body(), fg_color=p.surface_hover,
            button_color=p.accent, button_hover_color=p.accent_hover,
            command=self._on_preset, dynamic_resizing=False, width=320)
        self._preset_menu.set(_("— выбрать —"))
        self._preset_menu.grid(row=2, column=0, padx=16, pady=(2, 6), sticky="w")

        ctk.CTkLabel(self._cfg_card, text=_("Стратегия (опции nfqws2):"), font=fonts.small(),
                     text_color=p.text_muted).grid(row=3, column=0, padx=16, sticky="w")
        self._cmd = ctk.CTkEntry(self._cfg_card, font=fonts.mono(12))
        self._cmd.insert(0, cfg["cmd_opts"])
        self._cmd.grid(row=4, column=0, padx=16, pady=(4, 6), sticky="ew")

        self._voice = ctk.StringVar(value="1" if cfg["voice"] else "0")
        ctk.CTkSwitch(self._cfg_card, text=_("Звонки Discord через Zapret"), font=fonts.body(),
                      variable=self._voice, onvalue="1", offvalue="0", progress_color=p.accent,
                      command=self._on_voice).grid(row=5, column=0, padx=16, pady=(2, 6), sticky="w")

        row = ctk.CTkFrame(self._cfg_card, fg_color="transparent")
        row.grid(row=6, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(row, text=_("Сохранить стратегию"), font=fonts.body(), fg_color=p.accent,
                      text_color=p.accent_fg, hover_color=p.accent_hover, command=self._save_cmd).grid(row=0, column=0)
        self._restart_btn = ctk.CTkButton(row, text=_("Применить изменения"), font=fonts.body(),
                                          fg_color=p.surface_hover, hover_color=p.border,
                                          command=self._restart_service)
        self._restart_btn.grid(row=0, column=1, padx=(8, 0))
        self._save_note = ctk.CTkLabel(row, text="", font=fonts.small(), text_color=p.text_muted)
        self._save_note.grid(row=0, column=2, padx=10)

        # Test card: single-strategy test + full sweep.
        kit.SectionHeader(self._test_card, p, "strategy", _("Тест стратегий")).grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(self._test_card, text=_("● = TLS-рукопожатие успешно, ○ = заблокировано. "
                     "Ваше соединение во время теста не затрагивается."),
                     font=fonts.small(), text_color=p.text_muted, justify="left",
                     wraplength=540, anchor="w").grid(row=1, column=0, padx=16, sticky="w")

        btnrow = ctk.CTkFrame(self._test_card, fg_color="transparent")
        btnrow.grid(row=2, column=0, padx=16, pady=(8, 6), sticky="w")
        self._test_btn = ctk.CTkButton(btnrow, text=_("▶ Тест текущей"), font=fonts.body(),
                                       fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                                       command=self._run_test)
        self._test_btn.grid(row=0, column=0)
        self._full_btn = ctk.CTkButton(btnrow, text=_("⚡ Полная проверка"), font=fonts.body(),
                                       fg_color=p.surface_hover, hover_color=p.border, command=self._full_start)
        self._full_btn.grid(row=0, column=1, padx=(8, 0))
        self._stop_btn = ctk.CTkButton(btnrow, text=_("■ Стоп"), font=fonts.body(), fg_color=p.surface_hover,
                                       hover_color=p.border, command=self._full_stop_click, width=80)
        # shown only while running
        self._full_note = ctk.CTkLabel(self._test_card, text="", font=fonts.small(), text_color=p.text_muted,
                                       anchor="w")
        self._full_note.grid(row=3, column=0, padx=16, sticky="w")
        # Results area is gridded lazily (_show_out) so an empty CTkFrame doesn't
        # reserve its default ~200px of dead space before any test is run.
        self._test_out = ctk.CTkFrame(self._test_card, fg_color="transparent")
        self._test_out.grid_columnconfigure(0, weight=1)

    def _show_out(self) -> None:
        """Place the results frame in the grid (no-op if already shown)."""
        self._test_out.grid(row=4, column=0, padx=16, pady=(2, 12), sticky="ew")

    def _clear_out(self) -> None:
        for w in self._test_out.winfo_children():
            w.destroy()
        self._test_out.grid_remove()

    # ----- install ------------------------------------------------------

    def _build_install_prompt(self) -> None:
        p = self.p
        for w in self._install_box.winfo_children():
            w.destroy()
        if not self._pkg_manager:
            ctk.CTkLabel(self._install_box, text=_("Менеджер пакетов не найден — установите zapret2 вручную."),
                         font=fonts.small(), text_color=p.fail, anchor="w").grid(row=0, column=0, sticky="w")
            return
        ctk.CTkLabel(self._install_box, text=_("Zapret (zapret2/nfqws2) не установлен. Установить сейчас?"),
                     font=fonts.small(), text_color=p.warn, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        self._install_btn = ctk.CTkButton(self._install_box, text=_("Установить Zapret"), font=fonts.body(),
                                          fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                                          command=self._do_install)
        self._install_btn.grid(row=1, column=0, sticky="w")
        self._install_note = ctk.CTkLabel(self._install_box, text="", font=fonts.small(),
                                          text_color=p.text_muted, anchor="w")
        self._install_note.grid(row=1, column=1, padx=10, sticky="w")

    def _do_install(self) -> None:
        self._install_btn.configure(state="disabled", text=_("Устанавливаю…"))
        client = self._client

        def progress(msg: str) -> None:
            self.after(0, lambda: self._install_note.configure(text=msg, text_color=self.p.text_muted))

        run_async(self, lambda: zp.install(client, progress), self._installed_cb, self._install_err)

    def _installed_cb(self, res: tuple[bool, str]) -> None:
        ok, msg = res
        if ok:
            self._install_note.configure(text="✓ " + msg, text_color=self.p.ok)
            self.after(800, self.refresh)
        else:
            self._install_btn.configure(state="normal", text=_("Установить Zapret"))
            self._install_note.configure(text=msg, text_color=self.p.fail)
            if hasattr(self, "_enabled"):
                self._enabled.set("0")

    def _install_err(self, e: BaseException) -> None:
        self._install_btn.configure(state="normal", text=_("Установить Zapret"))
        self._install_note.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)

    # ----- edits --------------------------------------------------------

    def _build_preset_values(self) -> tuple[dict[str, str], list[str]]:
        """Flat values list with group separators; name->args map (separators excluded)."""
        mapping: dict[str, str] = {}
        values: list[str] = [_("— выбрать —")]
        rec = [c for c in self._cands if c.get("group", "recommended") == "recommended"]
        auto = [c for c in self._cands if c.get("group") == "auto"]
        if rec:
            values.append(_(_GRP_REC))
            for c in rec:
                values.append(c["name"])
                mapping[c["name"]] = c["args"]
        if auto:
            values.append(_(_GRP_AUTO))
            for c in auto:
                values.append(c["name"])
                mapping[c["name"]] = c["args"]
        return mapping, values

    def _on_preset(self, name: str) -> None:
        args = self._preset_map.get(name)
        if not args:  # separator or "— выбрать —"
            self._preset_menu.set(_("— выбрать —"))
            return
        self._cmd.delete(0, "end")
        self._cmd.insert(0, args)
        self._save_note.configure(text=_("Стратегия подставлена — нажмите «Сохранить»."),
                                  text_color=self.p.text_muted)

    def _on_enable(self) -> None:
        on = self._enabled.get() == "1"
        if on and not getattr(self, "_installed", False):
            # Cannot enable what isn't installed — bounce back and point at the install prompt.
            self._enabled.set("0")
            self._save_note.configure(text=_("Сначала установите Zapret (кнопка выше)."), text_color=self.p.warn)
            return
        if on and getattr(self, "_kmod_ok", None) is False:
            # Installed but the NFQUEUE kmod is missing — enabling would emit `queue num`
            # and nft would reject the whole fw4 set. Block it.
            self._enabled.set("0")
            self._save_note.configure(
                text=_("Нет модуля ядра NFQUEUE (kmod-nft-queue). Переустановите Zapret на странице «Ядро» "
                     "или установите kmod-nft-queue — иначе включение сломает firewall."),
                text_color=self.p.fail)
            return
        client = self._client
        run_async(self, lambda: zp.set_enabled(client, on),
                  lambda _r: self._save_note.configure(
                      text=_("Изменено — нажмите «Применить изменения»."), text_color=self.p.warn),
                  self._err)

    def _on_voice(self) -> None:
        on = self._voice.get() == "1"
        client = self._client
        run_async(self, lambda: zp.set_voice(client, on),
                  lambda _r: self._save_note.configure(
                      text=_("Изменено — нажмите «Применить изменения»."), text_color=self.p.warn),
                  self._err)

    def _save_cmd(self) -> None:
        opts = self._cmd.get().strip()
        client = self._client
        run_async(self, lambda: zp.set_cmd_opts(client, opts),
                  lambda _r: self._save_note.configure(
                      text=_("Сохранено — нажмите «Применить изменения»."), text_color=self.p.warn),
                  self._err)

    def _restart_service(self) -> None:
        self._restart_btn.configure(state="disabled", text=_("Применяю…"))
        client = self._client
        run_async(self, lambda: zp.restart_service(client), self._restarted, self._restart_err)

    def _restarted(self, ok: bool) -> None:
        self._restart_btn.configure(state="normal", text=_("Применить изменения"))
        self._save_note.configure(text=_("Изменения применены.") if ok else _("Не удалось применить."),
                                  text_color=self.p.ok if ok else self.p.fail)

    def _restart_err(self, e: BaseException) -> None:
        self._restart_btn.configure(state="normal", text=_("Применить изменения"))
        self._err(e)

    # ----- single-strategy test ----------------------------------------

    def _run_test(self) -> None:
        opts = self._cmd.get().strip()
        if not opts:
            self._save_note.configure(text=_("Сначала выберите или введите стратегию."), text_color=self.p.warn)
            return
        self._test_btn.configure(state="disabled", text=_("Тестирую…"))
        self._clear_out()
        client = self._client
        run_async(self, lambda: zp.run_test(client, opts), self._show_test, self._test_err)

    def _test_err(self, e: BaseException) -> None:
        self._test_btn.configure(state="normal", text=_("▶ Тест текущей"))
        self._err(e)

    def _show_test(self, res: dict[str, Any]) -> None:
        p = self.p
        self._test_btn.configure(state="normal", text=_("▶ Тест текущей"))
        self._show_out()
        if "error" in res:
            ctk.CTkLabel(self._test_out, text=res["error"], font=fonts.body(),
                         text_color=p.fail).grid(row=0, column=0, sticky="w")
            return
        results = res.get("results", [])
        for i, r in enumerate(results):
            ok = bool(r.get("ok"))
            dot = "●" if ok else "○"
            reason = "" if ok else f"  ({_(_REASON.get(r.get('reason'), r.get('reason') or '—'))})"
            ctk.CTkLabel(self._test_out, text=f"{dot}  {r.get('label')}{reason}", font=fonts.body(),
                         text_color=(p.ok if ok else p.fail), anchor="w").grid(
                row=i, column=0, sticky="w", pady=1)
        passed, total = res.get("passed", 0), res.get("total", len(results))
        ctk.CTkLabel(self._test_out, text=_("Пройдено: {0} из {1}").format(passed, total), font=fonts.small(),
                     text_color=p.text_muted).grid(row=len(results), column=0, sticky="w", pady=(6, 0))

    # ----- full sweep (client-driven loop, page/window-bound) ----------

    def _full_start(self) -> None:
        if self._full_running:
            return
        if not self._cands:
            self._full_note.configure(text=_("Список стратегий недоступен."), text_color=self.p.warn)
            return
        self._full_running = True
        self._full_stop = False
        self._full_passed = 0
        self._full_btn.configure(state="disabled")
        self._stop_btn.grid(row=0, column=2, padx=(8, 0))
        self._clear_out()
        self._show_out()
        self._full_next(0)

    def _full_stop_click(self) -> None:
        self._full_stop = True
        self._stop_btn.configure(state="disabled")

    def _full_next(self, i: int) -> None:
        n = len(self._cands)
        if self._full_stop or i >= n:
            self._full_finish(stopped=self._full_stop)
            return
        cand = self._cands[i]
        self._full_note.configure(text=_("Проверка {0}/{1}: {2}").format(i + 1, n, cand['name']), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: zp.run_test(client, cand["args"]),
                  lambda res, idx=i: self._full_row(idx, res),
                  lambda e, idx=i: self._full_row(idx, {"error": str(e)}))

    def _full_row(self, i: int, res: dict[str, Any]) -> None:
        p = self.p
        cand = self._cands[i]
        passed = 0 if res.get("error") else res.get("passed", 0)
        total = res.get("total", 0)
        ok = passed > 0 and not res.get("error")
        if ok:
            self._full_passed += 1
        line = ctk.CTkFrame(self._test_out, fg_color="transparent")
        line.grid(row=i, column=0, sticky="ew", pady=1)
        line.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(line, text=("✓" if ok else "✗"), font=fonts.body(),
                     text_color=(p.ok if ok else p.text_muted), width=18).grid(row=0, column=0, sticky="w")
        detail = res["error"] if res.get("error") else f"{passed}/{total}"
        ctk.CTkLabel(line, text=f"{cand['name']}  ({detail})", font=fonts.small(),
                     text_color=p.text, anchor="w").grid(row=0, column=1, sticky="w", padx=(4, 0))
        if ok:
            ctk.CTkButton(line, text=_("Применить"), font=fonts.small(), width=92, fg_color=p.accent,
                          text_color=p.accent_fg, hover_color=p.accent_hover,
                          command=lambda a=cand["args"], nm=cand["name"]: self._apply_full(a, nm)).grid(
                row=0, column=2, padx=(8, 0))
        self._full_next(i + 1)

    def _apply_full(self, args: str, name: str) -> None:
        self._cmd.delete(0, "end")
        self._cmd.insert(0, args)
        client = self._client
        run_async(self, lambda: zp.set_cmd_opts(client, args),
                  lambda _r: self._save_note.configure(
                      text=_("Применено: {0} — нажмите «Применить изменения».").format(name), text_color=self.p.ok),
                  self._err)

    def _full_finish(self, stopped: bool) -> None:
        self._full_running = False
        self._full_btn.configure(state="normal")
        self._stop_btn.grid_forget()
        self._stop_btn.configure(state="normal")
        self._full_note.configure(
            text=_("{0} — пройдено {1}/{2}").format('Остановлено' if stopped else 'Готово', self._full_passed, len(self._cands)),
            text_color=(self.p.warn if stopped else self.p.ok))
