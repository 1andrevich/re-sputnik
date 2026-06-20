# SPDX-License-Identifier: GPL-2.0-only
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

RULE_TYPE = "proxy_ru_rule"

# Source lists/services offered, mirroring client.js (value -> label).
SERVICE_SOURCES: list[tuple[str, str]] = [
    ("refilter", "Re-filter — блок-лист РФ (60000+ доменов + 25000+ IP)"),
    ("russia-inside", "Russia Inside — must-have РФ (1000+ доменов)"),
    ("youtube", "YouTube"),
    ("telegram", "Telegram"),
    ("discord", "Discord"),
    ("twitter", "Twitter / X"),
    ("tiktok", "TikTok"),
    ("meta", "Meta (Facebook, Instagram)"),
    ("roblox", "Roblox"),
    ("anime", "Аниме-стриминг"),
    ("hdrezka", "HDRezka"),
    ("news", "Мировые новости"),
    ("porn", "Контент 18+"),
    ("google_ai", "Google AI"),
    ("google_play", "Google Play"),
    ("geoblock", "GeoBlock-сервисы"),
    ("cloudflare", "Cloudflare CDN"),
    ("cloudfront", "CloudFront CDN"),
    ("ovh", "OVH (Франция)"),
    ("hetzner", "Hetzner (Германия)"),
    ("digitalocean", "DigitalOcean"),
    ("hodca", "HODCA"),
]
_SOURCE_LABELS = dict(SERVICE_SOURCES)

# Special node targets (besides actual proxy nodes).
NODE_SPECIAL: list[tuple[str, str]] = [
    ("main-out", "Основной пул серверов"),
    ("urltest", "Отдельный URLTest (авто)"),
    ("byedpi-out", "ByeDPI"),
]
_SPECIAL_LABELS = dict(NODE_SPECIAL)


@dataclass(slots=True)
class RuRule:
    section: str
    source: str
    node: str


def source_label(value: str) -> str:
    return _SOURCE_LABELS.get(value, value)


def node_label(value: str, nodes: list[nd.Node]) -> str:
    if value in _SPECIAL_LABELS:
        return _SPECIAL_LABELS[value]
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


def ensure_ru_defaults(client: RouterClient) -> None:
    """Quick-setup seeding so the guided flow yields a WORKING selective config.

    Idempotent and non-destructive: if no routing mode is set yet, switch to RU
    selective ('proxy_banned_ru', default route Direct); and if there are no rules
    yet, route the Re-filter RU blocklist through the main pool. Never clobbers an
    existing mode choice or existing rules.
    """
    mode = client.uci_get("homeproxy.config.routing_mode") or ""
    if not mode:
        client.uci_set("homeproxy.config.routing_mode", "proxy_banned_ru")
        # Recommended defaults on a fresh setup:
        #  - messenger calls THROUGH the proxy (WhatsApp/Telegram voice is often
        #    throttled/blocked in RU, so proxying it by default is the safe choice);
        #  - torrents BYPASS the proxy (they saturate the link and get banned on
        #    exit nodes). Both are user-overridable on this screen.
        #  - IPv6 OFF: the RU lists carry no v6 CIDRs, so v6 would leak past the
        #    proxy/rules — keep the data plane v4-only by default.
        client.uci_set("homeproxy.config.proxy_calls", "1")
        client.uci_set("homeproxy.config.no_proxy_torrents", "1")
        client.uci_set("homeproxy.config.ipv6_support", "0")
        client.uci_commit("homeproxy")
        mode = "proxy_banned_ru"
    if mode == "proxy_banned_ru" and not list_rules(client):
        # One preset list: Re-filter (РКН registry) through the main server pool.
        add_rule(client, "refilter", "main-out")
