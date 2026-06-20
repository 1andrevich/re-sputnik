# SPDX-License-Identifier: GPL-2.0-only
"""Diagnostics screen — the app's "eyes" on a router, on live RPC data.

Gathers the luci.homeproxy diagnostics methods over SSH and renders them as
green/red status, the active node, provider/proxy IPs, per-site connectivity,
and the full sanitized text report (safe to copy/save — keys are redacted on the
device side). All RPC work runs off the Tk thread.
"""

from __future__ import annotations

import re
from tkinter import filedialog
from typing import Any, Callable, Optional

import customtkinter as ctk

from ..engine import ip_info
from ..engine import nodes as nodes_engine
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import post_to, run_async

OnBack = Callable[[], None]

# connection_check sites accepted by the backend, with display labels.
_SITES = [
    ("youtube", "YouTube"),
    ("google", "Google"),
    ("yandex", "Яндекс"),
    ("speedtest", "Speedtest"),
    ("baidu", "Baidu"),
]


Progress = Callable[[float, str], None]

# Total discrete steps for the progress bar: 7 RPCs + node list + one per probed site.
_TOTAL_STEPS = 8 + len(_SITES)

# Latency thresholds for the active node. URLTest reports 65535 ms (0xFFFF) on a
# health-check timeout (node selected but dead). But ANY very high latency means a
# barely-working node — so warn (orange) at/above _SLOW_MS, not only at the
# sentinel: 60 s would otherwise still show green.
_SLOW_MS = 3000          # ≥ this → orange warning (slow / probably not working)
_NODE_TIMEOUT_MS = 65535  # exact URLTest timeout sentinel → labelled "(таймаут)"


def _gather(client: RouterClient, progress: Optional[Progress] = None) -> dict[str, Any]:
    """Run every diagnostic RPC once; tolerate per-call failure. Reports progress
    (fraction, current-step label) so the UI can show it's working, not frozen."""

    def safe(method: str, params: Optional[dict] = None) -> dict:
        try:
            return client.ubus_homeproxy(method, params, timeout=15)
        except Exception as exc:  # noqa: BLE001 — surface as an error field, don't abort
            return {"error": str(exc)}

    done = 0

    def step(label: str) -> None:
        nonlocal done
        done += 1
        if progress:
            progress(done / _TOTAL_STEPS, label)

    data: dict[str, Any] = {}
    step("ядро"); data["core"] = safe("diag_core_check")
    step("конфиг"); data["config"] = safe("diag_config_check")
    step("активный сервер"); data["active_node"] = safe("clash_active_node")
    step("серверы")
    try:
        data["nodes"] = nodes_engine.list_nodes(client)
    except Exception:  # noqa: BLE001 — names just won't resolve, not fatal
        data["nodes"] = []
    step("IP"); data["ip"] = safe("clash_ip_info")
    step("DNS"); data["dns"] = safe("diag_dns_ru")
    step("nftables"); data["nft"] = safe("diag_nftables")
    step("отчёт"); data["report"] = safe("diag_report").get("report", "")
    # clash_ip_info relies on the Clash API "ipinfo" field, which sing-box-extended
    # doesn't populate → empty IP card. If the proxy IP is missing, fetch it
    # ourselves (directly + through the mixed proxy), which works on any core.
    ip = data.get("ip")
    proxy_ip = (ip.get("proxy") or {}).get("ip") if isinstance(ip, dict) else None
    if not proxy_ip:
        try:
            fetched = ip_info.fetch_ip_info(client)
            if fetched.get("direct") or fetched.get("proxy"):
                data["ip"] = fetched
        except Exception:  # noqa: BLE001 — fallback is best-effort
            pass

    conn: dict[str, Optional[bool]] = {}
    for key, label in _SITES:
        step(f"связь: {label}")
        res = safe("connection_check", {"site": key})
        conn[key] = bool(res.get("result")) if "result" in res else None
    data["conn"] = conn
    return data


