# SPDX-License-Identifier: GPL-2.0-only
"""Пошаговая настройка — phase «Серверы».

Guided: add a subscription URL or paste share-links/keys, import them via the
router's own scripts, then pick the main node — "Авто" (URLTest picks the
fastest) or a specific node — and apply. Reaching a main node is what flips the
router to CONFIGURED so the service actually proxies.
"""

from __future__ import annotations

import os
from tkinter import filedialog
from typing import Any, Callable, Optional

import customtkinter as ctk

from ..engine import nodes as nd
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import post_to, run_async

OnDone = Callable[[], None]

MAX_SUBS = 7  # cap on subscription URL rows
MAX_VISIBLE = 254  # cap on node rows shown in the list (rest collapsed to a tail)


class QuickNodesScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, on_done: OnDone, offline: bool = False, on_back: Optional[OnDone] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_done = on_done
        self._on_back = on_back
        # Offline staging (Option 3): subscriptions need internet, so hide them and
        # allow finishing with no nodes; locally-parsed imports (vpn:// / share-
        # links / .conf) still work and are pre-added for the hand-off.
        self._offline = offline
        self._nodes: list[nd.Node] = []
        # Only blame "0 servers" on a failed import AFTER the user actually tried
        # one — on the pristine first load an empty list just means nothing's been
        # added yet, not that a subscription was processed and yielded nothing.
        self._import_attempted = False
        self._main_mode = ctk.StringVar(value="urltest")
        self._whitelist = ctk.StringVar(value="0")  # "у меня белые списки" → RU-server pool

        self._sc = kit.WizardScaffold(self, palette, step=5, label="Серверы и подписки", footer=False)
        self._scroll = self._sc.content
        b = self._scroll

        title = "Серверы (офлайн-подготовка)" if offline else "Серверы и подписки"
        ctk.CTkLabel(b, text=title, font=fonts.title(), text_color=palette.text).grid(
            row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        # Plain-language intro: explain what a "сервер" is for a non-technical user.
        explainer = "Сервер (VPN/прокси) — это то, через что пойдёт ваш трафик. "
        intro = explainer + (
            "Вставьте ссылки-ключи (vless://, hysteria2://, vpn://…) или импортируйте "
            ".conf. Подписки добавятся позже, когда у роутера появится интернет."
            if offline else
            "Добавьте подписку или вставьте ссылки-ключи (vless://, hysteria2://…). "
            "Затем выберите основной сервер.")
        ctk.CTkLabel(b, text=intro, font=fonts.body(),
                     text_color=palette.text_muted, wraplength=560, justify="left").grid(
            row=1, column=0, pady=(0, 12), padx=32, sticky="w")

        # --- subscriptions (online only — need internet to fetch) ------
        # Up to MAX_SUBS URL rows; "＋" adds the next, "✕" removes one.
        self._sub_entries: list[ctk.CTkEntry] = []
        if not offline:
            sub = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
            sub.grid(row=2, column=0, padx=32, sticky="ew")
            sub.grid_columnconfigure(0, weight=1)
            kit.SectionHeader(sub, palette, "links", "Подписки (URL)").grid(
                row=0, column=0, padx=16, pady=(12, 4), sticky="w")
            self._sub_rows = ctk.CTkFrame(sub, fg_color="transparent")
            self._sub_rows.grid(row=1, column=0, padx=16, pady=2, sticky="ew")
            self._sub_rows.grid_columnconfigure(0, weight=1)
            sub_btns = ctk.CTkFrame(sub, fg_color="transparent")
            sub_btns.grid(row=2, column=0, padx=16, pady=(6, 12), sticky="w")
            self._sub_btn = ctk.CTkButton(sub_btns, text="Добавить и обновить", font=fonts.body(),
                                          fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                          command=self._do_sub)
            self._sub_btn.grid(row=0, column=0)
            self._sub_add = ctk.CTkButton(sub_btns, text="Добавить ещё одну подписку",
                                          font=fonts.small(), width=210,
                                          fg_color=palette.surface_hover, hover_color=palette.border,
                                          command=self._add_sub_row)
            self._sub_add.grid(row=0, column=1, padx=(8, 0))
            self._add_sub_row()  # start with one

            # Daily subscription auto-update (same as Advanced mode — a device cron).
            au = ctk.CTkFrame(sub, fg_color="transparent")
            au.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")
            self._autoupd_var = ctk.StringVar(value="0")
            self._autoupd_switch = ctk.CTkSwitch(
                au, text="Автообновление подписок", font=fonts.body(), variable=self._autoupd_var,
                onvalue="1", offvalue="0", progress_color=palette.accent,
                button_color=palette.accent_fg, command=self._on_autoupd)
            self._autoupd_switch.grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(au, text="ежедневно в", font=fonts.small(),
                         text_color=palette.text_muted).grid(row=0, column=1, padx=(16, 6))
            self._autoupd_time = ctk.CTkOptionMenu(
                au, values=[f"{h:02d}:00" for h in range(24)], width=92, font=fonts.body(),
                fg_color=palette.surface_hover, button_color=palette.accent,
                button_hover_color=palette.accent_hover, command=lambda _v: self._on_autoupd())
            self._autoupd_time.set("02:00")
            self._autoupd_time.configure(state="disabled")
            self._autoupd_time.grid(row=0, column=2)
            self._load_autoupdate()  # reflect the device's current setting

        # --- paste links + .conf import --------------------------------
        lk = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        lk.grid(row=3, column=0, padx=32, pady=(12, 0), sticky="ew")
        lk.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(lk, palette, "file", "Ссылки-ключи (vless:// vpn://) и AmneziaWG .conf").grid(
            row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        self._links = ctk.CTkTextbox(lk, font=ctk.CTkFont(family="Consolas", size=12), height=70,
                                     fg_color=palette.bg, text_color=palette.text)
        self._links.grid(row=1, column=0, padx=16, pady=4, sticky="ew")
        btnrow = ctk.CTkFrame(lk, fg_color="transparent")
        btnrow.grid(row=2, column=0, padx=16, pady=(6, 12), sticky="w")
        self._link_btn = ctk.CTkButton(btnrow, text="Импортировать", font=fonts.body(),
                                       fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                       command=self._do_links)
        self._link_btn.grid(row=0, column=0)
        self._conf_btn = ctk.CTkButton(btnrow, text="Импорт .conf…", font=fonts.body(),
                                       fg_color=palette.surface_hover, hover_color=palette.border,
                                       command=self._do_conf)
        self._conf_btn.grid(row=0, column=1, padx=(8, 0))

        # --- main node --------------------------------------------------
        self._mn_card = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        self._mn_card.grid(row=4, column=0, padx=32, pady=(12, 0), sticky="ew")
        self._mn_card.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(self._mn_card, palette, "nodes", "Добавленные серверы").grid(
            row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        # Visible list of imported nodes so the user can confirm what was added.
        # Scrollable + fixed height so a large subscription (up to MAX_VISIBLE rows)
        # can be browsed without stretching the whole page.
        self._nodes_list = ctk.CTkScrollableFrame(self._mn_card, fg_color=palette.bg,
                                                  corner_radius=8, height=220)
        self._nodes_list.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")
        self._nodes_list.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._mn_card, text="Основной сервер", font=fonts.heading(),
                     text_color=palette.text).grid(row=2, column=0, padx=16, pady=(6, 4), sticky="w")
        ctk.CTkRadioButton(self._mn_card, text="Авто — выбирать самый быстрый (рекомендуется)",
                           value="urltest", variable=self._main_mode, font=fonts.body(),
                           fg_color=palette.accent, hover_color=palette.accent_hover,
                           command=self._on_mode).grid(row=3, column=0, padx=16, pady=4, sticky="w")
        ctk.CTkRadioButton(self._mn_card, text="Выбрать конкретный сервер", value="specific",
                           variable=self._main_mode, font=fonts.body(), fg_color=palette.accent,
                           hover_color=palette.accent_hover, command=self._on_mode).grid(
            row=4, column=0, padx=16, pady=4, sticky="w")
        self._node_menu = ctk.CTkOptionMenu(self._mn_card, values=["—"], font=fonts.body(),
                                            fg_color=palette.surface_hover, button_color=palette.accent,
                                            button_hover_color=palette.accent_hover)
        self._node_menu.grid(row=5, column=0, padx=(40, 16), pady=4, sticky="w")

        # "У меня белые списки": build the auto pool from up to 5 servers whose name
        # contains "Whitelist"/"белые списки" (the provider's whitelist-routing servers).
        ctk.CTkCheckBox(self._mn_card, text="У меня белые списки", font=fonts.body(),
                        variable=self._whitelist, onvalue="1", offvalue="0",
                        fg_color=palette.accent, hover_color=palette.accent_hover).grid(
            row=6, column=0, padx=16, pady=(8, 0), sticky="w")
        ctk.CTkLabel(self._mn_card, text="Белые списки - режим фильтрации интернета провайдером "
                     "когда работают только разрешенные сайты одобренные государством - Яндекс, ВК "
                     "и прочие.",
                     font=fonts.small(), text_color=palette.text_muted, wraplength=520,
                     justify="left", anchor="w").grid(row=7, column=0, padx=(40, 16), pady=(0, 4),
                                                       sticky="w")

        self._apply_btn = ctk.CTkButton(self._mn_card, text="Применить и продолжить",
                                        font=fonts.heading(), height=40, fg_color=palette.ok,
                                        hover_color=palette.accent_hover, command=self._apply)
        self._apply_btn.grid(row=8, column=0, padx=16, pady=(8, 12), sticky="ew")
        self._mn_card.grid_remove()  # shown once nodes exist

        self._status = ctk.CTkLabel(b, text="", font=fonts.small(), text_color=palette.text_muted,
                                    anchor="w", wraplength=560, justify="left")
        self._status.grid(row=5, column=0, padx=32, pady=(8, 4), sticky="w")

        # Staging can finish with no nodes — they're added online later.
        if offline:
            ctk.CTkButton(b, text="Готово — серверы добавлю позже →", font=fonts.body(),
                          fg_color="transparent", hover_color=palette.surface_hover,
                          text_color=palette.text_muted, command=self._on_done).grid(
                row=6, column=0, padx=32, pady=(0, 4), sticky="w")

        if on_back is not None:
            ctk.CTkButton(b, text="← Назад", font=fonts.body(), fg_color="transparent",
                          hover_color=palette.surface_hover, width=90, command=on_back).grid(
                row=7, column=0, padx=32, pady=(0, 12), sticky="w")

        self._refresh_nodes()

    # ----- helpers ------------------------------------------------------

    def _set_status(self, text: str, color: Optional[str] = None) -> None:
        self._status.configure(text=text, text_color=color or self.p.text_muted)

    # ----- subscription auto-update -------------------------------------

    def _load_autoupdate(self) -> None:
        """Reflect the device's current daily auto-update setting in the toggle."""
        client = self._client

        def done(res: tuple) -> None:
            if not self.winfo_exists():
                return
            enabled, hour = res
            self._autoupd_var.set("1" if enabled else "0")
            self._autoupd_time.set(f"{hour:02d}:00")
            self._autoupd_time.configure(state="normal" if enabled else "disabled")

        run_async(self, lambda: nd.get_subscription_autoupdate(client), done, lambda _e: None)

    def _on_autoupd(self) -> None:
        enabled = self._autoupd_var.get() == "1"
        try:
            hour = int(self._autoupd_time.get().split(":")[0])
        except ValueError:
            hour = 2
        self._autoupd_time.configure(state="normal" if enabled else "disabled")
        self._set_status(
            f"Автообновление подписок включено — ежедневно в {hour:02d}:00." if enabled
            else "Автообновление подписок выключено.")
        client = self._client
        run_async(self, lambda: nd.set_subscription_autoupdate(client, enabled, hour),
                  lambda _r: None, lambda e: self._set_status(f"Ошибка: {e}", self.p.fail))

    # ----- subscription rows --------------------------------------------

    def _add_sub_row(self) -> None:
        if len(self._sub_entries) >= MAX_SUBS:
            self._set_status(f"Не больше {MAX_SUBS} подписок.", self.p.warn)
            return
        i = len(self._sub_entries)
        row = ctk.CTkFrame(self._sub_rows, fg_color="transparent")
        row.grid(row=i, column=0, pady=2, sticky="ew")
        row.grid_columnconfigure(0, weight=1)
        entry = ctk.CTkEntry(row, font=fonts.body(), placeholder_text="https://…")
        entry.grid(row=0, column=0, sticky="ew")
        # First row has no remove button; extra rows can be removed.
        if i > 0:
            ctk.CTkButton(row, text="✕", width=32, font=fonts.body(), fg_color=self.p.surface_hover,
                          hover_color=self.p.fail, command=lambda r=row, e=entry: self._remove_sub_row(r, e)
                          ).grid(row=0, column=1, padx=(6, 0))
        self._sub_entries.append(entry)
        if len(self._sub_entries) >= MAX_SUBS:
            self._sub_add.configure(state="disabled")

    def _remove_sub_row(self, row: ctk.CTkBaseClass, entry: ctk.CTkEntry) -> None:
        if entry in self._sub_entries:
            self._sub_entries.remove(entry)
        row.destroy()
        self._sub_add.configure(state="normal")

    def _on_mode(self) -> None:
        if self._main_mode.get() == "specific":
            self._node_menu.grid()
        else:
            self._node_menu.grid_remove()

    def _refresh_nodes(self) -> None:
        client = self._client
        run_async(self, lambda: nd.list_nodes(client), self._render_nodes, self._err)

    def _render_nodes(self, nodes: list[nd.Node]) -> None:
        # Newest first: list_nodes returns UCI insertion order, so the most
        # recently added nodes are at the end — reverse to put them on top.
        nodes = list(reversed(nodes))
        self._nodes = nodes
        for w in self._nodes_list.winfo_children():
            w.destroy()
        if not nodes:
            self._mn_card.grid_remove()
            if self._import_attempted:
                self._set_status(
                    "Подписка обработана, но ни одного сервера не добавилось. Возможные причины: "
                    "у роутера нет интернета, ссылка недействительна, или формат подписки не "
                    "поддерживается этой версией Re:HomeProxy. Проверьте ссылку и связь — или "
                    "вставьте серверы ссылками-ключами / .conf ниже.", self.p.warn)
            else:
                self._set_status(
                    "Пока серверов нет. Добавьте подписку или вставьте ссылки-ключи / .conf ниже.",
                    self.p.text_muted)
            return
        labels = [f"{n.label or n.section} ({n.type})" for n in nodes]
        self._node_menu.configure(values=labels)
        self._node_menu.set(labels[0])
        # Scrollable list: show up to MAX_VISIBLE rows, collapse the rest as a tail.
        shown = nodes[:MAX_VISIBLE]
        for i, n in enumerate(shown):
            ctk.CTkLabel(self._nodes_list, text=f"•  {n.label or n.section}", font=fonts.body(),
                         text_color=self.p.text, anchor="w").grid(row=i, column=0, padx=10, pady=1, sticky="w")
            ctk.CTkLabel(self._nodes_list, text=n.type, font=fonts.small(),
                         text_color=self.p.text_muted, anchor="e").grid(row=i, column=1, padx=10, pady=1, sticky="e")
        if len(nodes) > len(shown):
            ctk.CTkLabel(self._nodes_list, text=f"… и ещё {len(nodes) - len(shown)} серверов",
                         font=fonts.small(), text_color=self.p.text_muted, anchor="w").grid(
                row=len(shown), column=0, columnspan=2, padx=10, pady=(1, 3), sticky="w")
        self._mn_card.grid()
        self._on_mode()
        self._set_status(f"Серверов: {len(nodes)}", self.p.text)

    def _err(self, e: BaseException) -> None:
        self._set_status(f"Ошибка: {e}", self.p.fail)

    # ----- actions ------------------------------------------------------

    def _do_sub(self) -> None:
        urls = [e.get().strip() for e in self._sub_entries if e.get().strip()]
        if not urls:
            self._set_status("Введите хотя бы один URL подписки.", self.p.warn)
            return
        self._sub_btn.configure(state="disabled", text="Обновляю…")
        client = self._client

        def task() -> dict:
            for url in urls:
                nd.add_subscription(client, url)
            return nd.update_subscriptions(client)  # one fetch for all

        def done(result: dict) -> None:
            self._sub_btn.configure(state="normal", text="Добавить и обновить")
            if not result.get("ok"):
                self._set_status(f"Подписок добавлено: {len(urls)}. Ошибка обновления — см. лог роутера.",
                                 self.p.warn)
            elif result.get("added") is not None:
                self._set_status(f"Подписок добавлено: {len(urls)}. Серверов: +{result['added']} / "
                                 f"−{result['removed']}.", self.p.ok)
            else:
                self._set_status(f"Подписок добавлено: {len(urls)}. Обновлено.", self.p.ok)
            self._import_attempted = True
            self._refresh_nodes()

        run_async(self, task, done, self._sub_err)

    def _sub_err(self, e: BaseException) -> None:
        self._sub_btn.configure(state="normal", text="Добавить и обновить")
        self._set_status(f"Не удалось обновить подписку: {e}", self.p.fail)

    def _do_links(self) -> None:
        text = self._links.get("1.0", "end").strip()
        if not text:
            self._set_status("Вставьте хотя бы одну ссылку.", self.p.warn)
            return
        self._link_btn.configure(state="disabled", text="Импортирую…")
        client = self._client
        # Routes vpn:// (decoded on the PC) and ordinary share-links to the right
        # importer; one paste can mix both.
        from ..engine import vpn_link
        run_async(self, lambda: vpn_link.import_mixed_links(client, text),
                  self._links_done, self._links_err)

    def _links_done(self, res: dict[str, Any]) -> None:
        self._link_btn.configure(state="normal", text="Импортировать")
        imported = res.get("imported") or 0
        failed = res.get("failed") or 0
        if imported == 0 and failed:
            errs = "; ".join(res.get("errors") or []) or "не удалось"
            self._set_status(f"Импорт не удался: {errs[:140]}", self.p.fail)
            return
        self._links.delete("1.0", "end")
        msg = f"Импортировано: {imported}, пропущено: {failed}."
        if res.get("errors"):
            msg += " " + "; ".join(res["errors"])[:100]
        self._set_status(msg, self.p.ok if imported else self.p.warn)
        self._import_attempted = True
        self._refresh_nodes()

    def _links_err(self, e: BaseException) -> None:
        self._link_btn.configure(state="normal", text="Импортировать")
        self._set_status(f"Импорт не удался: {e}", self.p.fail)

    def _do_conf(self) -> None:
        path = filedialog.askopenfilename(
            title="Выберите .conf (WireGuard/AmneziaWG)",
            filetypes=[("WireGuard/AmneziaWG", "*.conf"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            self._set_status(f"Не удалось прочитать файл: {e}", self.p.fail)
            return
        label = os.path.splitext(os.path.basename(path))[0]
        self._conf_btn.configure(state="disabled", text="Импортирую…")
        client = self._client
        run_async(self, lambda: nd.import_conf(client, text, label=label),
                  self._conf_done, self._conf_err)

    def _conf_done(self, res: dict[str, Any]) -> None:
        self._conf_btn.configure(state="normal", text="Импорт .conf…")
        if res.get("error"):
            self._set_status(f"Импорт .conf не удался: {res['error']}", self.p.fail)
            return
        self._set_status("Сервер из .conf импортирован.", self.p.ok)
        self._import_attempted = True
        self._refresh_nodes()

    def _conf_err(self, e: BaseException) -> None:
        self._conf_btn.configure(state="normal", text="Импорт .conf…")
        self._set_status(f"Импорт .conf не удался: {e}", self.p.fail)

    def _apply(self) -> None:
        if not self._nodes:
            self._set_status("Сначала добавьте серверы.", self.p.warn)
            return
        self._apply_btn.configure(state="disabled", text="Применяю…")
        client = self._client
        nodes = self._nodes
        whitelist = self._whitelist.get() == "1"
        if self._main_mode.get() == "urltest":
            def task() -> bool:
                # Build a lean, protocol-diverse auto pool: core-incompatible nodes
                # are dropped (one would crash config generation) and the rest are
                # spread across protocols, capped small — not all imported nodes.
                # Whitelist users: up to 5 "Whitelist"-named RU-routing servers are
                # seeded first, then the pool is filled with ordinary servers as usual.
                core = nd.active_core(client)
                pool = nd.build_urltest_pool(nodes, core, whitelist=whitelist)
                if not pool:
                    raise ValueError("Подходящих серверов для авто-пула не найдено в подписках.")
                nd.set_main_node(client, "urltest", urltest_nodes=pool)
                return nd.apply_and_restart(client)
        else:
            sel = self._node_menu.get()
            labels = [f"{n.label or n.section} ({n.type})" for n in nodes]
            value = nodes[labels.index(sel) if sel in labels else 0].section

            def task() -> bool:
                nd.set_main_node(client, value)
                return nd.apply_and_restart(client)

        run_async(self, task, self._applied, self._apply_err)

    def _applied(self, ok: bool) -> None:
        self._apply_btn.configure(state="normal", text="Применить и продолжить")
        if ok:
            self._set_status("Сервер применён.", self.p.ok)
            self._on_done()
        else:
            self._set_status("Сервер сохранён, но перезапуск сервиса не удался. Проверьте «Ядро».",
                             self.p.warn)

    def _apply_err(self, e: BaseException) -> None:
        self._apply_btn.configure(state="normal", text="Применить и продолжить")
        self._set_status(f"Не удалось применить: {e}", self.p.fail)
