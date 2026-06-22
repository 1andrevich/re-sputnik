# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Nodes & subscriptions operations — thin wrappers over the router's own scripts.

Uses the built-in mechanisms (never hand-rolls parsing): subscriptions via uci
list + update_subscriptions.uc; WireGuard/AmneziaWG .conf via import_conf.uc;
node listing via uci. Homeproxy-specific, so it lives here, not in RouterClient.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass

from ..router import RouterClient, RouterError

SUB_URL_KEY = "homeproxy.subscription.subscription_url"
UPDATE_SUBS_SCRIPT = "/etc/homeproxy/scripts/update_subscriptions.uc"
IMPORT_CONF_SCRIPT = "/usr/share/homeproxy/scripts/import_conf.uc"
# import_link.uc lives in /etc/homeproxy/scripts so it can import the node_parse module.
IMPORT_LINK_SCRIPT = "/etc/homeproxy/scripts/import_link.uc"
_IMPORT_TMP = "/tmp/re-companion-import.conf"
_LINKS_TMP = "/tmp/re-companion-links.txt"


@dataclass(slots=True)
class Node:
    section: str
    label: str
    type: str
    transport: str = ""   # vless/vmess/trojan stream transport (e.g. 'xhttp', 'ws')
    shadowtls: bool = False  # type='shadowsocks' wrapped in ShadowTLS (shadowtls_enabled)


# ----- subscriptions ----------------------------------------------------


def list_subscriptions(client: RouterClient) -> list[str]:
    return client.uci_get_list(SUB_URL_KEY)


def add_subscription(client: RouterClient, url: str) -> None:
    url = url.strip()
    if not url:
        raise RouterError("empty subscription URL")

    # DEFERRED (implement on user demand): encrypted Happ deep-links
    # `happ://crypt5/…` (also crypt..crypt4) wrap the real subscription URL behind
    # layered obfuscation + an RSA-unwrapped ChaCha20-Poly1305 key with keys
    # embedded in the Happ app. They CAN'T be decoded on the router (ucode has no
    # AEAD; 23.05 lacks ucode-mod-digest/zlib) — the App must decode them, then add
    # the resulting https:// URL here. Validated path (2026-06-19): bundle the
    # upstream `happ-decrypt-universal` CLI (Apache-2.0) and call it as a SEPARATE
    # process — arm's-length aggregation, so no license-combine issue — then
    # parse the URL from its "Result" stdout block. See memory: happ-crypt-link-decode.
    #
    # if url.startswith("happ://"):
    #     from . import happ_link
    #     url = happ_link.decode_happ(url)  # -> real https:// subscription URL

    if url in list_subscriptions(client):
        return  # idempotent
    client.uci_add_list(SUB_URL_KEY, url)
    client.uci_commit("homeproxy")


def remove_subscription(client: RouterClient, url: str) -> None:
    client.uci_del_list(SUB_URL_KEY, url)
    client.uci_commit("homeproxy")


AUTO_UPDATE_KEY = "homeproxy.subscription.auto_update"
AUTO_UPDATE_TIME_KEY = "homeproxy.subscription.auto_update_time"
_CRON_TAG = "homeproxy_autosetup"
_CROND_SCRIPT = "/etc/homeproxy/scripts/update_crond.sh"


def get_subscription_autoupdate(client: RouterClient) -> tuple[bool, int]:
    """(enabled, hour-of-day 0-23) of the daily subscription auto-update."""
    enabled = client.uci_get(AUTO_UPDATE_KEY) == "1"
    try:
        hour = int(client.uci_get(AUTO_UPDATE_TIME_KEY) or "2")
    except ValueError:
        hour = 2
    return enabled, max(0, min(23, hour))


def set_subscription_autoupdate(client: RouterClient, enabled: bool, hour: int) -> None:
    """Enable/disable a daily subscription auto-update at ``hour``:00 and apply the
    crontab line immediately — mirrors the device init.d (tag ``#homeproxy_autosetup``,
    ``update_crond.sh``), so no full proxy-service restart is needed."""
    hour = max(0, min(23, int(hour)))
    client.uci_set(AUTO_UPDATE_KEY, "1" if enabled else "0")
    client.uci_set(AUTO_UPDATE_TIME_KEY, str(hour))
    client.uci_commit("homeproxy")
    line = f"0 {hour} * * * {_CROND_SCRIPT} #{_CRON_TAG}"
    cmd = f'sed -i "/{_CRON_TAG}/d" /etc/crontabs/root 2>/dev/null; '
    if enabled:
        cmd += (f"mkdir -p /etc/crontabs; printf '%s\\n' {shlex.quote(line)} "
                ">> /etc/crontabs/root; ")
    cmd += "/etc/init.d/cron enable >/dev/null 2>&1; /etc/init.d/cron restart >/dev/null 2>&1"
    client.run(cmd)