class DiagnosticsScreen(ctk.CTkFrame):
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
        self._report_text = ""

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)
        self._build_header()
        self._body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self._body.grid(row=3, column=0, padx=24, sticky="nsew")
        self._body.grid_columnconfigure(0, weight=1)
        self.refresh()

    # ----- header -------------------------------------------------------

    def _build_header(self) -> None:
        p = self.p
        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=0, column=0, padx=24, pady=(20, 4), sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(bar, text="Диагностика", font=fonts.title(), text_color=p.text,
                     image=kit.icon(kit._ICON_FOR["diagnostics"], 26), compound="left").grid(
            row=0, column=0, sticky="w"
        )
        self._refresh_btn = ctk.CTkButton(
            bar, text=f"{kit.REFRESH_GLYPH} Обновить страницу", font=fonts.body(), width=180,
            fg_color=p.surface, hover_color=p.surface_hover, command=self.refresh,
        )
        self._refresh_btn.grid(row=0, column=1, padx=(8, 0))

        self._status = ctk.CTkLabel(self, text="", font=fonts.small(), text_color=p.text_muted)
        self._status.grid(row=1, column=0, padx=24, sticky="w")

        # Determinate progress bar — shown only while gathering, so the screen
        # never looks frozen during the (network-bound) probes.
        self._progress = ctk.CTkProgressBar(self, height=6, progress_color=p.accent)
        self._progress.grid(row=2, column=0, padx=24, pady=(2, 6), sticky="ew")
        self._progress.set(0)
        self._progress.grid_remove()

    # ----- refresh ------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_btn.configure(state="disabled", text="…")
        self._status.configure(text="Собираю диагностику…", text_color=self.p.text_muted)
        self._progress.set(0)
        self._progress.grid()
        client = self._client

        def on_progress(frac: float, label: str) -> None:
            post_to(self, lambda: self._set_progress(frac, label))

        run_async(self, lambda: _gather(client, on_progress), self._render, self._on_error)

    def _set_progress(self, frac: float, label: str) -> None:
        self._progress.set(frac)
        self._status.configure(text=f"Собираю диагностику… {label}", text_color=self.p.text_muted)

    def _on_error(self, exc: BaseException) -> None:
        self._progress.grid_remove()
        self._refresh_btn.configure(state="normal", text=f"{kit.REFRESH_GLYPH} Обновить страницу")
        self._status.configure(text=f"Ошибка: {exc}", text_color=self.p.fail)

    # ----- rendering ----------------------------------------------------

    def _render(self, d: dict[str, Any]) -> None:
        p = self.p
        self._progress.grid_remove()
        self._refresh_btn.configure(state="normal", text=f"{kit.REFRESH_GLYPH} Обновить страницу")
        self._status.configure(text="", text_color=p.text_muted)
        for w in self._body.winfo_children():
            w.destroy()
        self._report_text = d.get("report", "")

        row = 0
        row = self._render_status_chips(d, row)
        row = self._render_active_node(d, row)
        row = self._render_ip(d, row)
        row = self._render_dns(d, row)
        row = self._render_connectivity(d, row)
        row = self._render_report(d, row)

        if self._on_back is not None:
            ctk.CTkButton(
                self._body, text="← Назад", font=fonts.body(), fg_color="transparent",
                hover_color=p.surface_hover, width=90, command=self._on_back,
            ).grid(row=row, column=0, pady=(12, 8), sticky="w")

    def _card(self, title: str, row: int) -> ctk.CTkFrame:
        card = ctk.CTkFrame(self._body, fg_color=self.p.surface, corner_radius=12)
        card.grid(row=row, column=0, pady=(0, 12), sticky="ew")
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text=title, font=fonts.heading(), text_color=self.p.text).grid(
            row=0, column=0, padx=16, pady=(12, 6), sticky="w"
        )
        return card

    def _dot_color(self, ok: Optional[bool]) -> str:
        """State → dot color. Green=pass, red=fail, yellow=unknown/unavailable."""
        if ok is None:
            return self.p.warn
        return self.p.ok if ok else self.p.fail

    def _dot_row(self, parent: ctk.CTkBaseClass, ok: Optional[bool], text: str,
                 *, color: Optional[str] = None) -> ctk.CTkFrame:
        """A colored ● dot + neutral text — the dot's COLOR carries pass/fail.
        Pass an explicit ``color`` to override the ok→colour mapping (e.g. gray for
        a "not measured yet" state)."""
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkLabel(frame, text="●", font=fonts.body(),
                     text_color=color or self._dot_color(ok)).pack(side="left")
        ctk.CTkLabel(frame, text="  " + text, font=fonts.body(), text_color=self.p.text,
                     anchor="w").pack(side="left")
        return frame

    def _render_status_chips(self, d: dict[str, Any], row: int) -> int:
        core = d.get("core", {})
        config = d.get("config", {})
        node = d.get("active_node", {})
        nft = d.get("nft", {})

        checks: list[tuple[str, Optional[bool], str]] = [
            ("Ядро", bool(core.get("running")), self._clean_version(core.get("version", ""))),
            ("Конфиг", bool(config.get("valid")),
             f"outbounds: {config.get('stats', {}).get('outbounds', '?')}"),
            ("Clash API", "error" not in node and bool(node.get("node")), ""),
            ("nftables", bool(nft.get("nft_present")), ""),
        ]
        if core.get("byedpi_installed"):
            checks.append(("ByeDPI", bool(core.get("byedpi_running")), ""))
        # DNS now has its own card with per-test results (see _render_dns).

        card = self._card("Состояние", row)
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        for i, (label, ok, hint) in enumerate(checks):
            r, c = divmod(i, 2)
            text = label + (f"  ·  {hint}" if hint else "")
            self._dot_row(grid, ok, text).grid(row=r, column=c, padx=8, pady=3, sticky="w")
        return row + 1

    @staticmethod
    def _clean_version(v: str) -> str:
        """Extract a readable version from a noisy core version string.

        sing-box-extended reports a long line with build tags + revision
        (``…Tags: with_gvisor,with_quic,…Revision…``) that overflows the chip.
        Pull just the version number; fall back to the first short token.
        """
        import re

        if not v:
            return ""
        m = re.search(r"\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?", v)
        if m:
            return m.group(0)
        return v.split()[0][:24] if v.split() else ""

    @staticmethod
    def _resolve_node_name(raw: Optional[str], nodes: list) -> str:
        """Map a Clash outbound tag (``cfg-<section>-out``) to the node's human label
        from the node list; fall back to the raw tag for specials / unknown sections."""
        if not raw:
            return "—"
        m = re.match(r"^cfg-(.+)-out$", raw)
        if m:
            section = m.group(1)
            for n in nodes:
                if n.section == section:
                    return n.label or n.section
        return raw

    def _render_active_node(self, d: dict[str, Any], row: int) -> int:
        node = d.get("active_node", {})
        card = self._card("Активный сервер", row)
        if "error" in node or not node.get("node"):
            ctk.CTkLabel(card, text=node.get("error", "нет активного сервера"), font=fonts.body(),
                         text_color=self.p.text_muted, anchor="w").grid(
                row=1, column=0, padx=16, pady=(0, 12), sticky="w")
            return row + 1
        delay = node.get("delay")
        # Green only for a real, FAST-enough latency. High latency (≥ _SLOW_MS) =
        # barely-working or dead node → orange warning (65535 ms is the URLTest
        # timeout sentinel, just a special case). No delay at all = not probed yet
        # → yellow "нет отклика" (could be a fresh start, so no removal advice).
        slow = delay and delay >= _SLOW_MS and delay < _NODE_TIMEOUT_MS
        color: Optional[str] = None
        if delay == _NODE_TIMEOUT_MS:
            # CONFIRMED timeout: the core positively reported 65535 ms → red.
            delay_s, color = f"{delay} ms (таймаут)", self.p.fail
        elif not delay:
            # No data, or 0 ms (a non-confirmation some cores return on failure) —
            # UNCONFIRMED, so gray, never red. We don't claim a timeout we didn't get.
            delay_s, color = "нет данных", self.p.text_muted
        elif slow:
            delay_s, color = f"{delay} ms", self.p.warn            # high latency → orange
        else:
            delay_s, color = f"{delay} ms", self.p.ok              # responding → green
        grp = (f"   ·   группа: {node.get('group')} ({node.get('group_type')})"
               if node.get("group") else "")
        name = self._resolve_node_name(node.get("node"), d.get("nodes", []))
        text = f"{name}   ·   {node.get('type') or '—'}   ·   {delay_s}{grp}"
        self._dot_row(card, None, text, color=color).grid(
            row=1, column=0, padx=16, pady=(0, 4 if slow else 12), sticky="w")
        if slow:
            ctk.CTkLabel(card, text="⚠ Высокая задержка — сервер медленный или нерабочий (возможны "
                         "проблемы с DNS). Если повторяется — уберите этот сервер из списка.",
                         font=fonts.small(), text_color=self.p.warn, anchor="w",
                         wraplength=560, justify="left").grid(
                row=2, column=0, padx=16, pady=(0, 12), sticky="w")
        return row + 1

    def _render_ip(self, d: dict[str, Any], row: int) -> int:
        ip = d.get("ip", {})
        card = self._card("IP", row)
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        inner.grid_columnconfigure((0, 1), weight=1, uniform="ip")

        def fmt(entry: Optional[dict]) -> str:
            if not entry or not entry.get("ip"):
                return "—"
            cc = f" {entry.get('country')}" if entry.get("country") else ""
            return f"{entry.get('ip')}{cc}"

        if "error" in ip:
            ctk.CTkLabel(inner, text=ip["error"], font=fonts.body(), text_color=self.p.text_muted,
                         anchor="w", wraplength=560).grid(row=0, column=0, columnspan=2, sticky="w")
        else:
            self._kv(inner, 0, 0, "IP провайдера", fmt(ip.get("direct")))
            self._kv(inner, 0, 1, "Через прокси", fmt(ip.get("proxy")))
        return row + 1

    def _render_dns(self, d: dict[str, Any], row: int) -> int:
        """DNS routing test results (RU mode only): the russia-dns and secure-dns
        probes with their server + pass/fail, instead of one combined chip."""
        dns = d.get("dns", {})
        if dns.get("skip"):
            return row  # only meaningful in the Russia (proxy_banned_ru) mode
        card = self._card("DNS", row)
        if "error" in dns:
            ctk.CTkLabel(card, text=dns["error"], font=fonts.body(), text_color=self.p.text_muted,
                         anchor="w", wraplength=560, justify="left").grid(
                row=1, column=0, padx=16, pady=(0, 12), sticky="w")
            return row + 1
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.grid(row=1, column=0, padx=16, pady=(0, 12), sticky="ew")
        inner.grid_columnconfigure(0, weight=1)
        self._dns_row(inner, 0, "Россия — mail.ru", dns.get("russia_ok"), dns.get("russia_server"))
        self._dns_row(inner, 1, "Защищённый — andrevi.ch", dns.get("secure_ok"),
                      dns.get("secure_server"))
        return row + 1

    def _dns_row(self, parent: ctk.CTkBaseClass, r: int, label: str,
                 ok: Optional[bool], server: Optional[str]) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=r, column=0, sticky="w", pady=2)
        ctk.CTkLabel(box, text="●", font=fonts.body(), text_color=self._dot_color(ok)).pack(side="left")
        text = "  " + label + (f"   ·   {server}" if server else "")
        ctk.CTkLabel(box, text=text, font=fonts.body(), text_color=self.p.text, anchor="w").pack(side="left")

    def _kv(self, parent: ctk.CTkBaseClass, r: int, c: int, key: str, value: str) -> None:
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.grid(row=r, column=c, padx=4, sticky="ew")
        ctk.CTkLabel(box, text=key, font=fonts.small(), text_color=self.p.text_muted, anchor="w").pack(anchor="w")
        ctk.CTkLabel(box, text=value, font=fonts.body(), text_color=self.p.text, anchor="w").pack(anchor="w")

    def _render_connectivity(self, d: dict[str, Any], row: int) -> int:
        conn = d.get("conn", {})
        card = self._card("Проверка связи", row)
        grid = ctk.CTkFrame(card, fg_color="transparent")
        grid.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")
        for i, (key, label) in enumerate(_SITES):
            self._dot_row(grid, conn.get(key), label).grid(row=0, column=i, padx=8, sticky="w")
        return row + 1

    def _render_report(self, d: dict[str, Any], row: int) -> int:
        card = self._card("Полный отчёт (без паролей и ключей)", row)
        ctk.CTkLabel(card, text="Можно безопасно скопировать или сохранить и отправить на "
                     "проверку — пароли и ключи из отчёта автоматически удалены.",
                     font=fonts.small(), text_color=self.p.text_muted, wraplength=560,
                     justify="left", anchor="w").grid(row=1, column=0, padx=16, pady=(0, 6), sticky="w")
        box = ctk.CTkTextbox(card, font=ctk.CTkFont(family="Consolas", size=12),
                             fg_color=self.p.bg, text_color=self.p.text_muted, height=220, wrap="none")
        box.grid(row=2, column=0, padx=16, pady=(0, 8), sticky="ew")
        box.insert("1.0", self._report_text or "(пусто)")
        box.configure(state="disabled")
        btns = ctk.CTkFrame(card, fg_color="transparent")
        btns.grid(row=3, column=0, padx=16, pady=(0, 12), sticky="w")
        ctk.CTkButton(btns, text="📋 Копировать", font=fonts.small(), width=120,
                      fg_color="transparent", hover_color=self.p.surface_hover,
                      command=self._copy_report).grid(row=0, column=0)
        ctk.CTkButton(btns, text="💾 Сохранить", font=fonts.small(), width=120,
                      fg_color="transparent", hover_color=self.p.surface_hover,
                      command=self._save_report).grid(row=0, column=1, padx=(8, 0))
        return row + 1

    # ----- actions ------------------------------------------------------

    def _copy_report(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._report_text)
        self._status.configure(text="Отчёт скопирован.", text_color=self.p.text_muted)

    def _save_report(self) -> None:
        if not self._report_text:
            self._status.configure(text="Нет отчёта для сохранения.", text_color=self.p.warn)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Текстовый файл", "*.txt"), ("Все файлы", "*.*")],
            initialfile="re-homeproxy-diagnostics.txt",
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._report_text)
            self._status.configure(text=f"Сохранено: {path}", text_color=self.p.ok)
        except OSError as exc:
            self._status.configure(text=f"Не удалось сохранить: {exc}", text_color=self.p.fail)
