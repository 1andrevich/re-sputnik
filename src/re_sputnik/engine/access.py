# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Access control — per-device proxy policy (homeproxy.control.lan_*).

HomeProxy's real model is ONE global filter mode plus THREE INDEPENDENT lists,
and a single device IP may sit in several at once (mirrors the LuCI page):

Global filter mode (``lan_proxy_mode``):
- disabled      → the device filter list is off
- listed_only   → only devices in the Proxy list go through VPN, the rest direct
- except_listed → all devices go through VPN except those in the Direct list

Three independent IPv4 lists (each separate from the global mode and from each other):
- filter  → lan_proxy_ipv4_ips   (when mode=listed_only)   "go through VPN"
            lan_direct_ipv4_ips  (when mode=except_listed)  "go direct"
- gaming  → lan_gaming_mode_ipv4_ips   only TCP of the device is proxied (UDP direct)
- global  → lan_global_proxy_ipv4_ips  ALL traffic of the device goes through VPN,
                                        bypassing the routing rules

So one device can be e.g. in the proxy list AND gaming (TCP-only) AND global proxy.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..router import RouterClient

SECTION = "homeproxy.control"
MODE_KEY = f"{SECTION}.lan_proxy_mode"

# Underlying uci IPv4 list per logical list name.
LIST_KEYS = {
    "direct": f"{SECTION}.lan_direct_ipv4_ips",
    "proxy": f"{SECTION}.lan_proxy_ipv4_ips",
    "gaming": f"{SECTION}.lan_gaming_mode_ipv4_ips",
    "global": f"{SECTION}.lan_global_proxy_ipv4_ips",
}
GLOBAL_MODES = ["disabled", "listed_only", "except_listed"]

# Which underlying list the per-device "filter" toggle writes to, given the global
# mode. In 'disabled' the filter toggle is inert (no list is consulted).
FILTER_LIST_FOR_MODE = {"listed_only": "proxy", "except_listed": "direct"}

# Independent device flags and the list each maps to directly (filter is special,
# resolved via FILTER_LIST_FOR_MODE because its target depends on the global mode).
INDEPENDENT_FLAGS = {"gaming": "gaming", "global": "global"}


@dataclass(slots=True)
class Device:
    mac: str
    ip: str
    hostname: str
    manual: bool = False  # configured IP not currently in DHCP (e.g. added in LuCI)


def _ip_key(ip: str) -> tuple:
    """Numeric sort key for an IPv4 string (so .9 sorts before .108)."""
    try:
        return tuple(int(o) for o in ip.split("."))
    except ValueError:
        return (999, ip)


def list_devices(client: RouterClient) -> list[Device]:
    """Devices from /tmp/dhcp.leases (fields: ts mac ip hostname clientid)."""
    res = client.run("cat /tmp/dhcp.leases 2>/dev/null")
    devices: list[Device] = []
    if res.ok:
        for line in res.stdout.splitlines():
            p = line.split()
            if len(p) >= 4:
                devices.append(Device(mac=p[1], ip=p[2], hostname=p[3] if p[3] != "*" else p[2]))
    devices.sort(key=lambda d: _ip_key(d.ip))
    return devices


def merge_configured(devices: list[Device], policy: dict) -> list[Device]:
    """Add IPs already configured in the homeproxy lists that aren't in the DHCP
    leases, so manually-added IPs (e.g. set in LuCI) and offline/static devices
    still appear. Marked ``manual=True`` so the UI can flag them."""
    have = {d.ip for d in devices}
    extra: list[Device] = []
    for ips in policy.get("lists", {}).values():
        for ip in ips:
            if ip not in have:
                have.add(ip)
                extra.append(Device(mac="", ip=ip, hostname=ip, manual=True))
    return sorted(devices + extra, key=lambda d: _ip_key(d.ip))


def get_policy(client: RouterClient) -> dict:
    """Global mode + every per-list IPv4 set."""
    policy = {"mode": client.uci_get(MODE_KEY) or "disabled", "lists": {}}
    for name, key in LIST_KEYS.items():
        policy["lists"][name] = set(client.uci_get_list(key))
    return policy


def device_flags(ip: str, policy: dict) -> dict:
    """The three independent toggles for a device, given the current global mode.

    ``filter`` reflects membership in whichever list the current mode consults
    (proxy list for listed_only, direct list for except_listed; always False under
    'disabled'). ``gaming`` / ``global`` are mode-independent."""
    lists = policy.get("lists", {})
    mode = policy.get("mode", "disabled")
    filt_list = FILTER_LIST_FOR_MODE.get(mode)
    return {
        "filter": bool(filt_list) and ip in lists.get(filt_list, set()),
        "gaming": ip in lists.get("gaming", set()),
        "global": ip in lists.get("global", set()),
    }


def _flag_list_name(flag: str, mode: str) -> str | None:
    """Which logical list a flag writes to (None if the flag is inert in this mode)."""
    if flag == "filter":
        return FILTER_LIST_FOR_MODE.get(mode)
    return INDEPENDENT_FLAGS.get(flag)


def set_device_flag(client: RouterClient, ip: str, flag: str, on: bool, mode: str) -> None:
    """Add/remove a device IP from ONE list (non-exclusive — other flags untouched)."""
    name = _flag_list_name(flag, mode)
    if name is None:
        return
    key = LIST_KEYS[name]
    present = ip in client.uci_get_list(key)
    if on and not present:
        client.uci_add_list(key, ip)
    elif not on and present:
        client.uci_del_list(key, ip)
    else:
        return  # already in the desired state — nothing to commit
    client.uci_commit("homeproxy")


def set_global_mode(client: RouterClient, mode: str) -> None:
    if mode not in GLOBAL_MODES:
        return
    client.uci_set(MODE_KEY, mode)
    client.uci_commit("homeproxy")
