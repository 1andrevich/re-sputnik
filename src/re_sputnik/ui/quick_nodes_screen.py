# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
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
from .worker import run_async
from ..i18n import _, current_language

OnDone = Callable[[], None]

MAX_VISIBLE = 254  # cap on node rows shown in the list (rest collapsed to a tail)

# Friendly names for the empty-auto-pool diagnostic.
_CORE_LABELS = {"hiddify": "hiddify-core", "singbox": "sing-box-extended"}
_NODE_TYPE_LABELS = {"amneziawg": "AmneziaWG", "naive": "NaïveProxy"}


def _empty_pool_reason(nodes: list[nd.Node], core: str) -> str:
    """A verbose, specific reason the auto pool is empty — most often the active core
    can't run the only server types the user added (e.g. AmneziaWG on hiddify-core),
    which is impossible to guess from a bare 'nothing found'."""
    kind, types = nd.pool_failure_kind(nodes, core)
    if kind == "core_incompat":
        names = ", ".join(_NODE_TYPE_LABELS.get(t, t) for t in types)
        cur = _CORE_LABELS.get(core, core)
        alt = _CORE_LABELS["singbox" if core == "hiddify" else "hiddify"]
        return _(
            "Не удалось собрать авто-пул.\n\n"
            "Все добавленные серверы — типа {0}, а текущее ядро роутера «{1}» их не "
            "поддерживает, поэтому ни один не попал в пул. Серверы этого типа умеет "
            "только ядро «{2}».\n\n"
            "Как исправить:\n"
            "• откройте раздел «Ядро», переключите ядро на «{2}», вернитесь сюда и "
            "нажмите «Применить» снова; либо\n"
            "• добавьте серверы других типов (VLESS, Hysteria2, Trojan, "
            "Shadowsocks), которые поддерживает «{1}»."
        ).format(names, cur, alt)
    return _("Подходящих серверов для авто-пула не найдено в подписках.")


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

        self._sc = kit.WizardScaffold(self, palette, step=5, label=_("Серверы и подписки"), footer=False)
        self._scroll = self._sc.content
        b = self._scroll

        title = _("Серверы (офлайн-подготовка)") if offline else _("Серверы и подписки")
        ctk.CTkLabel(b, text=title, font=fonts.title(), text_color=palette.text).grid(
            row=0, column=0, pady=(28, 2), padx=32, sticky="w")
        # Plain-language intro: explain what a "сервер" is for a non-technical user.
        explainer = _("Сервер (VPN/прокси) — это то, через что пойдёт ваш трафик. ")
        intro = explainer + (
            _("Вставьте ссылки-ключи (vless://, hysteria2://, vpn://…) или импортируйте "
            ".conf. Подписки добавятся позже, когда у роутера появится интернет.")
            if offline else
            _("Добавьте подписку или вставьте ссылки-ключи (vless://, hysteria2://…). "
            "Затем выберите основной сервер."))
        ctk.CTkLabel(b, text=intro, font=fonts.body(),
                     text_color=palette.text_muted, wraplength=560, justify="left").grid(
            row=1, column=0, pady=(0, 12), padx=32, sticky="w")

        # --- subscriptions + keys (one field, auto-classified) ---------
        # Paste a subscription URL (http/https) or server keys (vless:// vpn://…),
        # one per line; add_mixed_input sorts them out. Subscriptions need internet
        # to fetch, so in offline staging they're only registered (fetched later).
        lk = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        lk.grid(row=2, column=0, padx=32, sticky="ew")
        lk.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(lk, palette, "links", _("Подписка или ключи серверов")).grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(
            lk, text=_("Ссылка-подписка (http:// https://) или ключи серверов (vless:// vmess:// "
            "hysteria2:// trojan:// ss:// vpn:// …) — по одному в строке. "
            "Приложение само определит, где подписка, а где ключ."),
            font=fonts.small(), text_color=palette.text_muted, wraplength=540,
            justify="left").grid(row=1, column=0, padx=16, pady=(0, 4), sticky="w")
        self._links = ctk.CTkTextbox(lk, font=fonts.mono(12), height=74,
                                     fg_color=palette.bg, text_color=palette.text)
        self._links.grid(row=2, column=0, padx=16, pady=4, sticky="ew")
        btnrow = ctk.CTkFrame(lk, fg_color="transparent")
        btnrow.grid(row=3, column=0, padx=16, pady=(6, 12), sticky="w")
        self._link_btn = ctk.CTkButton(btnrow, text=_("Добавить"), font=fonts.body(),
                                       fg_color=palette.accent, text_color=palette.accent_fg, hover_color=palette.accent_hover,
                                       command=self._do_input)
        self._link_btn.grid(row=0, column=0)
        self._conf_btn = ctk.CTkButton(btnrow, text=_("Импорт .conf…"), font=fonts.body(),
                                       fg_color=palette.surface_hover, hover_color=palette.border,
                                       command=self._do_conf)
        self._conf_btn.grid(row=0, column=1, padx=(8, 0))

        # Daily subscription auto-update (online only — needs internet; a device cron).
        if not offline:
            au = ctk.CTkFrame(lk, fg_color="transparent")
            au.grid(row=4, column=0, padx=16, pady=(0, 12), sticky="w")
            self._autoupd_var = ctk.StringVar(value="0")
            self._autoupd_switch = ctk.CTkSwitch(
                au, text=_("Автообновление подписок"), font=fonts.body(), variable=self._autoupd_var,
                onvalue="1", offvalue="0", progress_color=palette.accent,
                button_color=palette.accent_fg, command=self._on_autoupd)
            self._autoupd_switch.grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(au, text=_("ежедневно в"), font=fonts.small(),
                         text_color=palette.text_muted).grid(row=0, column=1, padx=(16, 6))
            self._autoupd_time = ctk.CTkOptionMenu(
                au, values=[f"{h:02d}:00" for h in range(24)], width=92, font=fonts.body(),
                fg_color=palette.surface_hover, button_color=palette.accent,
                button_hover_color=palette.accent_hover, command=lambda _v: self._on_autoupd())
            self._autoupd_time.set("02:00")
            self._autoupd_time.configure(state="disabled")
            self._autoupd_time.grid(row=0, column=2)
            self._load_autoupdate()  # reflect the device's current setting

        # --- main node --------------------------------------------------
        self._mn_card = ctk.CTkFrame(b, fg_color=palette.surface, corner_radius=12)
        self._mn_card.grid(row=4, column=0, padx=32, pady=(12, 0), sticky="ew")
        self._mn_card.grid_columnconfigure(0, weight=1)
        kit.SectionHeader(self._mn_card, palette, "nodes", _("Добавленные серверы")).grid(
            row=0, column=0, padx=16, pady=(12, 4), sticky="w")
        # Visible list of imported nodes so the user can confirm what was added.
        # Scrollable + fixed height so a large subscription (up to MAX_VISIBLE rows)
        # can be browsed without stretching the whole page.
        self._nodes_list = ctk.CTkScrollableFrame(self._mn_card, fg_color=palette.bg,
                                                  corner_radius=8, height=220)
        self._nodes_list.grid(row=1, column=0, padx=16, pady=(0, 8), sticky="ew")
        self._nodes_list.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._mn_card, text=_("Основной сервер"), font=fonts.heading(),
                     text_color=palette.text).grid(row=2, column=0, padx=16, pady=(6, 4), sticky="w")
        ctk.CTkRadioButton(self._mn_card, text=_("Авто — выбирать самый быстрый (рекомендуется)"),
                           value="urltest", variable=self._main_mode, font=fonts.body(),
                           fg_color=palette.accent, hover_color=palette.accent_hover,
                           command=self._on_mode).grid(row=3, column=0, padx=16, pady=4, sticky="w")
        ctk.CTkRadioButton(self._mn_card, text=_("Выбрать конкретный сервер"), value="specific",
                           variable=self._main_mode, font=fonts.body(), fg_color=palette.accent,
                           hover_color=palette.accent_hover, command=self._on_mode).grid(
            row=4, column=0, padx=16, pady=4, sticky="w")
        self._node_menu = ctk.CTkOptionMenu(self._mn_card, values=["—"], font=fonts.body(),
                                            fg_color=palette.surface_hover, button_color=palette.accent,
                                            button_hover_color=palette.accent_hover)
        self._node_menu.grid(row=5, column=0, padx=(40, 16), pady=4, sticky="w")

        # "У меня белые списки" — RU-only. Whitelist filtering (only state-approved
        # sites like Yandex/VK work) is a Russian ISP regime; it doesn't apply to the
        # CN/IR modes, so the option is offered only when the UI language is Russian.
        # Builds the auto pool from up to 5 "Whitelist"/"белые списки"-named servers.
        if current_language() == "ru":
            ctk.CTkCheckBox(self._mn_card, text=_("У меня белые списки"), font=fonts.body(),
                            variable=self._whitelist, onvalue="1", offvalue="0",
                            fg_color=palette.accent, hover_color=palette.accent_hover).grid(
                row=6, column=0, padx=16, pady=(8, 0), sticky="w")
            ctk.CTkLabel(self._mn_card, text=_("Белые списки - режим фильтрации интернета провайдером "
                         "когда работают только разрешенные сайты одобренные государством - Яндекс, ВК "
                         "и прочие."),
                         font=fonts.small(), text_color=palette.text_muted, wraplength=520,
                         justify="left", anchor="w").grid(row=7, column=0, padx=(40, 16), pady=(0, 4),
                                                           sticky="w")

        self._apply_btn = ctk.CTkButton(self._mn_card, text=_("Применить и продолжить"),
                                        font=fonts.heading(), height=40, fg_color=palette.ok,
                                        hover_color=palette.accent_hover, command=self._apply)
        self._apply_btn.grid(row=8, column=0, padx=16, pady=(8, 12), sticky="ew")
        self._mn_card.grid_remove()  # shown once nodes exist

        self._status = ctk.CTkLabel(b, text="", font=fonts.small(), text_color=palette.text_muted,
                                    anchor="w", wraplength=560, justify="left")
        self._status.grid(row=5, column=0, padx=32, pady=(8, 4), sticky="w")

        # Staging can finish with no nodes — they're added online later.
        if offline:
            ctk.CTkButton(b, text=_("Готово — серверы добавлю позже →"), font=fonts.body(),
                          fg_color="transparent", hover_color=palette.surface_hover,
                          text_color=palette.text_muted, command=self._on_done).grid(
                row=6, column=0, padx=32, pady=(0, 4), sticky="w")

        if on_back is not None:
            ctk.CTkButton(b, text=_("← Назад"), font=fonts.body(), fg_color="transparent",
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
            _("Автообновление подписок включено — ежедневно в {hour}:00.").format(hour=f"{hour:02d}") if enabled
            else _("Автообновление подписок выключено."))
        client = self._client
        run_async(self, lambda: nd.set_subscription_autoupdate(client, enabled, hour),
                  lambda _r: None, lambda e: self._set_status(_("Ошибка: {0}").format(e), self.p.fail))

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
                    _("Подписка обработана, но ни одного сервера не добавилось. Возможные причины: "
                    "у роутера нет интернета, ссылка недействительна, или формат подписки не "
                    "поддерживается этой версией Re:HomeProxy. Проверьте ссылку и связь — или "
                    "вставьте серверы ссылками-ключами / .conf ниже."), self.p.warn)
            else:
                self._set_status(
                    _("Пока серверов нет. Добавьте подписку или вставьте ссылки-ключи / .conf ниже."),
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
            ctk.CTkLabel(self._nodes_list, text=_("… и ещё {0} серверов").format(len(nodes) - len(shown)),
                         font=fonts.small(), text_color=self.p.text_muted, anchor="w").grid(
                row=len(shown), column=0, columnspan=2, padx=10, pady=(1, 3), sticky="w")
        self._mn_card.grid()
        self._on_mode()
        self._set_status(_("Серверов: {0}").format(len(nodes)), self.p.text)

    def _err(self, e: BaseException) -> None:
        self._set_status(_("Ошибка: {0}").format(e), self.p.fail)

    # ----- actions ------------------------------------------------------

    def _do_input(self) -> None:
        text = self._links.get("1.0", "end").strip()
        if not text:
            self._set_status(_("Вставьте ссылку-подписку или ключ сервера."), self.p.warn)
            return
        self._link_btn.configure(state="disabled", text=_("Добавляю…"))
        client = self._client
        # add_mixed_input sorts each line: http(s):// → subscription, the rest →
        # key import (vpn:// is decoded on the PC). Subscriptions are fetched right
        # away when online; offline they're only registered (no internet to fetch).
        fetch = not self._offline
        from ..engine import vpn_link
        run_async(self, lambda: vpn_link.add_mixed_input(client, text, fetch=fetch),
                  self._input_done, self._input_err)

    def _input_done(self, res: dict[str, Any]) -> None:
        self._link_btn.configure(state="normal", text=_("Добавить"))
        subs_added = res.get("subs_added") or 0
        imported = res.get("imported") or 0
        failed = res.get("failed") or 0
        errors = res.get("errors") or []
        upd = res.get("update")
        parts: list[str] = []
        if subs_added:
            if upd and upd.get("ok") and upd.get("added") is not None:
                parts.append(_("подписок: +{0} (серверов +{1} / −{2})").format(subs_added, upd['added'], upd['removed']))
            else:
                parts.append(_("подписок добавлено: {0}").format(subs_added))
        if imported:
            parts.append(_("ключей: +{0}").format(imported))
        if failed:
            parts.append(_("пропущено: {0}").format(failed))
        if not parts and not errors:
            self._set_status(_("Ничего не распознано — проверьте формат ссылок."), self.p.warn)
            return
        msg = ", ".join(parts) if parts else _("Не удалось добавить.")
        if errors:
            msg += ". " + "; ".join(errors)[:120]
        self._set_status(msg, self.p.ok if (subs_added or imported) else self.p.warn)
        self._links.delete("1.0", "end")
        self._import_attempted = True
        self._refresh_nodes()

    def _input_err(self, e: BaseException) -> None:
        self._link_btn.configure(state="normal", text=_("Добавить"))
        self._set_status(_("Не удалось добавить: {0}").format(e), self.p.fail)

    def _do_conf(self) -> None:
        path = filedialog.askopenfilename(
            title=_("Выберите .conf (WireGuard/AmneziaWG)"),
            filetypes=[("WireGuard/AmneziaWG", "*.conf"), (_("Все файлы"), "*.*")])
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            self._set_status(_("Не удалось прочитать файл: {0}").format(e), self.p.fail)
            return
        label = os.path.splitext(os.path.basename(path))[0]
        self._conf_btn.configure(state="disabled", text=_("Импортирую…"))
        client = self._client
        run_async(self, lambda: nd.import_conf(client, text, label=label),
                  self._conf_done, self._conf_err)

    def _conf_done(self, res: dict[str, Any]) -> None:
        self._conf_btn.configure(state="normal", text=_("Импорт .conf…"))
        if res.get("error"):
            self._set_status(_("Импорт .conf не удался: {0}").format(res['error']), self.p.fail)
            return
        self._set_status(_("Сервер из .conf импортирован."), self.p.ok)
        self._import_attempted = True
        self._refresh_nodes()

    def _conf_err(self, e: BaseException) -> None:
        self._conf_btn.configure(state="normal", text=_("Импорт .conf…"))
        self._set_status(_("Импорт .conf не удался: {0}").format(e), self.p.fail)

    def _apply(self) -> None:
        if not self._nodes:
            self._set_status(_("Сначала добавьте серверы."), self.p.warn)
            return
        self._apply_btn.configure(state="disabled", text=_("Применяю…"))
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
                    raise ValueError(_empty_pool_reason(nodes, core))
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
        self._apply_btn.configure(state="normal", text=_("Применить и продолжить"))
        if ok:
            self._set_status(_("Сервер применён."), self.p.ok)
            self._on_done()
        else:
            self._set_status(_("Сервер сохранён, но перезапуск сервиса не удался. Проверьте «Ядро»."),
                             self.p.warn)

    def _apply_err(self, e: BaseException) -> None:
        self._apply_btn.configure(state="normal", text=_("Применить и продолжить"))
        self._set_status(_("Не удалось применить: {0}").format(e), self.p.fail)
