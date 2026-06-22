# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Overview / dashboard — the default page of advanced mode, mirroring LuCI's main
status view: system header (host/uptime/IP), CPU & RAM, the active URLTest node
with latency colouring, an editable Main-Node / URLTest pool, DNS test results,
the active routing rules (read-only, with brand logos), DHCP devices, and the
home Wi-Fi networks with a join QR.

All RPC/SSH work runs off the Tk thread; the page paints once from one gather.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

import customtkinter as ctk

from ..engine import access as access_engine
from ..engine import core_health
from ..engine import network as net_engine
from ..engine import nodes as nodes_engine
from ..engine import overview as ov_engine
from ..engine import rules as rules_engine
from ..router import RouterClient
from . import flags
from . import icons
from . import kit
from .theme import Palette, fonts
from .worker import post_to, run_async
from ..i18n import N_, _

# Latency colour thresholds — identical scheme to the diagnostics screen and the
# LuCI status/client/diagnostics views (see reference_urltest_timeout_sentinel):
# <3000 green · 3000–65534 orange · 65535 red (confirmed timeout) · null/0 gray.
_SLOW_MS = 3000
_NODE_TIMEOUT_MS = 65535

_URLTEST_LABEL = N_("Автоматическая смена — по доступности и задержке (мс)")
_MAX_DEVICES = 40
# uplink proto (uci) → human label for the internet-connection card.
_PROTO_LABELS = {
    "dhcp": "DHCP", "dhcpv6": "DHCPv6", "pppoe": "PPPoE",
    "static": N_("Статический IP"), "wwan": "Wi-Fi",
}
_AUTO_MS = 2000  # auto-refresh cadence for the live cards (Система / Активный сервер)

_DNS_HELP = N_(
    "DNS — это «справочник» интернета: превращает имена сайтов (mail.ru, youtube.com) "
    "в IP-адреса, по которым устройство к ним подключается.\n"
    "• «Россия» — DNS для российских сайтов: они открываются напрямую, быстро и без прокси.\n"
    "• «Защищённый» — DNS по шифрованному каналу (DoH/DoT) для остального трафика: "
    "провайдер не видит и не может подменить ваши запросы."
)


