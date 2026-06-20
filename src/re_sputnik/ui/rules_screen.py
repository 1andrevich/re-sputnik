# SPDX-License-Identifier: GPL-2.0-only
"""Rules section — routing mode selector + RU-mode flag toggles (editable).

Logos and the full service→node binding table are deferred. This covers the
common edits: pick the routing mode, and (in the Russia mode) toggle the simple
uci flags that shape it. Changes are written to uci immediately and applied by a
deliberate service restart (generate_client.uc regenerates on restart).
"""

from __future__ import annotations

from typing import Any, Callable, Optional

import customtkinter as ctk

from ..engine import nodes as nodeng
from ..engine import rules as ruleng
from ..router import RouterClient
from .icons import has_real_icon, service_icon
from . import kit
from .theme import Palette, fonts
from .worker import run_async

# routing_mode uci value <-> human label (mirrors client.js, with RU renames).
_MODE_LABELS = {
    "proxy_banned_ru": "Россия (раздельное туннелирование)",
    "global": "Глобальный (весь трафик через прокси)",
    "gfwlist": "Китай — GFWList",
    "bypass_mainland_china": "Китай — Direct",
    "proxy_mainland_china": "Китай — Proxy",
    "custom": "Своя маршрутизация",
    "custom_json": "Свой JSON",
}
_LABEL_TO_MODE = {v: k for k, v in _MODE_LABELS.items()}

# Modes the app OFFERS in the dropdown. The China/custom/json modes still resolve
# via _MODE_LABELS (so a router already set to one, e.g. in LuCI, displays right),
# but the app only lets you choose the two that fit its audience.
_OFFERED_MODES = ("proxy_banned_ru", "global")

# RU-mode boolean flags shown as plain switches (uci key -> label). The VoIP and
# torrent flags are pulled OUT of here and rendered as rich, logo'd toggles
# (see _TRAFFIC_TOGGLES / _build_traffic_card) — what the user asked to look
# "like in a browser". IPv6 is intentionally NOT exposed: it's kept OFF by
# default (RU lists carry no v6 CIDRs, so v6 would leak past the proxy/rules).
_GLOBAL_FLAGS: list[tuple[str, str]] = []

# Short explainer of what "раздельное туннелирование" means for THIS app's presets
# (default-direct + only blocked-in-RU traffic via the proxy).
_SPLIT_TUNNEL_HELP = (
    "Раздельное туннелирование: по умолчанию весь трафик идёт напрямую (как обычно "
    "и быстро), а через VPN направляется только то, что заблокировано в России — по "
    "списку Re:filter (домены и IP из реестра РКН) и выбранным сервисам ниже. "
    "Так зарубежные сервисы открываются, а российские сайты и банки продолжают "
    "работать напрямую, без VPN."
)

# Rich traffic toggles for the Russia mode: uci key -> (title, subtitle, brand
# icon names, invert). `invert=True` means the switch ON corresponds to uci '0'
# (no_proxy_torrents is phrased negatively: ON = "proxy torrents" = flag '0').
_TRAFFIC_TOGGLES = [
    ("proxy_calls", "Звонки в мессенджерах через прокси",
     "WhatsApp, Telegram, FaceTime и др. — пускать голос/видео через прокси.",
     ("whatsapp", "telegram"), False),
    ("no_proxy_torrents", "Торренты через прокси",
     "Рекомендуем отключить — торренты перегружают канал и часто заблокированы на серверах.",
     ("torrent",), True),
]


class RulesScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, quick: bool = False, on_done: Optional[Callable[[], None]] = None,
                 on_back: Optional[Callable[[], None]] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._dirty = False
        # Quick-setup mode: seed sane RU defaults on load and show wizard nav.
        self._quick = quick
        self._on_done = on_done
        self._on_back = on_back

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=0, column=0, padx=24, pady=16, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self._body, text="Правила", font=fonts.title(), text_color=palette.text,
                     image=kit.icon(kit._ICON_FOR["rules"], 26), compound="left").grid(
            row=0, column=0, pady=(4, 8), sticky="w")
        self._status = ctk.CTkLabel(self._body, text="Считываю правила…", font=fonts.small(),
                                    text_color=palette.text_muted, anchor="w")
        self._status.grid(row=1, column=0, sticky="w", pady=(0, 8))
        self._card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._card.grid(row=2, column=0, sticky="ew")
        self._card.grid_columnconfigure(1, weight=1)

        # Rich VoIP/torrent toggles card (shown only in the Russia mode).
        self._traffic_card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._traffic_card.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        self._traffic_card.grid_columnconfigure(0, weight=1)
        self._traffic_card.grid_remove()

        # Service→node bindings card (shown only in the Russia mode).
        self._bind_card = ctk.CTkFrame(self._body, fg_color=palette.surface, corner_radius=12)
        self._bind_card.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        self._bind_card.grid_columnconfigure(0, weight=1)
        self._bind_card.grid_remove()
        self._nodes: list[nodeng.Node] = []
        self._rules: list[ruleng.RuRule] = []

        self._restart_btn = ctk.CTkButton(self._body, text="Применить изменения", font=fonts.body(),
                                           width=200, fg_color=palette.accent, text_color=palette.accent_fg,
                                           hover_color=palette.accent_hover, state="disabled",
                                           command=self._restart)
        self._restart_btn.grid(row=5, column=0, pady=(12, 8), sticky="w")

        # Wizard navigation (quick-setup only).
        if self._on_done is not None:
            nav = ctk.CTkFrame(self._body, fg_color="transparent")
            nav.grid(row=6, column=0, sticky="ew", pady=(4, 8))
            nav.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(nav, text="Далее →", font=fonts.heading(), height=42, fg_color=palette.ok,
                          hover_color=palette.accent_hover, command=self._continue).grid(
                row=0, column=0, columnspan=3, sticky="ew", pady=(0, 4))
            ctk.CTkButton(nav, text="Пропустить", font=fonts.body(), fg_color="transparent",
                          hover_color=palette.surface_hover, command=self._on_done).grid(
                row=1, column=0, sticky="w")
            if self._on_back is not None:
                ctk.CTkButton(nav, text="← Назад", font=fonts.body(), fg_color="transparent",
                              hover_color=palette.surface_hover, width=90,
                              command=self._on_back).grid(row=1, column=1, padx=(8, 0))
        self.refresh()

    def _continue(self) -> None:
        # Apply pending changes (restart) before advancing, so the next screen sees
        # a live config; if nothing's dirty, just move on.
        if self._dirty and self._on_done is not None:
            self._restart_btn.configure(state="disabled", text="Применяю…")
            client = self._client
            run_async(self, lambda: client.ubus_homeproxy("diag_service_restart", timeout=40),
                      lambda _r: (self._after_restart(_r), self._on_done()),
                      lambda e: self._status.configure(text=f"Ошибка: {e}", text_color=self.p.fail))
        elif self._on_done is not None:
            self._on_done()

    # ----- read ---------------------------------------------------------

    def refresh(self) -> None:
        client = self._client
        keys = ["routing_mode", "main_node", "main_udp_node", "ipv6_support",
                "proxy_calls", "no_proxy_torrents"]

        quick = self._quick

        def task() -> dict[str, Any]:
            if quick:
                ruleng.ensure_ru_defaults(client)  # seed RU mode + blocklists once
            d = {k: (client.uci_get(f"homeproxy.config.{k}") or "") for k in keys}
            if d["routing_mode"] == "proxy_banned_ru":
                d["_rules"] = ruleng.list_rules(client)
                d["_nodes"] = nodeng.list_nodes(client)
            return d

        run_async(self, task, self._render, lambda e: self._status.configure(
            text=f"Ошибка: {e}", text_color=self.p.fail))

    @staticmethod
    def _main_node_display(value: str | None, nodes: list) -> str:
        """Friendly text for the read-only main-node value: the raw uci value is
        'urltest' / 'byedpi-out' / a node section — show 'URLTest' / 'ByeDPI' / the
        node's label instead of the bare key."""
        if not value:
            return "—"
        if value == "urltest":
            return "URLTest"
        if value == "byedpi-out":
            return "ByeDPI"
        for n in nodes:
            if n.section == value:
                return f"{n.label or n.section} ({n.type})"
        return value

    def _render(self, d: dict[str, Any]) -> None:
        p = self.p
        self._status.configure(text="")
        for w in self._card.winfo_children():
            w.destroy()
        mode = d["routing_mode"]

        ctk.CTkLabel(self._card, text="Режим маршрутизации", font=fonts.body(),
                     text_color=p.text_muted).grid(row=0, column=0, padx=(16, 12), pady=(12, 6), sticky="w")
        offered = [_MODE_LABELS[k] for k in _OFFERED_MODES if k in _MODE_LABELS]
        cur_label = _MODE_LABELS.get(mode, mode)
        if cur_label and cur_label not in offered:
            offered.append(cur_label)  # show the router's current mode even if not offered
        self._mode_menu = ctk.CTkOptionMenu(
            self._card, values=offered, font=fonts.body(),
            fg_color=p.surface_hover, button_color=p.accent, button_hover_color=p.accent_hover,
            command=self._on_mode)
        self._mode_menu.set(cur_label or offered[0])
        self._mode_menu.grid(row=0, column=1, padx=(0, 16), pady=(12, 6), sticky="ew")

        if mode == "proxy_banned_ru":
            ctk.CTkLabel(self._card, text=_SPLIT_TUNNEL_HELP, font=fonts.small(),
                         text_color=p.text_muted, wraplength=560, justify="left",
                         anchor="w").grid(row=1, column=0, columnspan=2, padx=16, pady=(2, 8),
                                          sticky="w")

        row = 2
        self._switches: dict[str, ctk.CTkSwitch] = {}
        for key, label in _GLOBAL_FLAGS:
            var = ctk.StringVar(value="1" if d.get(key) == "1" else "0")
            sw = ctk.CTkSwitch(self._card, text=label, font=fonts.body(), variable=var,
                               onvalue="1", offvalue="0", progress_color=p.accent,
                               command=lambda k=key, v=var: self._on_flag(k, v))
            sw.grid(row=row, column=0, columnspan=2, padx=16, pady=4, sticky="w")
            self._switches[key] = sw
            row += 1
        ctk.CTkLabel(self._card, text="", height=4).grid(row=row, column=0)

        if mode == "proxy_banned_ru":
            self._build_traffic_card(d)
            self._nodes = d.get("_nodes") or []
            self._rules = d.get("_rules") or []
            self._build_bindings()
        else:
            self._traffic_card.grid_remove()
            self._bind_card.grid_remove()

    # ----- VoIP / torrent toggles (logo'd) ------------------------------

    def _build_traffic_card(self, d: dict[str, Any]) -> None:
        p = self.p
        for w in self._traffic_card.winfo_children():
            w.destroy()
        self._traffic_card.grid()
        kit.SectionHeader(self._traffic_card, p, "traffic", "Особый трафик").grid(
            row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        for i, (key, title, subtitle, brands, invert) in enumerate(_TRAFFIC_TOGGLES, start=1):
            rowf = ctk.CTkFrame(self._traffic_card, fg_color=p.surface_hover, corner_radius=8)
            rowf.grid(row=i, column=0, padx=12, pady=4, sticky="ew")
            rowf.grid_columnconfigure(1, weight=1)
            # Brand logos — only the ones we actually bundle (others rely on the
            # emoji in the title until their PNG is added to resources/icons/).
            real = [b for b in brands if has_real_icon(b)]
            if real:
                logos = ctk.CTkFrame(rowf, fg_color="transparent")
                logos.grid(row=0, column=0, rowspan=2, padx=(12, 8), pady=8)
                for j, b in enumerate(real):
                    ctk.CTkLabel(logos, text="", image=service_icon(b)).grid(row=0, column=j, padx=1)
            ctk.CTkLabel(rowf, text=title, font=fonts.body(), text_color=p.text, anchor="w").grid(
                row=0, column=1, padx=0, pady=(8, 0), sticky="w")
            ctk.CTkLabel(rowf, text=subtitle, font=fonts.small(), text_color=p.text_muted,
                         anchor="w", wraplength=420, justify="left").grid(
                row=1, column=1, padx=0, pady=(0, 8), sticky="w")
            # invert: switch ON == route through proxy == uci '0' for no_proxy_torrents.
            on_now = (d.get(key) != "1") if invert else (d.get(key) == "1")
            var = ctk.StringVar(value="1" if on_now else "0")
            ctk.CTkSwitch(rowf, text="", variable=var, onvalue="1", offvalue="0", width=46,
                          progress_color=p.accent,
                          command=lambda k=key, v=var, inv=invert: self._on_traffic_flag(k, v, inv)).grid(
                row=0, column=2, rowspan=2, padx=(8, 14), pady=8)

    def _on_traffic_flag(self, key: str, var: ctk.StringVar, invert: bool) -> None:
        # Map the user-facing ON/OFF back to the uci flag (inverted for torrents).
        on = var.get() == "1"
        value = ("0" if on else "1") if invert else ("1" if on else "0")
        client = self._client

        def task() -> None:
            client.uci_set(f"homeproxy.config.{key}", value)
            client.uci_commit("homeproxy")

        run_async(self, task, lambda _r: self._mark_dirty(), lambda e: self._status.configure(
            text=f"Ошибка: {e}", text_color=self.p.fail))

    # ----- service→node bindings ----------------------------------------

    def _build_bindings(self) -> None:
        p = self.p
        for w in self._bind_card.winfo_children():
            w.destroy()
        self._bind_card.grid()
        kit.SectionHeader(self._bind_card, p, "links", "Привязка сервисов к серверам").grid(
            row=0, column=0, padx=16, pady=(12, 2), sticky="w")
        ctk.CTkLabel(self._bind_card,
                     text="Маршрут по умолчанию — прямой. Добавленные правила проксируются с "
                     "автоматическим приоритетом:\n"
                     "1. Небольшие списки (YouTube, Discord и т.д.)\n"
                     "2. Russia Inside (1000+ доменов, itdoginfo) — общий набор небольших списков "
                     "(YouTube, Discord, Telegram, Meta…)\n"
                     "3. Re:filter (60000+ доменов + 25000+ IP) — список заблокированных в России "
                     "доменов и IP (Роскомнадзор, от сообщества)",
                     font=fonts.small(), text_color=p.text_muted, wraplength=540,
                     justify="left").grid(row=1, column=0, padx=16, pady=(0, 8), sticky="w")

        rows = ctk.CTkFrame(self._bind_card, fg_color="transparent")
        rows.grid(row=2, column=0, padx=8, sticky="ew")
        rows.grid_columnconfigure(0, weight=1)
        if not self._rules:
            ctk.CTkLabel(rows, text="Пока нет привязок.", font=fonts.small(),
                         text_color=p.text_muted).grid(row=0, column=0, padx=8, pady=4, sticky="w")
        for i, r in enumerate(self._rules):
            line = ctk.CTkFrame(rows, fg_color=p.surface_hover, corner_radius=8)
            line.grid(row=i, column=0, padx=8, pady=3, sticky="ew")
            line.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(line, text="", image=service_icon(r.source)).grid(
                row=0, column=0, padx=(12, 8), pady=6)
            ctk.CTkLabel(line, text=f"{ruleng.source_label(r.source)}  →  "
                         f"{ruleng.node_label(r.node, self._nodes)}", font=fonts.body(),
                         text_color=p.text, anchor="w").grid(row=0, column=1, padx=0, pady=6, sticky="w")
            ctk.CTkButton(line, text="✕", width=32, font=fonts.body(), fg_color="transparent",
                          hover_color=p.fail, text_color=p.text_muted,
                          command=lambda sec=r.section: self._remove_binding(sec)).grid(
                row=0, column=2, padx=(0, 8), pady=4)

        ctk.CTkLabel(self._bind_card, text="Логотипы — товарные знаки соответствующих владельцев, "
                     "используются лишь для обозначения сервиса.", font=fonts.small(),
                     text_color=self.p.text_muted, wraplength=540, justify="left").grid(
            row=4, column=0, padx=16, pady=(2, 8), sticky="w")

        # Add-rule row: source + node + add.
        used = {r.source for r in self._rules}
        avail = [(v, lbl) for v, lbl in ruleng.SERVICE_SOURCES if v not in used]
        add = ctk.CTkFrame(self._bind_card, fg_color="transparent")
        add.grid(row=3, column=0, padx=8, pady=(8, 12), sticky="ew")
        add.grid_columnconfigure((0, 1), weight=1)
        if not avail:
            ctk.CTkLabel(add, text="Все сервисы уже добавлены.", font=fonts.small(),
                         text_color=p.text_muted).grid(row=0, column=0, sticky="w", padx=8)
            return
        self._src_labels = {lbl: v for v, lbl in avail}
        self._src_menu = ctk.CTkOptionMenu(add, values=[lbl for _v, lbl in avail], font=fonts.body(),
                                           fg_color=p.surface_hover, button_color=p.accent,
                                           button_hover_color=p.accent_hover)
        self._src_menu.grid(row=0, column=0, padx=8, pady=4, sticky="ew")
        node_opts = list(ruleng.NODE_SPECIAL) + [(n.section, f"{n.label or n.section} ({n.type})")
                                                 for n in self._nodes]
        self._node_labels = {lbl: v for v, lbl in node_opts}
        self._node_menu = ctk.CTkOptionMenu(add, values=[lbl for _v, lbl in node_opts], font=fonts.body(),
                                            fg_color=p.surface_hover, button_color=p.accent,
                                            button_hover_color=p.accent_hover)
        self._node_menu.grid(row=0, column=1, padx=8, pady=4, sticky="ew")
        ctk.CTkButton(add, text="+ Добавить", font=fonts.body(), fg_color=p.accent, text_color=p.accent_fg,
                      hover_color=p.accent_hover, width=110, command=self._add_binding).grid(
            row=0, column=2, padx=8, pady=4)

    def _add_binding(self) -> None:
        source = self._src_labels.get(self._src_menu.get())
        node = self._node_labels.get(self._node_menu.get())
        if not source or not node:
            return
        client = self._client
        run_async(self, lambda: ruleng.add_rule(client, source, node),
                  lambda _r: (self._mark_dirty(), self.refresh()),
                  lambda e: self._status.configure(text=f"Ошибка: {e}", text_color=self.p.fail))

    def _remove_binding(self, section: str) -> None:
        client = self._client
        run_async(self, lambda: ruleng.remove_rule(client, section),
                  lambda _r: (self._mark_dirty(), self.refresh()),
                  lambda e: self._status.configure(text=f"Ошибка: {e}", text_color=self.p.fail))

    # ----- edits --------------------------------------------------------

    def _mark_dirty(self) -> None:
        self._dirty = True
        self._restart_btn.configure(state="normal")
        self._status.configure(text="Изменено. Нажмите «Применить изменения».",
                               text_color=self.p.warn)

    def _on_mode(self, label: str) -> None:
        mode = _LABEL_TO_MODE.get(label)
        if not mode:
            return
        client = self._client

        def task() -> None:
            client.uci_set("homeproxy.config.routing_mode", mode)
            client.uci_commit("homeproxy")

        def done(_r: Any) -> None:
            self._mark_dirty()
            self.refresh()  # re-render flags for the new mode

        run_async(self, task, done, lambda e: self._status.configure(
            text=f"Ошибка: {e}", text_color=self.p.fail))

    def _on_flag(self, key: str, var: ctk.StringVar) -> None:
        value = var.get()
        client = self._client

        def task() -> None:
            client.uci_set(f"homeproxy.config.{key}", value)
            client.uci_commit("homeproxy")

        run_async(self, task, lambda _r: self._mark_dirty(), lambda e: self._status.configure(
            text=f"Ошибка: {e}", text_color=self.p.fail))

    def _restart(self) -> None:
        self._restart_btn.configure(state="disabled", text="Применяю…")
        client = self._client
        run_async(self, lambda: client.ubus_homeproxy("diag_service_restart", timeout=40),
                  self._after_restart, lambda e: self._status.configure(
                      text=f"Ошибка: {e}", text_color=self.p.fail))

    def _after_restart(self, res: dict[str, Any]) -> None:
        self._restart_btn.configure(text="Применить изменения")
        if res.get("result"):
            self._dirty = False
            self._status.configure(text="Изменения применены.", text_color=self.p.ok)
        else:
            self._restart_btn.configure(state="normal")
            self._status.configure(text="Не удалось применить изменения.", text_color=self.p.fail)
