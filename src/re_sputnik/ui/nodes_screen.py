# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
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
from . import flags
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import _


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

        ctk.CTkLabel(self._body, text=_("Ключи и подписки VPN"), font=fonts.title(), text_color=palette.text,
                     image=kit.icon(kit.ICON_FOR["nodes"], 26), compound="left").grid(
            row=0, column=0, pady=(4, 6), sticky="w"
        )
        ctk.CTkLabel(
            self._body,
            text=_("Подписка — это ссылка (URL) от VPN-сервиса: приложение само скачивает по ней "
            "список серверов и периодически обновляет его. Ключ — это один конкретный сервер "
            "в виде строки (vless://, hysteria2://, ss://…) или файла .conf, который вы "
            "добавляете вручную."),
            font=fonts.small(), text_color=palette.text_muted, wraplength=620, justify="left",
            anchor="w").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._status = ctk.CTkLabel(self._body, text="", font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w", wraplength=600, justify="left")
        self._status.grid(row=2, column=0, sticky="w", pady=(0, 8))
        self._status.grid_remove()  # collapses while empty — no gap before the cards

        self._input_card = self._card(_("Ключи и подписки"), 3, "links")
        self._conf_card = self._card("WireGuard / AmneziaWG", 4, "file")
        self._nodes_card = self._card(_("Серверы"), 5, "nodes")
        self._build_input_card()
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
        self._set_status(_("Считываю подписки и серверы…"))
        client = self._client

        def task() -> dict[str, Any]:
            return {
                "subs": nodes_engine.list_subscriptions(client),
                "nodes": nodes_engine.list_nodes(client),
                "autoupdate": nodes_engine.get_subscription_autoupdate(client),
            }

        run_async(self, task, self._render, self._on_error)

    def _on_error(self, exc: BaseException) -> None:
        self._set_status(_("Ошибка: {0}").format(exc), "fail")

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
            _("Автообновление включено — ежедневно в {hour}:00.").format(hour=f"{hour:02d}") if enabled
            else _("Автообновление выключено."), "muted")
        client = self._client
        run_async(self, lambda: nodes_engine.set_subscription_autoupdate(client, enabled, hour),
                  lambda _r: None, self._subs_err)

    # ----- subscriptions ------------------------------------------------

    def _build_input_card(self) -> None:
        """One paste field for BOTH subscriptions and keys (auto-classified), the
        saved-subscriptions list, the update controls and the auto-update toggle.
        Only the list area is rebuilt on refresh, so the status message survives a
        reload."""
        p = self.p
        card = self._input_card

        ctk.CTkLabel(
            card,
            text=_("Вставьте сюда либо ссылку-подписку (начинается с http:// или https://), "
            "либо ключи отдельных серверов (vless:// vmess:// hysteria2:// trojan:// "
            "ss:// vpn:// …) — по одному в строке. Приложение само определит, где "
            "подписка, а где ключ."),
            font=fonts.small(), text_color=p.text_muted, wraplength=600, justify="left"
        ).grid(row=1, column=0, padx=16, pady=(0, 2), sticky="w")

        self._input_box = ctk.CTkTextbox(card, font=fonts.mono(12),
                                         fg_color=p.bg, text_color=p.text, height=74, wrap="none")
        self._input_box.grid(row=2, column=0, padx=16, pady=(6, 6), sticky="ew")

        add_row = ctk.CTkFrame(card, fg_color="transparent")
        add_row.grid(row=3, column=0, padx=12, pady=(0, 8), sticky="ew")
        add_row.grid_columnconfigure(2, weight=1)
        ctk.CTkButton(add_row, text=_("+ Добавить"), font=fonts.body(), width=130, fg_color=p.accent,
                      text_color=p.accent_fg, hover_color=p.accent_hover,
                      command=self._add_input).grid(row=0, column=0, padx=(4, 6))
        ctk.CTkButton(add_row, text=_("{0} Обновить все").format(kit.REFRESH_GLYPH), font=fonts.body(), width=140,
                      fg_color=p.surface_hover, hover_color=p.border,
                      command=self._update_subs).grid(row=0, column=1)
        self._subs_status = self._big_status_label(add_row)
        self._subs_status.configure(wraplength=560)
        self._subs_status.grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 0))

        # Saved subscriptions (managed list — each with a delete button).
        self._subs_list = ctk.CTkFrame(card, fg_color="transparent")
        self._subs_list.grid(row=4, column=0, sticky="ew", pady=(2, 0))
        self._subs_list.grid_columnconfigure(0, weight=1)

        # Daily auto-update (the device's own cron: update_crond.sh at the chosen hour).
        au = ctk.CTkFrame(card, fg_color="transparent")
        au.grid(row=5, column=0, padx=12, pady=(4, 12), sticky="w")
        self._autoupd_var = ctk.StringVar(value="0")
        self._autoupd_switch = ctk.CTkSwitch(
            au, text=_("Автообновление подписок"), font=fonts.body(), variable=self._autoupd_var,
            onvalue="1", offvalue="0", progress_color=p.accent, button_color=p.accent_fg,
            command=self._on_autoupd)
        self._autoupd_switch.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(au, text=_("ежедневно в"), font=fonts.small(), text_color=p.text_muted).grid(
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
        self._set_subs_status(_("Ошибка: {0}").format(exc), "fail")

    def _render_subs(self, subs: list[str]) -> None:
        p = self.p
        for w in self._subs_list.winfo_children():
            w.destroy()
        if not subs:
            ctk.CTkLabel(self._subs_list, text=_("Подписок нет."), font=fonts.small(),
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

    def _add_input(self) -> None:
        text = self._input_box.get("1.0", "end").strip()
        if not text:
            self._set_subs_status(_("Вставьте ссылку-подписку или ключ сервера."), "warn")
            return
        client = self._client
        self._set_subs_status(_("Добавляю…"))
        from ..engine import vpn_link
        # add_mixed_input sorts each line: http(s):// → subscription, the rest → key
        # import; new subscriptions are fetched right away (fetch=True).
        run_async(self, lambda: vpn_link.add_mixed_input(client, text, fetch=True),
                  self._after_input, self._subs_err)

    def _after_input(self, res: dict[str, Any]) -> None:
        subs_added = res.get("subs_added") or 0
        imported = res.get("imported") or 0
        failed = res.get("failed") or 0
        errors = res.get("errors") or []
        parts: list[str] = []
        if subs_added:
            parts.append(_("подписок добавлено: {0}").format(subs_added))
        upd = res.get("update")
        if upd and upd.get("ok") and upd.get("added") is not None:
            parts.append(_("серверов из подписок: +{0} / −{1}").format(upd['added'], upd['removed']))
        if imported:
            parts.append(_("ключей импортировано: {0}").format(imported))
        if failed:
            parts.append(_("пропущено: {0}").format(failed))
        if not parts and not errors:
            self._set_subs_status(_("Ничего не распознано — проверьте формат ссылок."), "warn")
            return
        msg = (_("Готово — ") + ", ".join(parts) + ".") if parts else _("Не удалось добавить.")
        if errors:
            msg += " " + "; ".join(errors)[:140]
        self._set_subs_status(msg, "ok" if (subs_added or imported) else "warn")
        self._input_box.delete("1.0", "end")
        self.refresh()

    def _remove_sub(self, url: str) -> None:
        client = self._client
        self._set_subs_status(_("Удаляю подписку…"))
        run_async(self, lambda: nodes_engine.remove_subscription(client, url),
                  lambda _r: self._subs_done(_("Подписка удалена.")), self._subs_err)

    def _subs_done(self, msg: str) -> None:
        self._set_subs_status(msg, "ok")
        self.refresh()

    def _delete_node(self, section: str, label: str) -> None:
        client = self._client
        self._set_status(_("Удаляю сервер «{0}»…").format(label))
        run_async(self, lambda: nodes_engine.delete_node(client, section),
                  lambda _r: self.refresh(), self._subs_err)

    def _update_subs(self) -> None:
        client = self._client
        self._set_subs_status(_("Обновляю подписки (загрузка и импорт)…"))
        run_async(self, lambda: nodes_engine.update_subscriptions(client), self._after_update, self._subs_err)

    def _after_update(self, result: dict[str, Any]) -> None:
        if not result.get("ok"):
            self._set_subs_status(_("Не удалось обновить подписки. Подробности в логе роутера."), "fail")
            self.refresh()
            return
        if result.get("added") is not None:
            msg = _("Подписки обновлены: добавлено {0}, удалено {1}.").format(result['added'], result['removed'])
        else:
            msg = _("Подписки обновлены.")
        self._set_subs_status(msg, "ok")
        self.refresh()

    # ----- .conf import -------------------------------------------------

    def _build_conf_card(self) -> None:
        p = self.p
        ctk.CTkLabel(self._conf_card,
                     text=_("Импорт конфигурации WireGuard / AmneziaWG (.conf):"),
                     font=fonts.small(), text_color=p.text_muted).grid(row=1, column=0, padx=16, sticky="w")
        actions = ctk.CTkFrame(self._conf_card, fg_color="transparent")
        actions.grid(row=2, column=0, padx=16, pady=(6, 12), sticky="ew")
        actions.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(actions, text=_("📄 Выбрать .conf файл"), font=fonts.body(),
                      fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                      command=self._pick_conf).grid(row=0, column=0, sticky="w")
        self._conf_status = self._big_status_label(actions)
        self._conf_status.grid(row=0, column=1, padx=(14, 0), sticky="w")

    def _set_conf_status(self, text: str, kind: str = "muted") -> None:
        self._conf_status.configure(text=text, text_color=self._status_color(kind))

    def _conf_err(self, exc: BaseException) -> None:
        self._set_conf_status(_("Ошибка: {0}").format(exc), "fail")

    def _pick_conf(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("WireGuard conf", "*.conf"), (_("Все файлы"), "*.*")])
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            self._set_conf_status(_("Не удалось прочитать файл: {0}").format(exc), "fail")
            return
        label = Path(path).stem
        client = self._client
        self._set_conf_status(_("Импортирую {0}…").format(label))
        run_async(self, lambda: nodes_engine.import_conf(client, text, label), self._after_conf, self._conf_err)

    def _after_conf(self, result: dict[str, Any]) -> None:
        if result.get("result"):
            self._set_conf_status(
                _("Импортировано: {0} ({1})").format(result.get('label') or result.get('section'), result.get('type')), "ok"
            )
            self.refresh()
        else:
            self._set_conf_status(_("Импорт не удался: {0}").format(result.get('error', 'неизвестная ошибка')), "fail")

    # ----- node list ----------------------------------------------------

    # Show newest-first, scroll through up to this many; collapse the rest. Matches
    # the quick-setup node list so both surfaces behave the same.
    _MAX_NODES = 254

    def _render_nodes(self, nodes: list[nodes_engine.Node]) -> None:
        p = self.p
        for w in self._nodes_card.grid_slaves():
            if int(w.grid_info()["row"]) > 0:
                w.destroy()
        ctk.CTkLabel(self._nodes_card, text=_("Всего серверов: {0}").format(len(nodes)), font=fonts.small(),
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
            # flags.name_label draws the country flag as an image (Win/Linux) and
            # serves as the row marker; macOS keeps the emoji. No "•" bullet needed.
            flags.name_label(listbox, label, font=fonts.body(), text_color=p.text,
                             anchor="w").grid(row=i, column=0, padx=6, pady=1, sticky="w")
            ctk.CTkLabel(listbox, text=node.type, font=fonts.small(), text_color=p.text_muted,
                         anchor="e").grid(row=i, column=1, padx=8, pady=1, sticky="e")
            ctk.CTkButton(listbox, text="✕", width=30, font=fonts.body(), fg_color="transparent",
                          text_color=p.fail, hover_color=p.surface_hover,
                          command=lambda s=node.section, lbl=label: self._delete_node(s, lbl)).grid(
                          row=i, column=2, padx=(2, 4), pady=1)
        if len(ordered) > self._MAX_NODES:
            ctk.CTkLabel(self._nodes_card, text=_("…и ещё {0} серверов").format(len(ordered) - self._MAX_NODES),
                         font=fonts.small(), text_color=p.text_muted).grid(
                row=3, column=0, padx=16, pady=(0, 10), sticky="w")