def update_subscriptions(client: RouterClient) -> dict:
    """Fetch + import all configured subscriptions via the router's own script.

    The script logs its real progress (``N nodes added, M removed`` / ``[FATAL
    ERROR] …``) to RUN_DIR/homeproxy.log, NOT to stdout — stdout only carries
    incidental restart noise (a benign ``ubus … service delete (Not found)`` when
    the service wasn't running). So we read the summary back from that log.

    Returns {ok, added, removed, error}; added/removed are None if not reported.
    """
    client.run(f"ucode {UPDATE_SUBS_SCRIPT} 2>&1", timeout=120)
    tail = client.run("tail -n 40 /var/run/homeproxy/homeproxy.log 2>/dev/null").stdout
    added = removed = None
    error = ""
    for line in tail.splitlines():
        if "[SUBSCRIBE]" not in line:
            continue
        msg = line.split("[SUBSCRIBE]", 1)[1].strip()
        if "FATAL ERROR" in msg:
            error = msg
        m = re.search(r"(\d+) nodes added, (\d+) removed", msg)
        if m:
            # A successful summary later in the tail supersedes an earlier run's fatal.
            added, removed, error = int(m.group(1)), int(m.group(2)), ""
    return {"ok": not error, "added": added, "removed": removed, "error": error}


# ----- share-link import (vless:// etc.) --------------------------------


def import_links(client: RouterClient, text: str) -> dict:
    """Import one or more proxy share-links via import_link.uc.

    Returns the script's JSON: {result, imported:[{section,label,type}], failed}
    or {error}. Imported nodes carry no grouphash (survive subscription updates).
    """
    links = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not links:
        return {"result": False, "error": "no links"}
    client.write_file(_LINKS_TMP, "\n".join(links) + "\n")
    res = client.run(f"ucode {IMPORT_LINK_SCRIPT} {shlex.quote(_LINKS_TMP)} 2>&1", timeout=30)
    client.run(f"rm -f {shlex.quote(_LINKS_TMP)}")
    out = res.stdout.strip()
    try:
        return json.loads(out.splitlines()[-1]) if out else {"error": "no output"}
    except (json.JSONDecodeError, IndexError):
        return {"error": out or "import failed"}


# ----- nodes ------------------------------------------------------------


def list_nodes(client: RouterClient) -> list[Node]:
    """List node sections with their label and type, read from uci."""
    cmd = (
        "for s in $(uci show homeproxy | sed -n "
        r"'s/^homeproxy\.\([^.]*\)=node$/\1/p'); do "
        r'printf "%s\t%s\t%s\t%s\t%s\n" "$s" '
        '"$(uci -q get homeproxy.$s.label)" "$(uci -q get homeproxy.$s.type)" '
        '"$(uci -q get homeproxy.$s.transport)" '
        '"$(uci -q get homeproxy.$s.shadowtls_enabled)"; done'
    )
    res = client.run(cmd, timeout=20)
    nodes: list[Node] = []
    if res.ok:
        for line in res.stdout.splitlines():
            parts = line.split("\t")
            if parts and parts[0]:
                nodes.append(
                    Node(
                        section=parts[0],
                        label=parts[1] if len(parts) > 1 else "",
                        type=parts[2] if len(parts) > 2 else "",
                        transport=parts[3] if len(parts) > 3 else "",
                        shadowtls=(len(parts) > 4 and parts[4] == "1"),
                    )
                )
    return nodes


# ----- main node selection ----------------------------------------------

MAIN_NODE_KEY = "homeproxy.config.main_node"
URLTEST_NODES_KEY = "homeproxy.config.main_urltest_nodes"

# Node types that break a given core's config generation, so they must be kept
# out of the URLTest pool — ONE incompatible node FATALs the whole config.
# sing-box-extended is built WITHOUT NaïveProxy (its only protocol gap; SSH and
# TUIC do work on it). hiddify-core lacks AmneziaWG. (TrustTunnel is sing-box-
# extended-only too, but it isn't a selectable node 'type', so nothing to filter.)
_CORE_INCOMPATIBLE = {
    "singbox": {"naive"},
    "hiddify": {"amneziawg"},
}
# Cap the auto pool so URLTest doesn't probe hundreds of nodes every interval.
# Kept small on purpose: a leaner, protocol-diverse pool tests faster and is more
# robust than dozens of same-type nodes (a few of which may be dead/blocked).
URLTEST_POOL_CAP = 15

