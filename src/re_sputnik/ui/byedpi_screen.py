# SPDX-License-Identifier: GPL-2.0-only
"""ByeDPI section — status, strategy, and the live strategy test."""

from __future__ import annotations

from typing import Any

import customtkinter as ctk

from ..engine import byedpi as bd
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async

_REASON = {"dns": "DNS", "refused": "отказ", "timeout": "таймаут", "tls": "TLS", "fail": "сбой"}


class ByeDPIScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=0, column=0, padx=24, pady=16, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self._body, text="ByeDPI", font=fonts.title(), text_color=palette.text,
                     image=kit.icon(kit._ICON_FOR["byedpi"], 26), compound="left").grid(
            row=0, column=0, pady=(4, 4), sticky="w")
        ctk.CTkLabel(self._body, text="Обход DPI для сервисов, где не нужен полный VPN.",
                     font=fonts.small(), text_color=palette.text_muted).grid(row=1, column=0, sticky="w")
        self._status = ctk.CTkLabel(self._body, text="Считываю ByeDPI…", font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w")
        self._status.grid(row=2, column=0, sticky="w", pady=(6, 8))

        self._status_card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._status_card.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self._status_card.grid_columnconfigure(1, weight=1)
        self._cfg_card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._cfg_card.grid(row=4, column=0, sticky="ew", pady=(0, 12))
        self._cfg_card.grid_columnconfigure(0, weight=1)
        self._test_card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._test_card.grid(row=5, column=0, sticky="ew")
        self._test_card.grid_columnconfigure(0, weight=1)
        self.refresh()

    # ----- read ---------------------------------------------------------

    def refresh(self) -> None:
        client = self._client

        def task() -> dict[str, Any]:
            return {"status": bd.get_status(client), "config": bd.get_config(client)}

        run_async(self, task, self._render, self._err)

    def _err(self, e: BaseException) -> None:
        self._status.configure(text=f"Ошибка: {e}", text_color=self.p.fail)

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
            text=("🟢 установлен и запущен" if running else
                  ("🟡 установлен, остановлен" if installed else "🔴 не установлен"))
            + (f"  ·  ciadpi {st.get('version')}" if st.get("version") else ""),
            text_color=(p.ok if running else (p.warn if installed else p.fail)))

        # Status rows.
        rows = [("Версия", st.get("version") or "—"), ("Архитектура", st.get("arch") or "—")]
        for i, (k, v) in enumerate(rows):
            ctk.CTkLabel(self._status_card, text=k, font=fonts.small(), text_color=p.text_muted).grid(
                row=i, column=0, padx=(16, 12), pady=3, sticky="w")
            ctk.CTkLabel(self._status_card, text=v, font=fonts.body(), text_color=p.text, anchor="e").grid(
                row=i, column=1, padx=(0, 16), pady=3, sticky="e")

        # Config card: enable switch + strategy field.
        self._enabled = ctk.StringVar(value="1" if cfg["enabled"] else "0")
        ctk.CTkSwitch(self._cfg_card, text="Включить ByeDPI", font=fonts.body(), variable=self._enabled,
                      onvalue="1", offvalue="0", progress_color=p.accent,
                      command=self._on_enable).grid(row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        # Strategy preset picker — fills the args field; manual edits still allowed.
        ctk.CTkLabel(self._cfg_card, text="Готовая стратегия:", font=fonts.small(),
                     text_color=p.text_muted).grid(row=1, column=0, padx=16, pady=(0, 0), sticky="w")
        self._presets = {name: args for name, args in bd.STRATEGY_PRESETS}
        self._preset_menu = ctk.CTkOptionMenu(
            self._cfg_card, values=["— выбрать —", *self._presets.keys()], font=fonts.body(),
            fg_color=p.surface_hover, button_color=p.accent, button_hover_color=p.accent_hover,
            command=self._on_preset, dynamic_resizing=False, width=320)
        self._preset_menu.set("— выбрать —")
        self._preset_menu.grid(row=2, column=0, padx=16, pady=(2, 6), sticky="w")

        ctk.CTkLabel(self._cfg_card, text="Стратегия (аргументы ciadpi):", font=fonts.small(),
                     text_color=p.text_muted).grid(row=3, column=0, padx=16, sticky="w")
        self._cmd = ctk.CTkEntry(self._cfg_card, font=ctk.CTkFont(family="Consolas", size=12))
        self._cmd.insert(0, cfg["cmd_opts"])
        self._cmd.grid(row=4, column=0, padx=16, pady=(4, 6), sticky="ew")
        row = ctk.CTkFrame(self._cfg_card, fg_color="transparent")
        row.grid(row=5, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(row, text="Сохранить стратегию", font=fonts.body(), fg_color=p.accent, text_color=p.accent_fg,
                      hover_color=p.accent_hover, command=self._save_cmd).grid(row=0, column=0)
        self._restart_btn = ctk.CTkButton(row, text="Применить изменения", font=fonts.body(),
                                          fg_color=p.surface_hover, hover_color=p.border,
                                          command=self._restart_service)
        self._restart_btn.grid(row=0, column=1, padx=(8, 0))
        self._save_note = ctk.CTkLabel(row, text="", font=fonts.small(), text_color=p.text_muted)
        self._save_note.grid(row=0, column=2, padx=10)

        # Test card.
        kit.SectionHeader(self._test_card, p, "strategy", "Тест стратегии").grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(self._test_card, text="● = TLS-рукопожатие успешно, ○ = заблокировано",
                     font=fonts.small(), text_color=p.text_muted).grid(row=1, column=0, padx=16, sticky="w")
        self._test_btn = ctk.CTkButton(self._test_card, text="▶ Запустить тест", font=fonts.body(),
                                       fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover, command=self._run_test)
        self._test_btn.grid(row=2, column=0, padx=16, pady=(8, 6), sticky="w")
        self._test_out = ctk.CTkFrame(self._test_card, fg_color="transparent")
        self._test_out.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")

    # ----- edits --------------------------------------------------------

    def _on_preset(self, name: str) -> None:
        args = self._presets.get(name)
        if not args:
            return
        self._cmd.delete(0, "end")
        self._cmd.insert(0, args)
        self._save_note.configure(text="Стратегия подставлена — нажмите «Сохранить».",
                                  text_color=self.p.text_muted)

    def _on_enable(self) -> None:
        on = self._enabled.get() == "1"
        client = self._client
        run_async(self, lambda: bd.set_enabled(client, on),
                  lambda _r: self._save_note.configure(
                      text="Изменено — нажмите «Применить изменения».", text_color=self.p.warn),
                  self._err)

    def _save_cmd(self) -> None:
        opts = self._cmd.get().strip()
        client = self._client
        run_async(self, lambda: bd.set_cmd_opts(client, opts),
                  lambda _r: self._save_note.configure(
                      text="Сохранено — нажмите «Применить изменения».", text_color=self.p.warn),
                  self._err)

    def _restart_service(self) -> None:
        self._restart_btn.configure(state="disabled", text="Применяю…")
        client = self._client
        run_async(self, lambda: bd.restart_service(client), self._restarted, self._restart_err)

    def _restarted(self, ok: bool) -> None:
        self._restart_btn.configure(state="normal", text="Применить изменения")
        self._save_note.configure(text="Изменения применены." if ok else "Не удалось применить.",
                                  text_color=self.p.ok if ok else self.p.fail)

    def _restart_err(self, e: BaseException) -> None:
        self._restart_btn.configure(state="normal", text="Применить изменения")
        self._err(e)

    # ----- test ---------------------------------------------------------

    def _run_test(self) -> None:
        opts = self._cmd.get().strip() or "--disorder 1"
        self._test_btn.configure(state="disabled", text="Тестирую… (до минуты)")
        for w in self._test_out.winfo_children():
            w.destroy()
        client = self._client
        run_async(self, lambda: bd.run_test(client, opts), self._show_test, self._test_err)

    def _test_err(self, e: BaseException) -> None:
        self._test_btn.configure(state="normal", text="▶ Запустить тест")
        self._err(e)

    def _show_test(self, res: dict[str, Any]) -> None:
        p = self.p
        self._test_btn.configure(state="normal", text="▶ Запустить тест")
        if "error" in res:
            ctk.CTkLabel(self._test_out, text=res["error"], font=fonts.body(),
                         text_color=p.fail).grid(row=0, column=0, sticky="w")
            return
        results = res.get("results", [])
        for i, r in enumerate(results):
            ok = bool(r.get("ok"))
            dot = "●" if ok else "○"
            reason = "" if ok else f"  ({_REASON.get(r.get('reason'), r.get('reason') or '')})"
            ctk.CTkLabel(self._test_out, text=f"{dot}  {r.get('label')}{reason}", font=fonts.body(),
                         text_color=(p.ok if ok else p.fail), anchor="w").grid(
                row=i, column=0, sticky="w", pady=1)
        passed, total = res.get("passed", 0), res.get("total", len(results))
        ctk.CTkLabel(self._test_out, text=f"Пройдено: {passed} из {total}", font=fonts.small(),
                     text_color=p.text_muted).grid(row=len(results), column=0, sticky="w", pady=(6, 0))
