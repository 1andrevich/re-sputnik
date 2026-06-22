# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Zapret (zapret2 / nfqws2) — status, install, strategy config, and testing.

Packet-level DPI bypass that complements ByeDPI: it can also carry QUIC video
and Discord calls. Mirrors the homeproxy LuCI Zapret tab — the strategy
candidates come from the same shipped /etc/homeproxy/zapret_candidates.json, so
the desktop app and LuCI offer an identical list. The per-strategy test reuses
the same isolated probe (zapret_strategy_test) the LuCI "full test" loop drives.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

from ..router import RouterClient
from ..i18n import _

ENABLED_KEY = "homeproxy.config.zapret_enabled"
CMD_KEY = "homeproxy.config.zapret_cmd_opts"
VOICE_KEY = "homeproxy.config.zapret_voice"

CANDIDATES_PATH = "/etc/homeproxy/zapret_candidates.json"


# ----- status / config --------------------------------------------------


def get_status(client: RouterClient) -> dict:
    """{installed, version, running, pkg_manager, arch} or {error}."""
    return client.ubus_homeproxy("zapret_status")


def get_config(client: RouterClient) -> dict:
    return {
        "enabled": client.uci_get(ENABLED_KEY) == "1",
        "cmd_opts": client.uci_get(CMD_KEY) or "",
        "voice": client.uci_get(VOICE_KEY) == "1",
    }


def set_enabled(client: RouterClient, on: bool) -> None:
    client.uci_set(ENABLED_KEY, "1" if on else "0")
    client.uci_commit("homeproxy")


def set_cmd_opts(client: RouterClient, opts: str) -> None:
    client.uci_set(CMD_KEY, opts.strip())
    client.uci_commit("homeproxy")


def set_voice(client: RouterClient, on: bool) -> None:
    client.uci_set(VOICE_KEY, "1" if on else "0")
    client.uci_commit("homeproxy")


def restart_service(client: RouterClient) -> bool:
    """Restart the homeproxy service so a Zapret change takes effect."""
    res = client.ubus_homeproxy("diag_service_restart", timeout=40)
    return bool(res.get("result"))


# ----- strategy candidates (shared file, single source of truth) --------


def load_candidates(client: RouterClient) -> list[dict[str, str]]:
    """Read the shipped candidate list: [{name, args, group}, ...].

    'args' is the stable key (used for match/apply); 'name' is display-only;
    'group' is 'recommended' or 'auto'. Returns [] if the file is unavailable.
    """
    res = client.run(f"cat {CANDIDATES_PATH} 2>/dev/null", timeout=20)
    if not res.ok or not res.stdout.strip():
        return []
    try:
        data = json.loads(res.stdout)
        cands = data.get("candidates")
        return cands if isinstance(cands, list) else []
    except (ValueError, AttributeError):
        return []


# ----- per-strategy test (the full-test loop calls this per candidate) --


def run_test(client: RouterClient, cmd_opts: str) -> dict:
    """Probe ONE strategy on a temporary NFQUEUE scoped to 4 test sites.

    zapret_strategy_test wraps the result as {output: "<json>"}; we unwrap it to
    {results:[{label,host,ok,reason,tls}], passed, total} or {error}.
    """
    res = client.ubus_homeproxy("zapret_strategy_test", {"cmd_opts": cmd_opts}, timeout=120)
    if res.get("error"):
        return {"error": res["error"]}
    try:
        data = json.loads(res.get("output") or "{}")
    except ValueError:
        return {"error": _("Не удалось разобрать результат теста.")}
    if data.get("error"):
        return {"error": data["error"]}
    return {
        "results": data.get("results", []),
        "passed": data.get("ok", 0),
        "total": data.get("total", 0),
    }


# ----- install (prepare -> download -> install) -------------------------


def install(client: RouterClient, progress: Optional[Callable[[str], None]] = None) -> tuple[bool, str]:
    """Install zapret2 on the router: prepare_install -> wget -> install_pkg.

    Mirrors the LuCI install-on-enable flow. Returns (ok, message)."""
    def say(m: str) -> None:
        if progress:
            progress(m)

    say(_("Проверяю требования…"))
    prep: dict[str, Any] = client.ubus_homeproxy("zapret_prepare_install", timeout=60)
    if prep.get("error") or not prep.get("dl_url"):
        return False, prep.get("error") or _("Не удалось подготовить установку (нет ссылки).")

    say(_("Скачиваю пакет…"))
    if not client.run(f"wget -qO {prep['tmp_path']} '{prep['dl_url']}'", timeout=300).ok:
        return False, _("Не удалось скачать пакет Zapret.")

    say(_("Устанавливаю…"))
    inst = client.ubus_homeproxy(
        "zapret_install_pkg",
        {"tmp_path": prep["tmp_path"], "pkg_manager": prep["pkg_manager"]}, timeout=180)
    if not inst.get("result"):
        return False, inst.get("error") or _("Установка Zapret не удалась.")
    return True, _("Zapret установлен.")


def remove(client: RouterClient) -> bool:
    res = client.ubus_homeproxy("zapret_remove", timeout=60)
    return bool(res.get("result"))
