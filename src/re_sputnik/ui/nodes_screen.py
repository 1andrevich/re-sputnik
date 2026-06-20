# SPDX-License-Identifier: GPL-2.0-only
"""Nodes & subscriptions section.

Subscriptions (list / add / update-all / remove), WireGuard-AmneziaWG .conf
import (file → push → import_conf.uc), and a read-only node list. All work goes
through the router's own scripts via engine.nodes; all calls run off the Tk
thread.
"""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ..engine import nodes as nodes_engine
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async


class NodesScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=0, column=0, padx=24, pady=16, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self._body, text="Ключи и подписки VPN", font=fonts.title(), text_color=palette.text,
                     image=kit.icon(kit._ICON_FOR["nodes"], 26), compound="left").grid(
            row=0, column=0, pady=(4, 6), sticky="w"
        )
        ctk.CTkLabel(
            self._body,
            text="Подписка — это ссылка (URL) от VPN-сервиса: приложение само скачивает по ней "
            "список серверов и периодически обновляет его. Ключ — это один конкретный сервер "
            "в виде строки (vless://, hysteria2://, ss://…) или файла .conf, который вы "
            "добавляете вручную.",
            font=fonts.small(), text_color=palette.text_muted, wraplength=620, justify="left",
            anchor="w").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._status = ctk.CTkLabel(self._body, text="", font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w", wraplength=600, justify="left")
        self._status.grid(row=2, column=0, sticky="w", pady=(0, 8))
        self._status.grid_remove()  # collapses while empty — no gap before the cards

        self._subs_card = self._card("Подписки", 3, "links")
        self._links_card = self._card("Ключи / ссылки", 4, "file")
        self._conf_card = self._card("WireGuard / AmneziaWG", 5, "file")
        self._nodes_card = self._card("Серверы", 6, "nodes")
        self._build_subs_card()
        self._build_links_card()
        self._build_conf_card()
        self.refresh()

    # ----- helpers ------------------------------------------------------

    def _card(self, title: str, row: int, icon: str = "") -> ctk.CTkFrame:
        card = ctk.CTkFrame(self._body, fg_color=self.p.surface, corner_radius=12)
        card.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        card.grid_columnconfigure(0, weight=1)
        if icon:
            kit.SectionHeader(card, self.p, icon, title).grid(
                row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        else:
            ctk.CTkLabel(card, text=title, font=fonts.heading(), text_color=self.p.text).grid(
                row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        return card

    def _status_color(self, kind: str) -> str:
        return {"muted": self.p.text_muted, "ok": self.p.ok,
                "warn": self.p.warn, "fail": self.p.fail}[kind]

    def _set_status(self, text: str, kind: str = "muted") -> None:
        # Top line — used only for the screen-level load (refresh). Per-action
        # results live next to their own buttons (see the *_status labels below).
        self._status.configure(text=text, text_color=self._status_color(kind))
        # Only occupy space when there's actually a message to show.
        self._status.grid() if text else self._status.grid_remove()

    def _big_status_label(self, parent: ctk.CTkBaseClass) -> ctk.CTkLabel:
        """A larger, bold result label placed next to an action button."""
        return ctk.CTkLabel(parent, text="", font=ctk.CTkFont(size=15, weight="bold"),
                            text_color=self.p.text_muted, anchor="w", justify="left", wraplength=380)

    # ----- refresh (subscriptions + nodes) ------------------------------

    def refresh(self) -> None:
        self._set_status("Считываю подписки и серверы…")
        client = self._client

        def task() -> dict[str, Any]:
            return {
                "subs": nodes_engine.list_subscriptions(client),
                "nodes": nodes_engine.list_nodes(client),
                "autoupdate": nodes_engine.get_subscription_autoupdate(client),
            }

        run_async(self, task, self._render, self._on_error)

    def _on_error(self, exc: BaseException) -> None:
        self._set_status(f"Ошибка: {exc}", "fail")

    def _render(self, data: dict[str, Any]) -> None:
        self._set_status("")
        self._render_subs(data["subs"])
        self._render_nodes(data["nodes"])
        enabled, hour = data["autoupdate"]
        self._autoupd_var.set("1" if enabled else "0")  # setting the var doesn't fire the command
        self._autoupd_time.set(f"{hour:02d}:00")
        self._autoupd_time.configure(state="normal" if enabled else "disabled")

    def _on_autoupd(self) -> None:
        enabled = self._autoupd_var.get() == "1"
        try:
            hour = int(self._autoupd_time.get().split(":")[0])
        except ValueError:
            hour = 2
        self._autoupd_time.configure(state="normal" if enabled else "disabled")
        self._set_subs_status(
            f"Автообновление включено — ежедневно в {hour:02d}:00." if enabled
            else "Автообновление выключено.", "muted")
        client = self._client
        run_async(self, lambda: nodes_engine.set_subscription_autoupdate(client, enabled, hour),
                  lambda _r: None, self._subs_err)

    # ----- subscriptions ------------------------------------------------

    def _build_subs_card(self) -> None:
        """Static parts of the subscriptions card (list area + add/update controls +
        a result label). Only the list area is rebuilt on refresh, so the status
        message survives a reload."""
        p = self.p
        self._subs_list = ctk.CTkFrame(self._subs_card, fg_color="transparent")
        self._subs_list.grid(row=1, column=0, sticky="ew")
        self._subs_list.grid_columnconfigure(0, weight=1)

        add_row = ctk.CTkFrame(self._subs_card, fg_color="transparent")
        add_row.grid(row=2, column=0, padx=12, pady=(8, 12), sticky="ew")
        add_row.grid_columnconfigure(0, weight=1)
        self._sub_entry = ctk.CTkEntry(add_row, font=fonts.body(),
                                       placeholder_text="Вставьте ссылку-подписку…")
        self._sub_entry.grid(row=0, column=0, padx=(0, 8), sticky="ew")
        ctk.CTkButton(add_row, text="+ Добавить", font=fonts.body(), width=110, fg_color=p.accent, text_color=p.accent_fg,
                      hover_color=p.accent_hover, command=self._add_sub).grid(row=0, column=1, padx=(0, 6))
        ctk.CTkButton(add_row, text=f"{kit.REFRESH_GLYPH} Обновить все", font=fonts.body(), width=140, fg_color=p.surface_hover,
                      hover_color=p.border, command=self._update_subs).grid(row=0, column=2)
        self._subs_status = self._big_status_label(add_row)
        self._subs_status.configure(wraplength=560)
        self._subs_status.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # Daily auto-update (the device's own cron: update_crond.sh at the chosen hour).
        au = ctk.CTkFrame(self._subs_card, fg_color="transparent")
        au.grid(row=3, column=0, padx=12, pady=(0, 12), sticky="w")
        self._autoupd_var = ctk.StringVar(value="0")
        self._autoupd_switch = ctk.CTkSwitch(
            au, text="Автообновление подписок", font=fonts.body(), variable=self._autoupd_var,
            onvalue="1", offvalue="0", progress_color=p.accent, button_color=p.accent_fg,
            command=self._on_autoupd)
        self._autoupd_switch.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(au, text="ежедневно в", font=fonts.small(), text_color=p.text_muted).grid(
            row=0, column=1, padx=(16, 6))
        self._autoupd_time = ctk.CTkOptionMenu(
            au, values=[f"{h:02d}:00" for h in range(24)], width=92, font=fonts.body(),
            fg_color=p.surface_hover, button_color=p.accent, button_hover_color=p.accent_hover,
            command=lambda _v: self._on_autoupd())
        self._autoupd_time.set("02:00")
        self._autoupd_time.configure(state="disabled")
        self._autoupd_time.grid(row=0, column=2)

    def _set_subs_status(self, text: str, kind: str = "muted") -> None:
        self._subs_status.configure(text=text, text_color=self._status_color(kind))

    def _subs_err(self, exc: BaseException) -> None:
        self._set_subs_status(f"Ошибка: {exc}", "fail")

    def _render_subs(self, subs: list[str]) -> None:
        p = self.p
        for w in self._subs_list.winfo_children():
            w.destroy()
        if not subs:
            ctk.CTkLabel(self._subs_list, text="Подписок нет.", font=fonts.small(),
                         text_color=p.text_muted).grid(row=0, column=0, padx=16, pady=2, sticky="w")
            return
        for i, url in enumerate(subs):
            line = ctk.CTkFrame(self._subs_list, fg_color="transparent")
            line.grid(row=i, column=0, padx=12, pady=2, sticky="ew")
            line.grid_columnconfigure(0, weight=1)
            shown = url if len(url) <= 70 else url[:67] + "…"
            ctk.CTkLabel(line, text="🔗 " + shown, font=fonts.body(), text_color=p.text,
                         anchor="w").grid(row=0, column=0, sticky="w")
            ctk.CTkButton(line, text="🗑", width=34, font=fonts.body(), fg_color="transparent",
                          hover_color=p.surface_hover,
                          command=lambda u=url: self._remove_sub(u)).grid(row=0, column=1)

    def _add_sub(self) -> None:
        url = self._sub_entry.get().strip()
        if not url:
            self._set_subs_status("Введите ссылку-подписку.", "warn")
            return
        client = self._client
        self._set_subs_status("Добавляю подписку…")
        run_async(self, lambda: nodes_engine.add_subscription(client, url),
                  lambda _r: self._subs_done("Подписка добавлена."), self._subs_err)

    def _remove_sub(self, url: str) -> None:
        client = self._client
        self._set_subs_status("Удаляю подписку…")
        run_async(self, lambda: nodes_engine.remove_subscription(client, url),
                  lambda _r: self._subs_done("Подписка удалена."), self._subs_err)

    def _subs_done(self, msg: str) -> None:
        self._set_subs_status(msg, "ok")
        self.refresh()

    def _update_subs(self) -> None:
        client = self._client
        self._set_subs_status("Обновляю подписки (загрузка и импорт)…")
        run_async(self, lambda: nodes_engine.update_subscriptions(client), self._after_update, self._subs_err)

    def _after_update(self, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            self._set_subs_status("Не удалось обновить подписки. Подробности в логе роутера.", "fail")
            self.refresh()
            return
        if result.get("added") is not None:
            msg = f"Подписки обновлены: добавлено {result['added']}, удалено {result['removed']}."
        else:
            msg = "Подписки обновлены."
        self._set_subs_status(msg, "ok")
        self.refresh()

    # ----- key / share-link import --------------------------------------

    def _build_links_card(self) -> None:
        p = self.p
        ctk.CTkLabel(self._links_card,
                     text="Вставьте ссылку-ключ (vless:// vmess:// hysteria2:// trojan:// ss:// "
                     "vpn:// …), по одной в строке:",
                     font=fonts.small(), text_color=p.text_muted, wraplength=600,
                     justify="left").grid(row=1, column=0, padx=16, sticky="w")
        self._links_box = ctk.CTkTextbox(self._links_card, font=ctk.CTkFont(family="Consolas", size=12),
                                         fg_color=p.bg, text_color=p.text, height=70, wrap="none")
        self._links_box.grid(row=2, column=0, padx=16, pady=(6, 6), sticky="ew")
        actions = ctk.CTkFrame(self._links_card, fg_color="transparent")
        actions.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="ew")
        actions.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(actions, text="+ Импортировать ключи", font=fonts.body(),
                      fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                      command=self._import_links).grid(row=0, column=0, sticky="w")
        # Import result is shown right here, next to the button, in a larger font —
        # not in the small status line at the very top of the screen.
        self._links_status = ctk.CTkLabel(actions, text="", font=ctk.CTkFont(size=15, weight="bold"),
                                          text_color=p.text_muted, anchor="w", justify="left",
                                          wraplength=380)
        self._links_status.grid(row=0, column=1, padx=(14, 0), sticky="w")

    def _set_links_status(self, text: str, kind: str = "muted") -> None:
        color = {"muted": self.p.text_muted, "ok": self.p.ok,
                 "warn": self.p.warn, "fail": self.p.fail}[kind]
        self._links_status.configure(text=text, text_color=color)

    def _links_err(self, exc: BaseException) -> None:
        self._set_links_status(f"Ошибка: {exc}", "fail")

    def _import_links(self) -> None:
        text = self._links_box.get("1.0", "end").strip()
        if not text:
            self._set_links_status("Вставьте хотя бы одну ссылку.", "warn")
            return
        client = self._client
        self._set_links_status("Импортирую ключи…")
        # import_mixed_links routes vpn:// (decoded on the PC) and ordinary
        # share-links to the right importer — one paste can mix both.
        from ..engine import vpn_link
        run_async(self, lambda: vpn_link.import_mixed_links(client, text),
                  self._after_links, self._links_err)

    def _after_links(self, res: dict[str, Any]) -> None:
        imported = res.get("imported") or 0
        failed = res.get("failed") or 0
        if imported == 0 and failed:
            errs = "; ".join(res.get("errors") or []) or "нет валидных ссылок"
            self._set_links_status(f"Импорт не удался: {errs[:140]}", "fail")
            return
        msg = f"Импортировано: {imported}, пропущено: {failed}."
        if res.get("errors"):
            msg += " " + "; ".join(res["errors"])[:100]
        self._set_links_status(msg, "ok" if imported else "warn")
        self._links_box.delete("1.0", "end")
        self.refresh()

    # ----- .conf import -------------------------------------------------

    def _build_conf_card(self) -> None:
        p = self.p
        ctk.CTkLabel(self._conf_card,
                     text="Импорт конфигурации WireGuard / AmneziaWG (.conf):",
                     font=fonts.small(), text_color=p.text_muted).grid(row=1, column=0, padx=16, sticky="w")
        actions = ctk.CTkFrame(self._conf_card, fg_color="transparent")
        actions.grid(row=2, column=0, padx=16, pady=(6, 12), sticky="ew")
        actions.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(actions, text="📄 Выбрать .conf файл", font=fonts.body(),
                      fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                      command=self._pick_conf).grid(row=0, column=0, sticky="w")
        self._conf_status = self._big_status_label(actions)
        self._conf_status.grid(row=0, column=1, padx=(14, 0), sticky="w")

    def _set_conf_status(self, text: str, kind: str = "muted") -> None:
        self._conf_status.configure(text=text, text_color=self._status_color(kind))

    def _conf_err(self, exc: BaseException) -> None:
        self._set_conf_status(f"Ошибка: {exc}", "fail")

    def _pick_conf(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("WireGuard conf", "*.conf"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self._set_conf_status(f"Не удалось прочитать файл: {exc}", "fail")
            return
        label = Path(path).stem
        client = self._client
        self._set_conf_status(f"Импортирую {label}…")
        run_async(self, lambda: nodes_engine.import_conf(client, text, label), self._after_conf, self._conf_err)

    def _after_conf(self, result: dict[str, Any]) -> None:
        if result.get("result"):
            self._set_conf_status(
                f"Импортировано: {result.get('label') or result.get('section')} ({result.get('type')})", "ok"
            )
            self.refresh()
        else:
            self._set_conf_status(f"Импорт не удался: {result.get('error', 'неизвестная ошибка')}", "fail")

    # ----- node list ----------------------------------------------------

    # Show newest-first, scroll through up to this many; collapse the rest. Matches
    # the quick-setup node list so both surfaces behave the same.
    _MAX_NODES = 254

    def _render_nodes(self, nodes: list[nodes_engine.Node]) -> None:
        p = self.p
        for w in self._nodes_card.grid_slaves():
            if int(w.grid_info()["row"]) > 0:
                w.destroy()
        ctk.CTkLabel(self._nodes_card, text=f"Всего серверов: {len(nodes)}", font=fonts.small(),
                     text_color=p.text_muted).grid(row=1, column=0, padx=16, pady=(0, 4), sticky="w")
        # Newest first: list_nodes returns uci insertion order (oldest → newest),
        # so reverse it — freshly imported nodes appear at the top.
        ordered = list(reversed(nodes))
        shown = ordered[:self._MAX_NODES]
        listbox = ctk.CTkScrollableFrame(self._nodes_card, fg_color=p.bg, height=260)
        listbox.grid(row=2, column=0, padx=12, pady=(0, 12), sticky="ew")
        listbox.grid_columnconfigure(0, weight=1)
        for i, node in enumerate(shown):
            label = node.label or node.section
            ctk.CTkLabel(listbox, text=f"• {label}", font=fonts.body(), text_color=p.text,
                         anchor="w").grid(row=i, column=0, padx=6, pady=1, sticky="w")
            ctk.CTkLabel(listbox, text=node.type, font=fonts.small(), text_color=p.text_muted,
                         anchor="e").grid(row=i, column=1, padx=8, pady=1, sticky="e")
        if len(ordered) > self._MAX_NODES:
            ctk.CTkLabel(self._nodes_card, text=f"…и ещё {len(ordered) - self._MAX_NODES} серверов",
                         font=fonts.small(), text_color=p.text_muted).grid(
                row=3, column=0, padx=16, pady=(0, 10), sticky="w")