class OverviewScreen(ctk.CTkFrame):
    def __init__(
        self,
        master: ctk.CTkBaseClass,
        palette: Palette,
        client: RouterClient,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._pool_selected: set[str] = set()
        self._pool_nodes: list[nodes_engine.Node] = []
        self._pool_enabled = True
        self._qr_imgs: list[ctk.CTkImage] = []  # keep refs alive
        # Auto-refresh of the live status cards only (Система / Активный сервер).
        self._auto_on = True
        self._auto_job: Optional[str] = None
        self._inflight = False
        self._sys_host: Optional[ctk.CTkFrame] = None
        self._uplink_host: Optional[ctk.CTkFrame] = None
        self._active_host: Optional[ctk.CTkFrame] = None
        # Live cards are built once, then refreshed in place (no destroy/rebuild =
        # no flicker). These flags reset on each full render (hosts recreated).
        self._sys_built = False
        self._uplink_built = False
        self._active_built = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_header()
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=2, column=0, padx=24, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)
        self.bind("<Destroy>", self._on_destroy)
        self.refresh()

    # ----- header / progress -------------------------------------------

    def _build_header(self) -> None:
        p = self.p
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, padx=24, pady=(20, 4), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self._host_lbl = ctk.CTkLabel(bar, text=_("Обзор"), font=fonts.title(), text_color=p.text,
                                      image=kit.icon(kit._ICON_FOR["overview"], 26), compound="left",
                                      anchor="w")
        self._host_lbl.grid(row=0, column=0, sticky="w")
        # Auto-refresh indicator (sits where the refresh button used to be): a
        # clickable green/red dot + label. Green = on, red = off; one click toggles.
        self._auto_box = ctk.CTkFrame(bar, fg_color=p.surface, corner_radius=8)
        self._auto_box.grid(row=0, column=1, padx=(8, 0))
        self._auto_dot = ctk.CTkLabel(self._auto_box, text="●", font=fonts.body(), text_color=p.ok)
        self._auto_dot.grid(row=0, column=0, padx=(10, 6), pady=6)
        self._auto_txt = ctk.CTkLabel(self._auto_box, text=_("Авто-обновление страницы"),
                                      font=fonts.small(), text_color=p.text)
        self._auto_txt.grid(row=0, column=1, padx=(0, 12), pady=6)
        for w in (self._auto_box, self._auto_dot, self._auto_txt):
            w.bind("<Button-1>", self._toggle_auto)
            w.configure(cursor="hand2")
        self._sub_lbl = ctk.CTkLabel(self, text="", font=fonts.small(), text_color=p.text_muted,
                                     anchor="w")
        self._sub_lbl.grid(row=1, column=0, padx=24, sticky="w")

    # ----- gather / refresh --------------------------------------------

    def refresh(self) -> None:
        """Full manual refresh: repaint every card (incl. the interactive Пул
        серверов). Guarded so it never overlaps an in-flight auto pull."""
        if self._inflight:
            return
        self._inflight = True
        self._sub_lbl.configure(text=_("Собираю данные…"), text_color=self.p.text_muted)
        client = self._client
        run_async(self, lambda: self._gather(client), self._render_full, self._on_error)

    @staticmethod
    def _gather(client: RouterClient) -> dict[str, Any]:
        def safe(fn: Callable[[], Any], default: Any) -> Any:
            try:
                return fn()
            except Exception:  # noqa: BLE001 — one dead RPC shouldn't blank the page
                return default

        d: dict[str, Any] = {}
        d["sys"] = safe(lambda: ov_engine.system_info(client), ov_engine.SystemInfo(lan_ip=client.host))
        d["uplink"] = safe(lambda: net_engine.uplink_info(client), None)
        d["active"] = safe(lambda: client.ubus_homeproxy("clash_active_node", timeout=15), {})
        d["core"] = safe(lambda: client.ubus_homeproxy("diag_core_check", timeout=15), {})
        d["core_failure"] = safe(lambda: core_health.diagnose_core_failure(client, core=d["core"]), None)
        d["nodes"] = safe(lambda: nodes_engine.list_nodes(client), [])
        d["main"] = safe(lambda: nodes_engine.get_main_node(client), "")
        d["pool"] = safe(lambda: client.uci_get_list(nodes_engine.URLTEST_NODES_KEY), [])
        d["interval"] = safe(lambda: client.uci_get("homeproxy.config.main_urltest_interval"), "") or "180"
        d["tolerance"] = safe(lambda: client.uci_get("homeproxy.config.main_urltest_tolerance"), "") or "150"
        d["dns"] = safe(lambda: client.ubus_homeproxy("diag_dns_ru", timeout=15), {})
        d["rules"] = safe(lambda: rules_engine.list_rules(client), [])
        d["devices"] = safe(lambda: access_engine.list_devices(client), [])
        aps = safe(lambda: net_engine.ap_credentials(client), [])
        # Pre-render QR PIL images off the Tk thread; the CTkImage is built in render.
        d["wifi"] = [(ap, ov_engine.wifi_qr_image(
            ov_engine.wifi_qr_payload(ap.ssid, ap.key, ap.encryption, ap.hidden))) for ap in aps]
        return d

    @staticmethod
    def _gather_status(client: RouterClient) -> dict[str, Any]:
        """Lightweight gather for the auto-refreshed live cards only (Система /
        Активный сервер) — no DNS/rules/devices/Wi-Fi/QR work."""
        def safe(fn: Callable[[], Any], default: Any) -> Any:
            try:
                return fn()
            except Exception:  # noqa: BLE001
                return default

        d: dict[str, Any] = {}
        d["sys"] = safe(lambda: ov_engine.system_info(client), ov_engine.SystemInfo(lan_ip=client.host))
        d["active"] = safe(lambda: client.ubus_homeproxy("clash_active_node", timeout=15), {})
        d["core"] = safe(lambda: client.ubus_homeproxy("diag_core_check", timeout=15), {})
        d["core_failure"] = safe(lambda: core_health.diagnose_core_failure(client, core=d["core"]), None)
        d["nodes"] = safe(lambda: nodes_engine.list_nodes(client), [])
        return d

    def _on_error(self, exc: BaseException) -> None:
        self._inflight = False
        self._sub_lbl.configure(text=_("Ошибка: {0}").format(exc), text_color=self.p.fail)
        self._schedule_auto()

    # ----- auto-refresh (live cards only) ------------------------------

    def _toggle_auto(self, _evt: Any = None) -> None:
        if self._auto_on:
            self._auto_on = False
            if self._auto_job is not None:
                self.after_cancel(self._auto_job)
                self._auto_job = None
            self._set_indicator()
        else:
            self._auto_on = True
            self._set_indicator()
            self._schedule_auto()

    def _set_indicator(self) -> None:
        """Dot: green when auto-refresh is on, red when off. (No loading state.)"""
        if not self.winfo_exists():
            return
        self._auto_dot.configure(text_color=self.p.ok if self._auto_on else self.p.fail)

    def _schedule_auto(self) -> None:
        if not self._auto_on or not self.winfo_exists():
            return
        if self._auto_job is not None:
            self.after_cancel(self._auto_job)
        self._auto_job = self.after(_AUTO_MS, self._auto_tick)

    def _auto_tick(self) -> None:
        self._auto_job = None
        if not self._auto_on or not self.winfo_exists():
            return
        if self._inflight:  # a pull is already running — retry on the next tick
            self._schedule_auto()
            return
        self._inflight = True
        client = self._client
        run_async(self, lambda: self._gather_status(client), self._on_auto_done, self._on_auto_err)

    def _on_auto_done(self, d: dict[str, Any]) -> None:
        self._inflight = False
        if self.winfo_exists():
            self._render_live(d)
        self._schedule_auto()

    def _on_auto_err(self, _exc: BaseException) -> None:
        self._inflight = False
        self._schedule_auto()

    def _on_destroy(self, evt: Any) -> None:
        if evt.widget is self:
            self._auto_on = False
            if self._auto_job is not None:
                try:
                    self.after_cancel(self._auto_job)
                except Exception:  # noqa: BLE001
                    pass
                self._auto_job = None

    # ----- render -------------------------------------------------------

    def _render_full(self, d: dict[str, Any]) -> None:
        self._inflight = False
        self._pool_selected = set()
        self._qr_imgs.clear()
        for w in self._body.winfo_children():
            w.destroy()

        self._update_header(d["sys"])

        # Persistent hosts for the two auto-refreshed cards (rebuilt in place on each
        # tick); everything below is manual-refresh only so edits aren't clobbered.
        self._sys_host = ctk.CTkFrame(self._body, fg_color="transparent")
        self._sys_host.grid(row=0, column=0, sticky="ew")
        self._sys_host.grid_columnconfigure(0, weight=1)
        self._uplink_host = ctk.CTkFrame(self._body, fg_color="transparent")
        self._uplink_host.grid(row=1, column=0, sticky="ew")
        self._uplink_host.grid_columnconfigure(0, weight=1)
        self._active_host = ctk.CTkFrame(self._body, fg_color="transparent")
        self._active_host.grid(row=2, column=0, sticky="ew")
        self._active_host.grid_columnconfigure(0, weight=1)

        self._sys_built = False
        self._uplink_built = False
        self._active_built = False
        self._render_system(d["sys"])
        self._render_uplink(d)
        self._render_active(d)
        row = 3
        row = self._render_mainnode(d, row)
        row = self._render_dns(d, row)
        row = self._render_rules(d, row)
        row = self._render_devices(d, row)
        row = self._render_wifi(d, row)

        self._set_indicator()
        self._schedule_auto()

    def _render_live(self, d: dict[str, Any]) -> None:
        """Repaint only the auto-refreshed cards (Система / Активный сервер)."""
        if self._sys_host is None or not self._sys_host.winfo_exists():
            return
        self._update_header(d["sys"])
        self._render_system(d["sys"])
        self._render_active(d)

    def _update_header(self, sys_info: "ov_engine.SystemInfo") -> None:
        p = self.p
        self._host_lbl.configure(text=sys_info.hostname or _("Обзор"))
        sub = []
        if sys_info.model:
            sub.append(sys_info.model)
        sub.append(_("аптайм {0}").format(ov_engine.format_uptime(sys_info.uptime_s)))
        sub.append(_("IP роутера {0}").format(sys_info.lan_ip))
        self._sub_lbl.configure(text="  ·  ".join(sub), text_color=p.text_muted)

    def _card(self, title: str, row: int, parent: Optional[ctk.CTkBaseClass] = None) -> ctk.CTkFrame:
        parent = parent if parent is not None else self._body
        card = ctk.CTkFrame(parent, fg_color=self.p.surface, corner_radius=12)
        card.grid(row=row, column=0, pady=(0, 12), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=fonts.heading(), text_color=self.p.text).grid(
            row=0, column=0, padx=16, pady=(12, 6), sticky="w")
        return card

    # ----- system (CPU / RAM) ------------------------------------------

    def _render_system(self, s: ov_engine.SystemInfo) -> None:
        # s.mem_pct is the USED percentage; this meter reports FREE (per the spec),
        # so invert it for both the number and the bar length.
        free_pct = max(0, 100 - s.mem_pct)
        free_mb = max(0, s.mem_total_mb - s.mem_used_mb)
        mem_detail = (_("{0}%  ·  свободно {1} из {2} МБ").format(free_pct, free_mb, s.mem_total_mb)
                      if s.mem_total_mb else f"{free_pct}%")
        if not self._sys_built:
            card = self._card(_("Система"), 0, parent=self._sys_host)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
            inner.grid_columnconfigure(0, weight=1)
            self._cpu_detail, self._cpu_bar = self._meter(
                inner, 0, _("Загрузка процессора"), s.cpu_pct, f"{s.cpu_pct}%")
            self._mem_detail, self._mem_bar = self._meter(
                inner, 1, _("Свободно ОЗУ"), free_pct, mem_detail, invert_color=True)
            self._sys_built = True
        else:  # update existing widgets in place — no flicker
            self._update_meter(self._cpu_detail, self._cpu_bar, s.cpu_pct, f"{s.cpu_pct}%")
            self._update_meter(self._mem_detail, self._mem_bar, free_pct, mem_detail, invert_color=True)

    def _meter(self, parent: ctk.CTkBaseClass, r: int, label: str, pct: int, detail: str,
               *, invert_color: bool = False) -> tuple[ctk.CTkLabel, ctk.CTkProgressBar]:
        p = self.p
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=r, column=0, sticky="ew", pady=4)
        box.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(box, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text=label, font=fonts.body(), text_color=p.text, anchor="w").grid(
            row=0, column=0, sticky="w")
        detail_lbl = ctk.CTkLabel(top, text=detail, font=fonts.small(), text_color=p.text_muted,
                                  anchor="e")
        detail_lbl.grid(row=0, column=1, sticky="e")
        bar = ctk.CTkProgressBar(box, height=8, progress_color=self._meter_color(pct, invert_color))
        bar.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        bar.set(max(0.0, min(1.0, pct / 100)))
        return detail_lbl, bar

    def _meter_color(self, pct: int, invert_color: bool) -> str:
        # High usage = warn/fail colour. For "free RAM" the meaning is inverted
        # (low free = bad), so colour by the load (100 - free).
        p = self.p
        load = (100 - pct) if invert_color else pct
        return p.ok if load < 70 else (p.warn if load < 90 else p.fail)

    def _update_meter(self, detail_lbl: ctk.CTkLabel, bar: ctk.CTkProgressBar, pct: int,
                      detail: str, *, invert_color: bool = False) -> None:
        detail_lbl.configure(text=detail)
        bar.configure(progress_color=self._meter_color(pct, invert_color))
        bar.set(max(0.0, min(1.0, pct / 100)))

    # ----- internet uplink (WAN / WWAN) --------------------------------

    def _render_uplink(self, d: dict[str, Any]) -> None:
        p = self.p
        info = d.get("uplink")
        if info is None or not getattr(info, "present", False):
            main = _("Не удалось определить интерфейс выхода в интернет.")
            detail, dot = "", p.warn
        else:
            if info.kind == "wifi":
                parts = [f"Wi-Fi «{info.wifi_ssid}»" if info.wifi_ssid else _("Wi-Fi (клиент)")]
                if info.wifi_band:
                    parts.append(info.wifi_band.replace(".", ",") + _(" ГГц"))
                if info.wifi_rate_mbps:
                    parts.append(_("{0} Мбит/с").format(info.wifi_rate_mbps))
            else:
                parts = [_("Кабель")]
                sp = net_engine.link_speed_label(info.link_speed_mbps)
                if sp:
                    parts.append(sp)
            parts.append(_(_PROTO_LABELS.get(info.proto, (info.proto or "").upper() or "—")))
            if info.ip:
                parts.append(info.ip)
            main = "   ·   ".join(parts)
            if info.internet:
                detail, dot = _("Есть подключение к интернету"), p.ok
            else:
                detail, dot = _("Нет подключения к интернету"), p.fail

        if not self._uplink_built:
            card = self._card(_("Подключение к интернету"), 0, parent=self._uplink_host)
            # WAN info is loaded once (not auto-polled) — a small button refreshes
            # just this card on demand.
            self._up_refresh_btn = ctk.CTkButton(
                card, text=kit.REFRESH_GLYPH, width=28, height=28, corner_radius=8, font=fonts.body(),
                fg_color=p.surface_hover, hover_color=p.border, text_color=p.text,
                command=self._refresh_uplink)
            self._up_refresh_btn.grid(row=0, column=1, padx=(0, 12), pady=(10, 0), sticky="e")
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="w")
            self._up_dot, self._up_main = self._status_row(inner, 0, big=True)
            self._up_detail = ctk.CTkLabel(inner, text="", font=fonts.small(),
                                           text_color=p.text_muted, anchor="w")
            self._up_detail.grid(row=1, column=0, sticky="w", pady=(4, 0))
            self._uplink_built = True
        self._up_dot.configure(text_color=dot)
        self._up_main.configure(text=main)
        self._up_detail.configure(text=detail)

    def _refresh_uplink(self) -> None:
        """On-demand refresh of just the WAN card (not part of the auto-poll)."""
        if not self.winfo_exists() or not self._uplink_built:
            return
        self._up_refresh_btn.configure(state="disabled")
        self._up_detail.configure(text=_("Обновляю…"), text_color=self.p.text_muted)
        client = self._client

        def done(info: Any) -> None:
            if self.winfo_exists():
                self._render_uplink({"uplink": info})
                self._up_refresh_btn.configure(state="normal")

        def err(e: BaseException) -> None:
            if self.winfo_exists():
                self._up_detail.configure(text=_("Ошибка: {0}").format(e), text_color=self.p.fail)
                self._up_refresh_btn.configure(state="normal")

        run_async(self, lambda: net_engine.uplink_info(client), done, err)

    # ----- active node --------------------------------------------------

    def _delay_display(self, delay: Optional[int]) -> tuple[str, str]:
        """(text, colour) for a latency, same epistemics as everywhere else."""
        p = self.p
        if delay == _NODE_TIMEOUT_MS:
            return _("{0} ms (таймаут)").format(delay), p.fail
        if not delay:
            return _("нет данных"), p.text_muted
        if delay >= _SLOW_MS:
            return f"{delay} ms", p.warn
        return f"{delay} ms", p.ok

    @staticmethod
    def _resolve_node_name(raw: Optional[str], nodes: list) -> str:
        """Map a Clash outbound tag (``cfg-<section>-out``) back to the node's
        human label from the node list; fall back to the raw tag for specials
        (main-out, direct-out, …) or an unknown section."""
        if not raw:
            return "—"
        m = re.match(r"^cfg-(.+)-out$", raw)
        if m:
            section = m.group(1)
            for n in nodes:
                if n.section == section:
                    return n.label or n.section
        return raw

    def _render_active(self, d: dict[str, Any]) -> None:
        p = self.p
        node = d.get("active") or {}
        core = d.get("core") or {}

        # Main line (server name + delay, or a "starting/stopped" message). Don't
        # surface the raw RPC error — right after a (re)start the Clash API needs a
        # few seconds, so frame it as "still starting" while the core is running.
        if not isinstance(node, dict) or "error" in node or not node.get("node"):
            core_running = isinstance(core, dict) and bool(core.get("running"))
            if core_running:
                main_text = _("Сервис ещё запускается — активный сервер появится через несколько секунд.")
                main_dot = p.text_muted
            else:
                main_text = _("Прокси-сервис не запущен — активного сервера пока нет.")
                main_dot = p.warn
        else:
            delay_s, main_dot = self._delay_display(node.get("delay"))
            grp = (_("   ·   группа: {0} ({1})").format(node.get('group'), node.get('group_type'))
                   if node.get("group") else "")
            name = self._resolve_node_name(node.get("node"), d.get("nodes", []))
            main_text = f"{name}   ·   {node.get('type') or '—'}   ·   {delay_s}{grp}"

        core_txt, core_color, bd_txt, bd_color, zp_txt, zp_color = self._core_status(core)

        if not self._active_built:
            card = self._card(_("Активный сервер"), 0, parent=self._active_host)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="w")
            self._act_dot, self._act_txt = self._status_row(inner, 0, big=True)
            self._core_dot, self._core_lbl = self._status_row(inner, 1, big=False)
            self._bd_dot, self._bd_lbl = self._status_row(inner, 2, big=False)
            self._zapret_dot, self._zapret_lbl = self._status_row(inner, 3, big=False)
            # Config-error explainer (hidden unless the core won't start). Tells the
            # user it's a config problem on a NAMED server, not a broken core.
            self._fail_lbl = ctk.CTkLabel(inner, text="", font=fonts.small(), text_color=p.warn,
                                          anchor="w", justify="left", wraplength=560)
            self._fail_lbl.grid(row=4, column=0, sticky="w", pady=(8, 0))
            self._fail_lbl.grid_remove()
            self._active_built = True
        # Update in place (no destroy/rebuild = no flicker).
        self._act_dot.configure(text_color=main_dot)
        flags.apply_to_label(self._act_txt, main_text)
        self._core_dot.configure(text_color=core_color)
        self._core_lbl.configure(text=core_txt)
        self._bd_dot.configure(text_color=bd_color)
        self._bd_lbl.configure(text=bd_txt)
        self._zapret_dot.configure(text_color=zp_color)
        self._zapret_lbl.configure(text=zp_txt)
        cf = d.get("core_failure")
        if cf:
            head, steps = core_health.failure_message(cf)
            self._fail_lbl.configure(text="⚠ " + head + "\n• " + "\n• ".join(steps))
            self._fail_lbl.grid()
        else:
            self._fail_lbl.grid_remove()

    def _status_row(self, parent: ctk.CTkBaseClass, r: int, *, big: bool
                    ) -> tuple[ctk.CTkLabel, ctk.CTkLabel]:
        """A reusable dot + text line; returns (dot, text) for in-place updates."""
        p = self.p
        font = fonts.body() if big else fonts.small()
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=r, column=0, sticky="w", pady=(0 if r == 0 else 4, 0))
        dot = ctk.CTkLabel(box, text="●", font=font, text_color=p.text_muted)
        dot.pack(side="left")
        txt = ctk.CTkLabel(box, text="", font=font, text_color=p.text if big else p.text_muted,
                           anchor="w", justify="left", wraplength=560)
        txt.pack(side="left", padx=(6, 0))
        return dot, txt

    @staticmethod
    def _clean_version(v: str) -> str:
        """Pull a readable X.Y.Z(-tag) out of a noisy core version string (sing-box-
        extended prints a long line with build tags + revision)."""
        import re

        if not v:
            return ""
        m = re.search(r"\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?", v)
        return m.group(0) if m else v.split()[0][:24]

    def _core_status(self, core: dict) -> tuple[str, str, str, str, str, str]:
        """(core_text, core_colour, byedpi_text, byedpi_colour) — pure data, no
        widgets, so the active card can be refreshed in place."""
        p = self.p
        if not isinstance(core, dict):
            return "", p.text_muted, "", p.text_muted
        binary = core.get("binary") or ""
        if "hiddify" in binary or (core.get("hiddify_installed") and not core.get("singbox_installed")):
            name = "hiddify-core"
        elif "sing-box" in binary or core.get("singbox_installed"):
            name = "sing-box"
        else:
            name = ""  # no core binary present
        running = bool(core.get("running"))
        ver = self._clean_version(core.get("version") or "")
        if not name:
            # No core installed at all — say so plainly instead of "Ядро: ядро · остановлено".
            core_txt = _("Ядро: не установлено")
        else:
            core_txt = _("Ядро: {0}").format(name) + (f" {ver}" if ver else "")
            core_txt += _("   ·   запущено") if running else _("   ·   остановлено")
        core_color = p.ok if running else p.fail
        # ByeDPI runs independently of the core; show it whatever its state.
        if not core.get("byedpi_installed"):
            bd_txt, bd_color = _("ByeDPI: не установлен"), p.text_muted
        elif core.get("byedpi_running"):
            bd_txt, bd_color = _("ByeDPI: запущен"), p.ok
        else:
            bd_txt, bd_color = _("ByeDPI: установлен, остановлен"), p.warn
        # Zapret (nfqws2) runs independently of the core too — show it like ByeDPI.
        if not core.get("zapret_installed"):
            zp_txt, zp_color = _("Zapret: не установлен"), p.text_muted
        elif core.get("zapret_running"):
            zp_txt, zp_color = _("Zapret: запущен"), p.ok
        else:
            zp_txt, zp_color = _("Zapret: установлен, остановлен"), p.warn
        return core_txt, core_color, bd_txt, bd_color, zp_txt, zp_color

    # ----- main node / URLTest pool (interactive) -----------------------

    def _render_mainnode(self, d: dict[str, Any], row: int) -> int:
        p = self.p
        nodes: list[nodes_engine.Node] = d.get("nodes", [])
        main = d.get("main", "")
        pool = set(d.get("pool", []))
        card = self._card(_("Пул серверов"), row)

        # section <-> label maps; URLTest is a synthetic choice.
        self._label_to_section = {_(_URLTEST_LABEL): "urltest"}
        values = [_(_URLTEST_LABEL)]
        for n in nodes:
            lbl = f"{n.label or n.section} ({n.type})"
            # de-dup labels defensively
            while lbl in self._label_to_section:
                lbl += " "
            self._label_to_section[lbl] = n.section
            values.append(lbl)
        cur_label = next((lbl for lbl, sec in self._label_to_section.items()
                          if sec == main), _(_URLTEST_LABEL) if main == "urltest" else values[0])

        sel = ctk.CTkFrame(card, fg_color="transparent")
        sel.grid(row=1, column=0, padx=16, pady=(0, 6), sticky="ew")
        sel.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(sel, text=_("Сервер"), font=fonts.body(), text_color=p.text_muted).grid(
            row=0, column=0, padx=(0, 10), sticky="w")
        self._main_menu = ctk.CTkOptionMenu(sel, values=values, font=fonts.body(),
                                            fg_color=p.surface_hover, button_color=p.accent,
                                            button_hover_color=p.accent_hover,
                                            command=lambda _l: self._sync_pool_state())
        self._main_menu.set(cur_label)
        self._main_menu.grid(row=0, column=1, sticky="ew")

        # URLTest pool: a checkbox per node. Selected nodes float to the top of the
        # list (alphabetical); unchecking drops a node back into the alphabetical
        # tail. State lives in a set, so the list re-sorts live on each toggle.
        self._pool_nodes = list(nodes)
        self._pool_selected = {n.section for n in nodes if n.section in pool}
        self._pool_enabled = True
        self._pool_frame = ctk.CTkFrame(card, fg_color="transparent")
        self._pool_frame.grid(row=2, column=0, padx=16, pady=(2, 6), sticky="ew")
        self._pool_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self._pool_frame, text=_("Серверы в пуле"), font=fonts.small(),
                     text_color=p.text_muted, anchor="w").grid(row=0, column=0, sticky="w", pady=(0, 2))
        self._pool_list = ctk.CTkScrollableFrame(self._pool_frame, fg_color=p.bg, height=160)
        self._pool_list.grid(row=1, column=0, sticky="ew")
        self._pool_list.grid_columnconfigure(0, weight=1)
        self._render_pool()

        # interval / tolerance — each with an explanation (wording from LuCI po/ru).
        tune = ctk.CTkFrame(card, fg_color="transparent")
        tune.grid(row=3, column=0, padx=16, pady=(0, 6), sticky="ew")
        tune.grid_columnconfigure(0, weight=1)
        self._interval_entry = self._tuning_field(
            tune, 0, _("Интервал проверки (с)"), str(d.get("interval", "180")),
            _("Время в секундах: меньше = серверы тестируются чаще, больше = реже тесты — меньше нагрузки."))
        self._tol_entry = self._tuning_field(
            tune, 2, _("Допуск (мс)"), str(d.get("tolerance", "150")),
            _("Минимальная разница задержек (мс) для переключения на более быстрый сервер — "
            "предотвращает постоянное переключение между серверами с близкой задержкой."))

        self._apply_btn = ctk.CTkButton(card, text=_("Применить изменения"), font=fonts.body(),
                                        width=200, fg_color=p.accent, text_color=p.accent_fg, hover_color=p.accent_hover,
                                        command=self._apply_mainnode)
        self._apply_btn.grid(row=4, column=0, padx=16, pady=(2, 12), sticky="w")
        self._mn_status = ctk.CTkLabel(card, text="", font=fonts.small(), text_color=p.text_muted)
        self._mn_status.grid(row=5, column=0, padx=16, pady=(0, 10), sticky="w")
        self._sync_pool_state()
        return row + 1

    @staticmethod
    def _node_caption(n: "nodes_engine.Node") -> str:
        return f"{n.label or n.section} ({n.type})"

    @staticmethod
    def _node_sort_key(n: "nodes_engine.Node") -> str:
        return (n.label or n.section).lower()

    def _render_pool(self) -> None:
        """Rebuild the pool list: checked nodes on top (alphabetical), then the
        unchecked ones (alphabetical). Called on (re)load and mode change only —
        NOT on every toggle, so checking a box doesn't reshuffle the list under
        the cursor. The re-sort lands after "Применить изменения" (via refresh)."""
        p = self.p
        for w in self._pool_list.winfo_children():
            w.destroy()
        chosen = sorted((n for n in self._pool_nodes if n.section in self._pool_selected),
                        key=self._node_sort_key)
        rest = sorted((n for n in self._pool_nodes if n.section not in self._pool_selected),
                      key=self._node_sort_key)
        state = "normal" if self._pool_enabled else "disabled"
        for i, n in enumerate(chosen + rest):
            # Row = [checkbox] [flag-image name label]. A checkbox can't hold the
            # flag image, so the name lives in its own label (flags.name_label draws
            # the flag as a picture on Windows/Linux); clicking it toggles the box.
            row = ctk.CTkFrame(self._pool_list, fg_color="transparent")
            row.grid(row=i, column=0, sticky="ew", padx=8, pady=2)
            row.grid_columnconfigure(1, weight=1)
            cb = ctk.CTkCheckBox(row, text="", width=20, checkbox_width=20, checkbox_height=20,
                                 fg_color=p.accent, hover_color=p.accent_hover, state=state,
                                 command=lambda sec=n.section: self._toggle_pool(sec))
            cb.grid(row=0, column=0, padx=(0, 6))
            if n.section in self._pool_selected:
                cb.select()
            lbl = flags.name_label(row, self._node_caption(n), font=fonts.body(),
                                   text_color=p.text, anchor="w")
            lbl.grid(row=0, column=1, sticky="w")
            if self._pool_enabled:
                lbl.bind("<Button-1>", lambda _e, c=cb: c.toggle())

    def _toggle_pool(self, section: str) -> None:
        # Only track the selection — do NOT re-render. The checkbox toggles its
        # own mark; reshuffling here is what caused the lag/churn on every click.
        # Order is re-sorted after "Применить изменения" (refresh rebuilds it).
        if section in self._pool_selected:
            self._pool_selected.discard(section)
        else:
            self._pool_selected.add(section)

    def _tuning_field(self, parent: ctk.CTkBaseClass, r: int, label: str, value: str,
                      hint: str) -> ctk.CTkEntry:
        """A labelled numeric entry with an explanation line below it."""
        p = self.p
        head = ctk.CTkFrame(parent, fg_color="transparent")
        head.grid(row=r, column=0, sticky="w", pady=(4, 0))
        ctk.CTkLabel(head, text=label, font=fonts.small(),
                     text_color=p.text_muted).pack(side="left", padx=(0, 8))
        entry = ctk.CTkEntry(head, width=80, font=fonts.body())
        entry.insert(0, value)
        entry.pack(side="left")
        ctk.CTkLabel(parent, text=hint, font=fonts.small(), text_color=p.text_muted,
                     wraplength=540, justify="left", anchor="w").grid(
            row=r + 1, column=0, sticky="w", pady=(0, 2))
        return entry

    def _sync_pool_state(self) -> None:
        """Pool/tuning controls matter only in URLTest mode — gray them otherwise."""
        is_urltest = self._label_to_section.get(self._main_menu.get()) == "urltest"
        self._pool_enabled = is_urltest
        self._render_pool()
        state = "normal" if is_urltest else "disabled"
        for ent in (self._interval_entry, self._tol_entry):
            ent.configure(state=state)

    def _apply_mainnode(self) -> None:
        value = self._label_to_section.get(self._main_menu.get(), "urltest")
        pool = list(self._pool_selected)
        interval = self._interval_entry.get().strip() or "180"
        tolerance = self._tol_entry.get().strip() or "150"
        if value == "urltest" and not pool:
            self._mn_status.configure(text=_("Выберите хотя бы один сервер для пула URLTest."),
                                      text_color=self.p.warn)
            return
        if not (interval.isdigit() and tolerance.isdigit()):
            self._mn_status.configure(text=_("Интервал и допуск должны быть числами."),
                                      text_color=self.p.warn)
            return
        self._apply_btn.configure(state="disabled", text=_("Применяю…"))
        self._mn_status.configure(text=_("Применяю изменения…"), text_color=self.p.text_muted)
        client = self._client

        def task() -> bool:
            nodes_engine.set_main_node(client, value, urltest_nodes=pool)
            if value == "urltest":
                client.uci_set("homeproxy.config.main_urltest_interval", interval)
                client.uci_set("homeproxy.config.main_urltest_tolerance", tolerance)
                client.uci_commit("homeproxy")
            return nodes_engine.apply_and_restart(client)

        run_async(self, task, self._after_apply, self._apply_err)

    def _after_apply(self, ok: bool) -> None:
        self._apply_btn.configure(state="normal", text=_("Применить изменения"))
        if ok:
            self._mn_status.configure(text=_("Изменения применены."), text_color=self.p.ok)
            post_to(self, self.refresh)
        else:
            self._mn_status.configure(text=_("Не удалось применить изменения."), text_color=self.p.fail)

    def _apply_err(self, exc: BaseException) -> None:
        self._apply_btn.configure(state="normal", text=_("Применить изменения"))
        self._mn_status.configure(text=_("Ошибка: {0}").format(exc), text_color=self.p.fail)

    # ----- DNS ----------------------------------------------------------

    def _render_dns(self, d: dict[str, Any], row: int) -> int:
        p = self.p
        dns = d.get("dns") or {}
        if not isinstance(dns, dict) or dns.get("skip"):
            return row  # only meaningful in the Russia (proxy_banned_ru) mode
        card = self._card("DNS", row)
        # Help "?" toggle next to the title (explains DNS + Россия/Защищённый).
        ctk.CTkButton(card, text="?", width=26, height=26, corner_radius=13,
                      font=fonts.small(), fg_color=p.surface_hover, hover_color=p.border,
                      text_color=p.text, command=self._toggle_dns_help).grid(
            row=0, column=1, padx=(0, 12), pady=(12, 6), sticky="e")
        self._dns_help_lbl = ctk.CTkLabel(card, text=_(_DNS_HELP), font=fonts.small(),
                                          text_color=p.text_muted, wraplength=560,
                                          justify="left", anchor="w")  # shown on demand
        self._dns_help_open = False
        if "error" in dns:
            ctk.CTkLabel(card, text=dns["error"], font=fonts.body(), text_color=p.text_muted,
                         anchor="w", wraplength=560, justify="left").grid(
                row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="w")
            return row + 1
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=1, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="ew")
        self._dns_row(inner, 0, _("Россия — протестировано на mail.ru"),
                      dns.get("russia_ok"), dns.get("russia_server"))
        self._dns_row(inner, 1, _("Защищённый — протестировано на andrevi.ch"),
                      dns.get("secure_ok"), dns.get("secure_server"))
        return row + 1

    def _toggle_dns_help(self) -> None:
        if getattr(self, "_dns_help_lbl", None) is None or not self._dns_help_lbl.winfo_exists():
            return
        if self._dns_help_open:
            self._dns_help_lbl.grid_remove()
        else:
            self._dns_help_lbl.grid(row=2, column=0, columnspan=2, padx=16, pady=(0, 12), sticky="w")
        self._dns_help_open = not self._dns_help_open

    def _dns_row(self, parent: ctk.CTkBaseClass, r: int, label: str,
                 ok: Optional[bool], server: Optional[str]) -> None:
        p = self.p
        color = p.warn if ok is None else (p.ok if ok else p.fail)
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=r, column=0, sticky="w", pady=2)
        ctk.CTkLabel(box, text="●", font=fonts.body(), text_color=color).pack(side="left")
        text = "  " + label + (f"   ·   {server}" if server else "")
        ctk.CTkLabel(box, text=text, font=fonts.body(), text_color=p.text, anchor="w").pack(side="left")

    # ----- rules (read-only, with logos) -------------------------------

    def _render_rules(self, d: dict[str, Any], row: int) -> int:
        p = self.p
        rules: list[rules_engine.RuRule] = d.get("rules", [])
        nodes: list[nodes_engine.Node] = d.get("nodes", [])
        card = self._card(_("Активные правила"), row)
        if not rules:
            ctk.CTkLabel(card, text=_("Правил нет — весь трафик идёт напрямую."), font=fonts.body(),
                         text_color=p.text_muted, anchor="w").grid(
                row=1, column=0, padx=16, pady=(0, 12), sticky="w")
            return row + 1
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        inner.grid_columnconfigure(0, weight=1)
        for i, r in enumerate(rules):
            line = ctk.CTkFrame(inner, fg_color="transparent")
            line.grid(row=i, column=0, sticky="w", pady=2)
            ic = icons.service_icon(r.source, size=20) if icons.has_real_icon(r.source) else None
            if ic is not None:
                ctk.CTkLabel(line, image=ic, text="").pack(side="left", padx=(0, 8))
            src = rules_engine.source_label(r.source)
            dst = rules_engine.node_label(r.node, nodes)
            ctk.CTkLabel(line, text=f"{src}  →  {dst}", font=fonts.body(), text_color=p.text,
                         anchor="w").pack(side="left")
        return row + 1

    # ----- devices (DHCP) ----------------------------------------------

    def _render_devices(self, d: dict[str, Any], row: int) -> int:
        p = self.p
        devices: list[access_engine.Device] = d.get("devices", [])
        card = self._card(_("Устройства в сети ({0})").format(len(devices)), row)
        if not devices:
            ctk.CTkLabel(card, text=_("Нет активных аренд DHCP."), font=fonts.body(),
                         text_color=p.text_muted, anchor="w").grid(
                row=1, column=0, padx=16, pady=(0, 12), sticky="w")
            return row + 1
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        inner.grid_columnconfigure(0, weight=1)
        for i, dev in enumerate(devices[:_MAX_DEVICES]):
            line = ctk.CTkFrame(inner, fg_color="transparent")
            line.grid(row=i, column=0, sticky="ew", pady=1)
            line.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(line, text=dev.hostname, font=fonts.body(), text_color=p.text,
                         anchor="w").grid(row=0, column=0, sticky="w")
            ctk.CTkLabel(line, text=dev.ip, font=fonts.small(), text_color=p.text_muted,
                         anchor="e").grid(row=0, column=1, padx=10, sticky="e")
        if len(devices) > _MAX_DEVICES:
            ctk.CTkLabel(inner, text=_("… и ещё {0} устройств").format(len(devices) - _MAX_DEVICES),
                         font=fonts.small(), text_color=p.text_muted, anchor="w").grid(
                row=_MAX_DEVICES, column=0, sticky="w", pady=(2, 0))
        return row + 1

    # ----- Wi-Fi + QR ---------------------------------------------------

    def _render_wifi(self, d: dict[str, Any], row: int) -> int:
        p = self.p
        wifi: list[tuple[net_engine.ApCred, Any]] = d.get("wifi", [])
        card = self._card(_("Wi-Fi сети роутера"), row)
        if not wifi:
            ctk.CTkLabel(card, text=_("Точка доступа не настроена."), font=fonts.body(),
                         text_color=p.text_muted, anchor="w").grid(
                row=1, column=0, padx=16, pady=(0, 12), sticky="w")
            return row + 1
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        inner.grid_columnconfigure(0, weight=1)
        for i, (ap, qr_pil) in enumerate(wifi):
            box = ctk.CTkFrame(inner, fg_color=p.bg, corner_radius=10)
            box.grid(row=i, column=0, sticky="ew", pady=4)
            box.grid_columnconfigure(0, weight=1)
            txt = ctk.CTkFrame(box, fg_color="transparent")
            txt.grid(row=0, column=0, padx=12, pady=12, sticky="nw")
            ctk.CTkLabel(txt, text=ap.ssid, font=fonts.heading(), text_color=p.text,
                         anchor="w").grid(row=0, column=0, sticky="w")
            band = _("{0} ГГц").format(ap.band) if ap.band and ap.band != "?" else ""
            meta = "  ·  ".join(x for x in (band, _("скрытая") if ap.hidden else "") if x)
            if meta:
                ctk.CTkLabel(txt, text=meta, font=fonts.small(), text_color=p.text_muted,
                             anchor="w").grid(row=1, column=0, sticky="w")
            if ap.key:
                ctk.CTkLabel(txt, text=_("Пароль: {0}").format(ap.key),
                             font=ctk.CTkFont(family="Consolas", size=13), text_color=p.text,
                             anchor="w").grid(row=2, column=0, sticky="w", pady=(4, 0))
            else:
                ctk.CTkLabel(txt, text=_("Открытая сеть (без пароля)"), font=fonts.small(),
                             text_color=p.text_muted, anchor="w").grid(row=2, column=0, sticky="w")
            if qr_pil is not None:
                img = ctk.CTkImage(light_image=qr_pil, dark_image=qr_pil, size=(150, 150))
                self._qr_imgs.append(img)
                qlbl = ctk.CTkLabel(box, image=img, text="")
                qlbl.grid(row=0, column=1, padx=12, pady=12, sticky="e")
                ctk.CTkLabel(box, text=_("Наведите камеру телефона"), font=fonts.small(),
                             text_color=p.text_muted).grid(row=1, column=1, padx=12, pady=(0, 10))
        return row + 1
