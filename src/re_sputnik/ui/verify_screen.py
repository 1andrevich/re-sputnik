# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Quick Setup phase 5 — Verify.

Runs the connectivity probes + active-node check and gives a plain verdict:
does it work or not. Reuses the same RPCs as Diagnostics but in a focused,
end-of-wizard form with a clear green/red answer and a Done button.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

import customtkinter as ctk

from ..engine import nodes as nodes_engine
from ..router import RouterClient
from . import kit
from .theme import Palette, fonts
from .worker import run_async
from ..i18n import _, N_

OnDone = Callable[[], None]

_SITES = [
    ("youtube", "YouTube"),
    ("google", "Google"),
    ("yandex", N_("Яндекс")),
    ("speedtest", "Speedtest"),
    ("baidu", "Baidu"),
]


def _probe(client: RouterClient) -> dict[str, Any]:
    def safe(method: str, params: Optional[dict] = None) -> dict:
        try:
            return client.ubus_homeproxy(method, params, timeout=15)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)}

    conn: dict[str, Optional[bool]] = {}
    for key, _label in _SITES:
        r = safe("connection_check", {"site": key})
        conn[key] = bool(r.get("result")) if "result" in r else None
    # config/core checks let us name WHY there's no connection (invalid config /
    # service down / no live node), instead of just showing red.
    try:
        nodes = nodes_engine.list_nodes(client)
    except Exception:  # noqa: BLE001 — names just won't resolve, not fatal
        nodes = []
    return {"conn": conn, "node": safe("clash_active_node"), "nodes": nodes,
            "config": safe("diag_config_check"), "core": safe("diag_core_check")}


def _resolve_node_name(raw: Optional[str], nodes: list) -> str:
    """Map a Clash outbound tag (``cfg-<section>-out``) to the node's label."""
    if not raw:
        return "—"
    m = re.match(r"^cfg-(.+)-out$", raw)
    if m:
        for n in nodes:
            if n.section == m.group(1):
                return n.label or n.section
    return raw


