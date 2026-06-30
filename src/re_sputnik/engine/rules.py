# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""RU proxy rules — bind a service/list to the node that should carry it.

In ``proxy_banned_ru`` routing mode the default route is Direct; each added
``proxy_ru_rule`` section routes one source (a blocklist or a service like
YouTube/Telegram) through a chosen node — the main node, ByeDPI, a specific
node, or a separate URLTest pool. Mirrors HomeProxy's own ``proxy_ru_rule``
model (client.js), driven via uci.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..router import RouterClient
from . import nodes as nd
from ..i18n import _, N_

RULE_TYPE = "proxy_ru_rule"

# Source lists/services offered, mirroring client.js (value -> label).
SERVICE_SOURCES: list[tuple[str, str]] = [
    ("refilter",      N_("Re:filter — блок-лист РФ (60000+ доменов + 25000+ IP)")),
    ("russia-inside", N_("Russia Inside — must-have РФ (1000+ доменов)")),
    ("youtube",       "YouTube"),
    ("telegram",      "Telegram"),
    ("discord",       "Discord"),
    ("twitter",       "Twitter / X"),
    ("tiktok",        "TikTok"),
    ("meta",          "Meta (Facebook, Instagram)"),
    ("roblox",        "Roblox"),
    ("anime",         N_("Аниме-стриминг")),
    ("hdrezka",       "HDRezka"),
    ("news",          N_("Мировые новости")),
    ("porn",          N_("Контент 18+")),
    ("google_ai",     "Google AI"),
    ("google_play",   "Google Play"),
    ("geoblock",      N_("GeoBlock-сервисы")),
    ("cloudflare",    "Cloudflare CDN"),
    ("cloudfront",    "CloudFront CDN"),
    ("ovh",           N_("OVH (Франция)")),
    ("hetzner",       N_("Hetzner (Германия)")),
    ("digitalocean",  "DigitalOcean"),
    ("hodca",         "HODCA"),
]
_SOURCE_LABELS = dict(SERVICE_SOURCES)

# Special node targets (besides actual proxy nodes).
NODE_SPECIAL: list[tuple[str, str]] = [
    ("main-out",    N_("Основной пул серверов")),
    ("urltest",     N_("Отдельный пул (авто)")),
    ("byedpi-out",  "ByeDPI"),
    ("zapret-out",  "Zapret"),
]
_SPECIAL_LABELS = dict(NODE_SPECIAL)

# Selective routing modes the app understands. proxy_banned_ru = forward (RU:
# default Direct, lists -> proxy); bypass_cn / bypass_ir = reverse (default proxy,
# region geosite/geoip -> Direct, per-service overrides). Mirrors generate_client.uc
# REGION / client.js.
SELECTIVE_MODES = ("proxy_banned_ru", "bypass_cn", "bypass_ir")

# Domestic DNS resolver presets per selective mode for the app's «Дополнительно»
# picker: (uci_key, default_value, [(value, label)…]). Mirrors client.js; the
# backend also defaults these, so leaving a field unset is fine.
DNS_PRESETS: dict[str, tuple[str, str, list[tuple[str, str]]]] = {
    "proxy_banned_ru": ("russia_dns_server", "77.88.8.8", [
        ("77.88.8.8", "Yandex (77.88.8.8)"),
        ("193.58.251.251", "SkyDNS (193.58.251.251)"),
        ("83.220.169.155", "Comss.one (83.220.169.155)"),
        ("1.1.1.1", "Cloudflare (1.1.1.1)"),
        ("8.8.8.8", "Google (8.8.8.8)"),
    ]),
    "bypass_cn": ("china_dns_server", "223.5.5.5", [
        ("223.5.5.5", "AliDNS (223.5.5.5)"),
        ("210.2.4.8", "CNNIC (210.2.4.8)"),
        ("119.29.29.29", "Tencent (119.29.29.29)"),
        ("117.50.10.10", "ThreatBook (117.50.10.10)"),
    ]),
    "bypass_ir": ("iran_dns_server", "178.22.122.100", [
        ("178.22.122.100", "Shecan (178.22.122.100)"),
        ("185.51.200.2", "Shecan #2 (185.51.200.2)"),
        ("78.157.42.100", "Electro/Begzar (78.157.42.100)"),
        ("10.202.10.202", "403.online (10.202.10.202)"),
        ("10.202.10.10", "Radar (10.202.10.10)"),
    ]),
}

# Legacy China routing_mode values (pre-rework) -> the mode they map to now, so a
# router still set to one (e.g. from old LuCI) migrates cleanly to bypass_cn.
_LEGACY_MODE_MAP = {
    "gfwlist": "bypass_cn",
    "bypass_mainland_china": "bypass_cn",
    "proxy_mainland_china": "bypass_cn",
}

# Bulk RU blocklists — only meaningful in the RU forward mode. In the reverse
# modes the region geosite/geoip is baked into the engine baseline, so here those
# modes only offer per-service overrides.
_RU_ONLY_SOURCES = {"refilter", "russia-inside"}


def is_selective(mode: str) -> bool:
    return mode in SELECTIVE_MODES


def normalize_mode(mode: str) -> str:
    """Map legacy China modes to the current bypass_cn; pass everything else through."""
    return _LEGACY_MODE_MAP.get(mode, mode)


def sources_for_mode(mode: str) -> list[tuple[str, str]]:
    """Service sources offered for a mode: RU gets the bulk blocklists too; the
    reverse modes (cn/ir) only get the per-service overrides."""
    if mode == "proxy_banned_ru":
        return list(SERVICE_SOURCES)
    return [(v, lbl) for v, lbl in SERVICE_SOURCES if v not in _RU_ONLY_SOURCES]