# Protocol diversity for the auto (URLTest) pool, in PREFERENCE order. The pool is
# filled round-robin across these buckets so it spreads over different protocols
# (resilient if one whole protocol is blocked) rather than 15 nodes of one type.
# This is a recommendation, not a hard filter: weaker/other types (see _WEAK_BUCKETS)
# still get pulled in if the preferred buckets can't fill the cap.
_PREFERRED_BUCKETS = (
    "amneziawg",      # core-gated: sing-box-extended only
    "vless-xhttp",    # vless with xhttp transport — strong against DPI
    "hysteria2",
    "shadowtls",
    "mieru",
    "naive",          # core-gated: hiddify-core only
    "vless",          # other vless transports
    "trojan",
    "vmess",
)
# Pulled in only after the preferred buckets are exhausted (Shadowsocks last:
# weakest URLTest candidate, and risky on sing-box ≥1.12 with udp_over_tcp gone).
_WEAK_BUCKETS = ("shadowsocks",)


def _bucket_of(node: "Node") -> str:
    """Diversity bucket for a node. Two regroupings matter for RU:
    - vless+xhttp is split out from plain vless (strong vs ordinary);
    - a Shadowsocks node wrapped in ShadowTLS (shadowtls_enabled) is TLS-camouflaged
      and DPI-survivable, so it joins the strong 'shadowtls' bucket — NOT the weak
      plain-shadowsocks one (which gets DPI-blocked in Russia almost instantly)."""
    if node.type == "vless" and node.transport == "xhttp":
        return "vless-xhttp"
    if node.type == "shadowsocks" and node.shadowtls:
        return "shadowtls"
    return node.type


def _round_robin(buckets: dict[str, list["Node"]], order: list[str],
                 pool: list[str], cap: int) -> list[str]:
    """Append node sections to ``pool`` by taking one from each bucket per pass,
    visiting buckets in ``order`` — gives a protocol-diverse spread up to ``cap``."""
    queues = [list(buckets[k]) for k in order if buckets.get(k)]
    while len(pool) < cap and any(queues):
        for q in queues:
            if q:
                pool.append(q.pop(0).section)
                if len(pool) >= cap:
                    return pool
    return pool


def active_core(client: RouterClient) -> str:
    """Which core is active: 'singbox' or 'hiddify' (preferred_core, then detect)."""
    pref = client.uci_get("homeproxy.config.preferred_core")
    if pref in ("singbox", "hiddify"):
        return pref
    info = client.ubus_homeproxy("diag_core_check")
    if info.get("hiddify_installed") and not info.get("singbox_installed"):
        return "hiddify"
    return "singbox"


# A Russia-located exit (name has "Russia"/"Россия") can't bypass RU blocks, so it's
# kept OUT of the default auto pool. Whitelist servers (name has "Whitelist"/"белые
# списки") are the provider's RU-routing servers — used ONLY for the whitelist pool.
_RU_NAME_RE = re.compile(r"russia|росси", re.IGNORECASE)
_WL_NAME_RE = re.compile(r"whitelist|бел\w*\s*спис", re.IGNORECASE)
# The provider's own "best" pick (name has "Авто"/"Auto"/"Лучший"/"Best", e.g.
# "Авто | Лучший сервер") goes into the auto pool FIRST, as a priority member.
_PRIORITY_NAME_RE = re.compile(r"авто|auto|лучш|best", re.IGNORECASE)