class VerifyScreen(ctk.CTkFrame):
    def __init__(self, master: ctk.CTkBaseClass, palette: Palette, client: RouterClient,
                 *, on_done: OnDone, on_back: Optional[OnDone] = None) -> None:
        super().__init__(master, fg_color="transparent")
        self.p = palette
        self._client = client
        self._on_done = on_done
        self._on_back = on_back

        self._sc = kit.WizardScaffold(self, palette, step=7, label=_("Проверка"), footer=False)
        self._scroll = self._sc.content
        body = self._scroll

        ctk.CTkLabel(body, text=_("Проверка"), font=fonts.title(), text_color=palette.text).grid(
            row=0, column=0, pady=(28, 4), padx=32, sticky="w")
        self._verdict = ctk.CTkLabel(body, text=_("Проверяю подключение…"), font=fonts.heading(),
                                     text_color=palette.text_muted)
        self._verdict.grid(row=1, column=0, padx=32, pady=(0, 12), sticky="w")

        self._node = ctk.CTkLabel(body, text="", font=fonts.body(), text_color=palette.text_muted,
                                  anchor="w", wraplength=560, justify="left")
        self._node.grid(row=2, column=0, padx=32, sticky="w")

        # Root-cause line, shown only when something is wrong.
        self._diag = ctk.CTkLabel(body, text="", font=fonts.small(), text_color=palette.warn,
                                  anchor="w", wraplength=560, justify="left")
        self._diag.grid(row=3, column=0, padx=32, pady=(0, 4), sticky="w")
        self._diag.grid_remove()

        self._sites = ctk.CTkFrame(body, fg_color=palette.surface, corner_radius=12)
        self._sites.grid(row=4, column=0, padx=32, pady=(10, 12), sticky="ew")
        self._sites.grid_columnconfigure(0, weight=1)

        self._retry = ctk.CTkButton(body, text=f"{kit.REFRESH_GLYPH} " + _("Проверить снова"), font=fonts.body(),
                                    fg_color=palette.surface, hover_color=palette.surface_hover,
                                    command=self.refresh)
        self._retry.grid(row=5, column=0, padx=32, pady=(0, 6), sticky="w")
        ctk.CTkButton(body, text=_("Далее"), font=fonts.heading(), height=42, fg_color=palette.ok, text_color=palette.accent_fg,
                      hover_color=palette.accent_hover, command=on_done).grid(
            row=6, column=0, padx=32, pady=(6, 6), sticky="ew")
        if on_back is not None:
            ctk.CTkButton(body, text=_("← Назад"), font=fonts.body(), fg_color="transparent",
                          hover_color=palette.surface_hover, width=90, command=on_back).grid(
                row=7, column=0, padx=32, pady=(0, 14), sticky="w")
        self.refresh()

    def refresh(self) -> None:
        self._retry.configure(state="disabled")
        self._verdict.configure(text=_("Проверяю подключение…"), text_color=self.p.text_muted)
        for w in self._sites.winfo_children():
            w.destroy()
        client = self._client
        run_async(self, lambda: _probe(client), self._render, self._err)

    def _err(self, e: BaseException) -> None:
        self._retry.configure(state="normal")
        self._verdict.configure(text=_("Ошибка проверки: {e}").format(e=e), text_color=self.p.fail)

    def _render(self, d: dict[str, Any]) -> None:
        p = self.p
        self._retry.configure(state="normal")
        conn = d["conn"]
        node = d["node"]

        ok_count = sum(1 for v in conn.values() if v)
        total = len(conn)
        if ok_count == total:
            self._verdict.configure(text=_("✓ Всё работает"), text_color=p.ok)
        elif ok_count == 0:
            self._verdict.configure(text=_("✗ Нет связи через прокси"), text_color=p.fail)
        else:
            self._verdict.configure(
                text=_("⚠ Частично: {ok} из {total} сайтов").format(ok=ok_count, total=total),
                text_color=p.warn)

        has_node = not ("error" in node or not node.get("node"))
        if not has_node:
            self._node.configure(text=_("Активный сервер: —  (сервер не выбран или сервис не запущен)"))
        else:
            delay = node.get("delay")
            ds = f"{delay} ms" if delay is not None else "—"
            name = _resolve_node_name(node.get("node"), d.get("nodes", []))
            self._node.configure(text=_("Активный сервер: {name} · {type} · {delay}").format(
                name=name, type=node.get('type') or '—', delay=ds))

        self._show_diagnosis(d, ok_count, has_node)

        for i, (key, label) in enumerate(_SITES):
            v = conn.get(key)
            dot, color = ("●", p.ok) if v else (("○", p.fail) if v is not None else ("○", p.text_muted))
            ctk.CTkLabel(self._sites, text=f"{dot}  {_(label)}", font=fonts.body(), text_color=color,
                         anchor="w").grid(row=i, column=0, padx=16, pady=4, sticky="w")

    def _show_diagnosis(self, d: dict[str, Any], ok_count: int, has_node: bool) -> None:
        """When nothing (or little) works, name the most likely cause so the user
        isn't left staring at red dots. Order: config invalid → service/node down
        → node reachable but traffic blocked."""
        if ok_count > 0:
            self._diag.grid_remove()
            return
        config = d.get("config") or {}
        core = d.get("core") or {}
        if "error" not in config and config.get("valid") is False:
            out = (config.get("check_output") or "").strip()
            tail = (": " + out[-300:]) if out else "."
            msg = _("Причина: конфигурация ядра невалидна") + tail
        elif not core.get("hiddify_installed") and not core.get("singbox_installed"):
            msg = _("Причина: ядро не установлено — вернитесь на шаг «Установка ПО».")
        elif not has_node:
            msg = (_("Причина: сервис не выбрал сервер. Возможно, он не запущен или серверы "
                   "недоступны. Нажмите «Проверить снова» через 10–20 секунд."))
        else:
            msg = (_("Сервер выбран, но трафик не проходит — серверы могут быть мертвы или "
                   "заблокированы. Попробуйте другие серверы или ByeDPI."))
        self._diag.configure(text=msg)
        self._diag.grid()
