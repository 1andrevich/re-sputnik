# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Why won't the core start? — turn a sing-box/hiddify config FATAL into a
human-readable cause the user can act on.

The core (sing-box) refuses to start the WHOLE service if even one outbound is
invalid, and the only signal the user otherwise gets is "service stopped". This
module reads the config-check output, finds the offending ``outbound[N]``, maps
that index back to the node's human name (so the user can remove THAT server from
the pool), and produces ready-to-show guidance. Pure read-only diagnosis.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from ..router import RouterClient
from . import nodes as nodes_engine
from ..i18n import _, N_

# sing-box logs colour codes (\x1b[31mFATAL…); strip them so displayed text is clean.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
# sing-box: "create service: initialize outbound[3]: uTLS is required by reality client"
_OUTBOUND_RE = re.compile(r"outbound\[(\d+)\]\s*:\s*(.+)", re.IGNORECASE)
# generated tags look like cfg-<section>-out  or  cfg-<section>-shadowtls-out
_TAG_SECTION_RE = re.compile(r"^cfg-(.+?)-(?:shadowtls-)?out$")

_CONFIG_PATH = "/var/run/homeproxy/hiddify-c.json"

# A few common sing-box errors phrased for a non-technical user. Unknown ones fall
# back to the raw reason (still shown verbatim so nothing is hidden).
_FRIENDLY = (
    ("utls is required by reality", N_("сервер использует Reality, но в ссылке нет uTLS-отпечатка")),
    ("missing tls", N_("у сервера не настроен TLS")),
    ("unknown method", N_("неподдерживаемый метод шифрования")),
    ("unknown cipher", N_("неподдерживаемый шифр")),
    ("invalid uuid", N_("неверный UUID в ссылке")),
    ("parse", N_("не удалось разобрать параметры сервера")),
)


@dataclass(slots=True)
class CoreFailure:
    """A config-level reason the core won't start."""

    raw: str                       # full check_output (verbatim, never hidden)
    reason: str                    # the part after outbound[N]: (or raw if no match)
    node_name: Optional[str]       # human-readable culprit server name, if identified
    node_section: Optional[str]    # uci section of the culprit (for "remove from pool")
    outbound_index: Optional[int]  # the N in outbound[N]

    @property
    def friendly_reason(self) -> str:
        low = self.reason.lower()
        for needle, phrase in _FRIENDLY:
            if needle in low:
                return _(phrase)
        return self.reason


def diagnose_core_failure(client: RouterClient, core: Optional[dict] = None,
                          config: Optional[dict] = None) -> Optional[CoreFailure]:
    """Return a CoreFailure if the core is installed but won't start because the
    config is invalid; else None (running fine / no core / stopped for another
    reason). Pass already-fetched ``diag_core_check`` / ``diag_config_check`` dicts
    to skip duplicate RPCs. Safe to call on every refresh — tolerant of hiccups."""
    if core is None:
        try:
            core = client.ubus_homeproxy("diag_core_check", timeout=15)
        except Exception:
            return None
    if not isinstance(core, dict) or core.get("running"):
        return None
    if not (core.get("singbox_installed") or core.get("hiddify_installed")):
        return None  # no core at all — that's "Ядро не установлено", a different message
    cfg = config
    if cfg is None:
        try:
            cfg = client.ubus_homeproxy("diag_config_check", timeout=25)
        except Exception:
            return None
    if not isinstance(cfg, dict) or cfg.get("valid"):
        return None  # config is valid — core stopped for some other reason
    raw = (cfg.get("check_output") or "").strip()
    return _analyze(client, raw)


def _analyze(client: RouterClient, raw: str) -> CoreFailure:
    raw = _ANSI_RE.sub("", raw).strip()
    reason = raw
    idx: Optional[int] = None
    m = _OUTBOUND_RE.search(raw)
    if m:
        idx = int(m.group(1))
        reason = m.group(2).strip()

    node_name = node_section = None
    if idx is not None:
        tag = _outbound_tag(client, idx)
        if tag:
            sm = _TAG_SECTION_RE.match(tag)
            if sm:
                node_section = sm.group(1)
                node_name = _label_for(client, node_section) or tag
            else:
                node_name = tag  # a non-node outbound (direct/block/urltest) — show the tag
    return CoreFailure(raw=raw, reason=reason, node_name=node_name,
                       node_section=node_section, outbound_index=idx)


def _outbound_tag(client: RouterClient, idx: int) -> Optional[str]:
    """The `tag` of outbound[idx] in the generated config (root-readable)."""
    try:
        out = client.run(f"cat {_CONFIG_PATH} 2>/dev/null", timeout=20)
        obs = json.loads(out.stdout).get("outbounds", [])
        return obs[idx].get("tag") if 0 <= idx < len(obs) else None
    except Exception:
        return None


def _label_for(client: RouterClient, section: str) -> Optional[str]:
    try:
        for n in nodes_engine.list_nodes(client):
            if n.section == section:
                return n.label or section
    except Exception:
        pass
    return None


def failure_message(f: CoreFailure) -> tuple[str, list[str]]:
    """(headline, steps) — consistent Russian wording for any of the 3 screens."""
    if f.node_name:
        head = _("Ядро не запускается из-за сервера «{0}»: {1}. "
                 "Это не поломка ядра — оно не может загрузить конфигурацию из-за одного сервера.").format(
            f.node_name, f.friendly_reason)
        steps = [
            _("Уберите сервер «{0}» из пула URLTest (или выберите другой основной сервер).").format(f.node_name),
            _("Перезапустите сервис — ядро запустится с остальными серверами."),
        ]
    elif f.reason:
        head = _("Ядро не запускается из-за ошибки в конфигурации: {0}. "
                 "Это не поломка ядра.").format(f.friendly_reason)
        steps = [
            _("Уберите недавно добавленный / проблемный сервер из пула или выберите другой основной."),
            _("Перезапустите сервис."),
        ]
    else:
        head = _("Ядро не запускается из-за ошибки в конфигурации (это не поломка ядра).")
        steps = [_("Проверьте список серверов и выберите другой основной сервер, затем перезапустите.")]
    return head, steps