def default_mode_for_lang() -> str:
    """Quick-setup default region from the app's UI language: zh -> China,
    fa -> Iran, everything else -> Russia. User can switch on the rules screen."""
    from ..i18n import current_language
    lang = (current_language() or "").lower()
    if lang.startswith("zh"):
        return "bypass_cn"
    if lang.startswith("fa"):
        return "bypass_ir"
    return "proxy_banned_ru"


@dataclass(slots=True)
class RuRule:
    section: str
    source: str
    node: str


def source_label(value: str) -> str:
    return _(_SOURCE_LABELS.get(value, value))


def node_label(value: str, nodes: list[nd.Node]) -> str:
    if value in _SPECIAL_LABELS:
        return _(_SPECIAL_LABELS[value])
    for n in nodes:
        if n.section == value:
            return f"{n.label or n.section} ({n.type})"
    return value


def list_rules(client: RouterClient) -> list[RuRule]:
    cmd = (
        "for s in $(uci show homeproxy | sed -n "
        rf"'s/^homeproxy\.\([^.]*\)={RULE_TYPE}$/\1/p'); do "
        r'printf "%s\t%s\t%s\n" "$s" '
        '"$(uci -q get homeproxy.$s.source)" "$(uci -q get homeproxy.$s.node)"; done'
    )
    res = client.run(cmd, timeout=20)
    rules: list[RuRule] = []
    if res.ok:
        for line in res.stdout.splitlines():
            parts = line.split("\t")
            if parts and parts[0]:
                rules.append(RuRule(section=parts[0],
                                    source=parts[1] if len(parts) > 1 else "",
                                    node=parts[2] if len(parts) > 2 else ""))
    return rules


def add_rule(client: RouterClient, source: str, node: str) -> None:
    """Add (or update) a rule routing ``source`` through ``node``.

    Source is unique per HomeProxy (only the first rule for a source applies), so
    an existing rule for the same source is updated rather than duplicated. When
    node='urltest', the pool is filled with core-compatible nodes (an empty pool
    is a dead outbound).
    """
    existing = next((r for r in list_rules(client) if r.source == source), None)
    sec = existing.section if existing else client.run(
        f"uci add homeproxy {RULE_TYPE}").stdout.strip()
    client.run(f"uci set homeproxy.{sec}.source='{source}'")
    client.run(f"uci set homeproxy.{sec}.node='{node}'")
    # MUST set enabled='1' — generate_client.uc only emits rule_sets for rules where
    # `enabled === '1'`; without it the rule (and its RU lists) is silently skipped.
    client.run(f"uci set homeproxy.{sec}.enabled='1'")
    if node == "urltest":
        client.run(f"uci -q delete homeproxy.{sec}.urltest_nodes")
        pool = nd.build_urltest_pool(nd.list_nodes(client), nd.active_core(client))
        for n in pool:
            client.uci_add_list(f"homeproxy.{sec}.urltest_nodes", n)
        client.run(f"uci set homeproxy.{sec}.urltest_interval='180'")
        client.run(f"uci set homeproxy.{sec}.urltest_tolerance='150'")
    client.uci_commit("homeproxy")


def remove_rule(client: RouterClient, section: str) -> None:
    client.run(f"uci delete homeproxy.{section}")
    client.uci_commit("homeproxy")


def ensure_mode_defaults(client: RouterClient, mode: str | None = None) -> None:
    """Quick-setup seeding so the guided flow yields a WORKING selective config.

    Idempotent and non-destructive:
     - migrate a legacy China mode (gfwlist/bypass_mainland_china/proxy_mainland_china)
       to the current ``bypass_cn`` so the reworked backend recognizes it;
     - if no routing mode is set yet, switch to ``mode`` (default: by app language
       — zh->China, fa->Iran, else Russia);
     - for the RU forward mode only, if there are no rules yet, route the Re:filter
       blocklist through the main pool (reverse modes get the region geosite/geoip
       from the engine baseline, so no seed rule is needed).
    Never clobbers an existing (non-legacy) mode choice or existing rules.
    """
    target = normalize_mode(mode or default_mode_for_lang())

    raw = client.uci_get("homeproxy.config.routing_mode") or ""
    if raw in _LEGACY_MODE_MAP:  # migrate stale China value in place
        client.uci_set("homeproxy.config.routing_mode", _LEGACY_MODE_MAP[raw])
        client.uci_commit("homeproxy")
        raw = _LEGACY_MODE_MAP[raw]

    if not raw:
        client.uci_set("homeproxy.config.routing_mode", target)
        # Recommended defaults on a fresh setup (all selective modes):
        #  - messenger calls THROUGH the proxy (WhatsApp/Telegram voice is often
        #    throttled/blocked, so proxying it by default is the safe choice);
        #  - torrents BYPASS the proxy (they saturate the link and get banned on
        #    exit nodes). Both are user-overridable on the rules screen.
        #  - IPv6 OFF: the region lists carry no v6 CIDRs, so v6 would leak past
        #    the proxy/rules — keep the data plane v4-only by default.
        client.uci_set("homeproxy.config.proxy_calls", "1")
        client.uci_set("homeproxy.config.no_proxy_torrents", "1")
        client.uci_set("homeproxy.config.ipv6_support", "0")
        client.uci_commit("homeproxy")
        raw = target

    if raw == "proxy_banned_ru" and not list_rules(client):
        # One preset list: Re:filter (РКН registry) through the main server pool.
        add_rule(client, "refilter", "main-out")


# Back-compat alias (legacy call sites): seed defaults for the RU forward mode.
def ensure_ru_defaults(client: RouterClient) -> None:
    ensure_mode_defaults(client, "proxy_banned_ru")