def build_urltest_pool(nodes: list[Node], core: str, *, cap: int = URLTEST_POOL_CAP,
                       whitelist: bool = False, wl_cap: int = 5) -> list[str]:
    """Sections for the auto (URLTest) pool: core-incompatible types are dropped
    HARD (one such node FATALs config generation), then the rest are picked
    round-robin across protocol buckets for diversity, preferring the strong
    protocols and only dipping into weaker ones (Shadowsocks) to reach ``cap``.

    Russia-named servers are ALWAYS excluded (a RU exit can't bypass RU blocks).

    Whitelist-named servers ("Whitelist"/"белые списки" — the provider's RU-routing
    servers) are handled by ``whitelist``:
    - ``whitelist=False`` (default): they are a LAST RESORT — added only if the
      ordinary servers couldn't fill ``cap``.
    - ``whitelist=True``: up to ``wl_cap`` (5) of them are placed in the pool FIRST,
      then the remaining capacity is filled with ordinary servers as usual."""
    bad = _CORE_INCOMPATIBLE.get(core, set())
    buckets: dict[str, list[Node]] = {}      # ordinary servers, by protocol bucket
    wl_nodes: list[Node] = []                # Whitelist-named servers, kept aside
    priority: list[Node] = []                # provider's "Авто/Лучший" pick(s)
    for n in nodes:
        if n.type in bad or not n.type:
            continue
        name = n.label or ""
        if _RU_NAME_RE.search(name):
            continue                          # Russia exits never join the pool
        if _WL_NAME_RE.search(name):
            wl_nodes.append(n)
            continue
        if _PRIORITY_NAME_RE.search(name):
            priority.append(n)                # provider's recommended best → first
            continue
        buckets.setdefault(_bucket_of(n), []).append(n)

    # Any node type we didn't name explicitly is treated as "other" — included
    # after the preferred set but ahead of the explicitly-weak Shadowsocks.
    known = set(_PREFERRED_BUCKETS) | set(_WEAK_BUCKETS)
    other = [k for k in buckets if k not in known]

    pool: list[str] = []
    if whitelist:
        # Whitelist setup: seed with up to wl_cap whitelist servers, then fill the
        # rest of the pool with ordinary servers as usual.
        pool.extend(n.section for n in wl_nodes[:wl_cap])
    # The provider's "Авто/Лучший" pick goes in FIRST (priority), ahead of the
    # protocol round-robin — but never crowds out the whole cap.
    for n in priority:
        if len(pool) >= cap:
            break
        pool.append(n.section)
    pool = _round_robin(buckets, list(_PREFERRED_BUCKETS), pool, cap)
    if len(pool) < cap:
        pool = _round_robin(buckets, other + list(_WEAK_BUCKETS), pool, cap)
    if not whitelist and not pool and wl_nodes:
        # Default mode: whitelist servers are RU-routing (whitelisted destinations
        # only), so they join the general pool ONLY as an absolute last resort —
        # when there is no ordinary server at all.
        pool = _round_robin({"_wl": wl_nodes}, ["_wl"], pool, cap)
    return pool


# Back-compat alias: older call sites used this name (now diversity-aware).
core_compatible_sections = build_urltest_pool


def get_main_node(client: RouterClient) -> str:
    """Current main_node value ('' if unset, 'urltest', or a node section id)."""
    return client.uci_get(MAIN_NODE_KEY) or ""


def set_main_node(client: RouterClient, value: str, *,
                  urltest_nodes: list[str] | None = None) -> None:
    """Set the main node — a specific node section, or 'urltest' (auto-fastest).

    For 'urltest' the pool (main_urltest_nodes) is REQUIRED — an empty pool makes
    the urltest outbound have no members, so we populate it (and set sane
    interval/tolerance defaults matching the LuCI placeholders).
    """
    client.uci_set(MAIN_NODE_KEY, value)
    if value == "urltest":
        client.run(f"uci -q delete {URLTEST_NODES_KEY}")
        for n in (urltest_nodes or []):
            client.uci_add_list(URLTEST_NODES_KEY, n)
        if not client.uci_get("homeproxy.config.main_urltest_interval"):
            client.uci_set("homeproxy.config.main_urltest_interval", "180")
        if not client.uci_get("homeproxy.config.main_urltest_tolerance"):
            client.uci_set("homeproxy.config.main_urltest_tolerance", "150")
    client.uci_commit("homeproxy")


def apply_and_restart(client: RouterClient) -> bool:
    """Regenerate the core config + restart the service so node changes take effect."""
    res = client.ubus_homeproxy("diag_service_restart", timeout=40)
    return bool(res.get("result"))


# ----- .conf import (WireGuard / AmneziaWG) -----------------------------


def import_conf(client: RouterClient, conf_text: str, label: str = "") -> dict:
    """Push a .conf and run import_conf.uc; return its parsed JSON result."""
    client.write_file(_IMPORT_TMP, conf_text)
    cmd = f"ucode {IMPORT_CONF_SCRIPT} {shlex.quote(_IMPORT_TMP)}"
    if label.strip():
        cmd += f" {shlex.quote(label.strip())}"
    res = client.run(cmd, timeout=30)
    client.run(f"rm -f {shlex.quote(_IMPORT_TMP)}")  # don't leave the conf on /tmp
    text = res.stdout.strip()
    try:
        return json.loads(text.splitlines()[-1]) if text else {"error": "no output"}
    except (json.JSONDecodeError, IndexError):
        return {"error": text or "import failed"}
