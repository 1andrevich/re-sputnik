# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""LAN address / DHCP server settings + per-device static leases.

These are the router's core network identity, so changing them is dangerous: a
new LAN IP or netmask drops every device (including the PC running the app), and
a bad DHCP range can leave clients without an address. The UI gates the apply
behind an explicit confirmation; this module validates hard and applies the
change with a DETACHED network reload (so the SSH call returns before our own
connection is cut), mirroring ``network.change_lan_ip``.

Static leases ("permanent IP for a device") are a low-risk dnsmasq reload — they
just pin a device's MAC to a fixed address (a uci ``config host`` entry).
"""

from __future__ import annotations

import ipaddress
import re
import shlex
from dataclasses import dataclass

from ..router import RouterClient, RouterError
from ..i18n import _

# How the LAN address is configured changed across OpenWrt releases:
#   <= 24.10  : separate `network.lan.ipaddr` + `network.lan.netmask` (two fields)
#   >= 25.12  : a single CIDR `network.lan.ipaddr='192.168.1.1/24'`, no netmask
#   SNAPSHOT  : rolling/unversioned — too unpredictable to touch safely.
NET_SPLIT = "split"      # IP + netmask
NET_CIDR = "cidr"        # single CIDR address
NET_SNAPSHOT = "snapshot"  # hide the section, tell the user to do it by hand

_VER_RE = re.compile(r"^(\d+)\.(\d+)")


def _distrib_release(client: RouterClient) -> str:
    """OpenWrt version string (DISTRIB_RELEASE), e.g. '24.10.0' / '25.12.0' /
    'SNAPSHOT' / '24.10-SNAPSHOT'. Falls back to os-release VERSION_ID."""
    out = client.run("cat /etc/openwrt_release 2>/dev/null").stdout
    for line in out.splitlines():
        if line.startswith("DISTRIB_RELEASE="):
            return line.split("=", 1)[1].strip().strip("'\"")
    out = client.run("cat /etc/os-release 2>/dev/null").stdout
    for line in out.splitlines():
        if line.startswith("VERSION_ID="):
            return line.split("=", 1)[1].strip().strip("'\"")
    return ""


def detect_network_mode(client: RouterClient) -> str:
    """Which LAN-address UI to show: NET_SPLIT / NET_CIDR / NET_SNAPSHOT.

    A bare 'SNAPSHOT' (NOT '24.10-SNAPSHOT' / '25.12-SNAPSHOT') → snapshot mode.
    Otherwise the (major, minor) version decides: >= 25.12 → CIDR, else split.
    Unrecognised/forked version strings default to the safe two-field split form."""
    rel = _distrib_release(client)
    if rel.strip().upper() == "SNAPSHOT":
        return NET_SNAPSHOT
    m = _VER_RE.match(rel.strip())
    if not m:
        return NET_SPLIT
    return NET_CIDR if (int(m.group(1)), int(m.group(2))) >= (25, 12) else NET_SPLIT


def netmask_to_prefix(netmask: str) -> int:
    """'255.255.255.0' -> 24 (defaults to 24 on a malformed mask)."""
    try:
        return ipaddress.ip_network(f"0.0.0.0/{netmask.strip()}").prefixlen
    except ValueError:
        return 24


def cidr_of(ip: str, netmask: str) -> str:
    """Compose the single-field CIDR address, e.g. '192.168.1.1/24'."""
    return f"{ip.strip()}/{netmask_to_prefix(netmask)}"


def parse_cidr(cidr: str) -> "tuple[str, str] | None":
    """'192.168.1.1/24' -> (ip, netmask); None if malformed."""
    cidr = cidr.strip()
    if "/" not in cidr:
        return None
    ip, _sep, pfx = cidr.partition("/")
    if not pfx.isdigit():
        return None
    try:
        net = ipaddress.ip_network(f"0.0.0.0/{pfx}")
        ipaddress.ip_address(ip.strip())
    except ValueError:
        return None
    return ip.strip(), str(net.netmask)


@dataclass(slots=True)
class LanSettings:
    ipaddr: str
    netmask: str
    dhcp_start: int       # first host offset in the LAN subnet (dnsmasq 'start')
    dhcp_limit: int       # number of addresses to hand out ('limit')
    leasetime: str        # e.g. "12h", "1d", "infinite"
    dhcp_enabled: bool     # dhcp.lan.ignore == 0


@dataclass(slots=True)
class StaticLease:
    name: str
    mac: str
    ip: str
    index: int            # position in dhcp.@host[] (for removal)


def get_lan_settings(client: RouterClient) -> LanSettings:
    ip = client.uci_get("network.lan.ipaddr") or "192.168.1.1"
    mask = client.uci_get("network.lan.netmask") or ""
    # OpenWrt allows CIDR in ipaddr (e.g. "192.168.1.1/24") with no separate
    # netmask — split it so the IP field stays clean and the mask reflects reality.
    if "/" in ip:
        ip, _sep, prefix = ip.partition("/")
        if not mask and prefix.isdigit():
            try:
                mask = str(ipaddress.ip_network(f"0.0.0.0/{prefix}").netmask)
            except ValueError:
                pass
    if not mask:
        mask = "255.255.255.0"
    start = client.uci_get("dhcp.lan.start")
    limit = client.uci_get("dhcp.lan.limit")
    lease = client.uci_get("dhcp.lan.leasetime") or "12h"
    ignore = client.uci_get("dhcp.lan.ignore")
    return LanSettings(
        ipaddr=ip, netmask=mask,
        dhcp_start=int(start) if (start and start.isdigit()) else 100,
        dhcp_limit=int(limit) if (limit and limit.isdigit()) else 150,
        leasetime=lease,
        dhcp_enabled=(ignore not in ("1",)),
    )


def _leasetime_ok(v: str) -> bool:
    v = v.strip().lower()
    if v == "infinite":
        return True
    return len(v) >= 2 and v[-1] in ("m", "h", "d") and v[:-1].isdigit() and int(v[:-1]) > 0


# ----- lease time as ЧЧ:ММ (idiot-proof form) ---------------------------

_LEASE_MAX_MIN = 720 * 60  # 30 days — sane upper bound for a DHCP lease


def leasetime_to_hm(s: str) -> tuple[int, int]:
    """dnsmasq leasetime string → (hours, minutes) for the ЧЧ:ММ form.

    Accepts the usual suffixes (m/h/d), a bare seconds count, or 'infinite'
    (and anything unparseable) → falls back to 12:00."""
    s = (s or "").strip().lower()
    mins: "int | None" = None
    if s.endswith("m") and s[:-1].isdigit():
        mins = int(s[:-1])
    elif s.endswith("h") and s[:-1].isdigit():
        mins = int(s[:-1]) * 60
    elif s.endswith("d") and s[:-1].isdigit():
        mins = int(s[:-1]) * 1440
    elif s.isdigit():
        mins = int(s) // 60  # bare value = seconds
    if not mins or mins <= 0:
        mins = 720  # default 12:00
    return mins // 60, mins % 60


def hm_to_leasetime(hours: int, minutes: int) -> str:
    """(hours, minutes) → dnsmasq leasetime in minutes, e.g. '750m'."""
    return f"{hours * 60 + minutes}m"


def validate_hm(hours: str, minutes: str) -> "str | None":
    """Validate the ЧЧ:ММ lease-time form. Returns an error string or None."""
    h, m = hours.strip(), minutes.strip()
    if not h.isdigit() or not m.isdigit():
        return _("Время аренды: введите ЧЧ:ММ, например 12:00.")
    hh, mm = int(h), int(m)
    if mm > 59:
        return _("Минуты должны быть от 00 до 59.")
    total = hh * 60 + mm
    if total < 2:
        return _("Слишком маленькое время аренды — минимум 00:02.")
    if total > _LEASE_MAX_MIN:
        return _("Слишком большое время аренды — максимум 720:00 (30 суток).")
    return None


def validate_lan_settings(ipaddr: str, netmask: str, dhcp_start: str, dhcp_limit: str,
                          leasetime: str) -> "str | None":
    """Return a human error string, or None if the settings are sane."""
    try:
        ip = ipaddress.ip_address(ipaddr.strip())
    except ValueError:
        return _("Неверный IP-адрес роутера.")
    if ip.version != 4:
        return _("Нужен адрес IPv4.")
    if not ip.is_private:
        return _("Используйте частный адрес (192.168.x.x, 10.x.x.x или 172.16–31.x.x).")
    try:
        net = ipaddress.ip_network(f"{ip}/{netmask.strip()}", strict=False)
    except ValueError:
        return _("Неверная маска подсети.")
    if net.prefixlen > 30:
        return _("Слишком маленькая подсеть — выберите маску не уже /30.")
    if int(str(ip).split(".")[-1]) in (0, 255):
        return _("Адрес роутера не может быть адресом сети/широковещания.")
    for label, raw in ((_("Начало диапазона DHCP"), dhcp_start), (_("Размер диапазона DHCP"), dhcp_limit)):
        if not raw.strip().isdigit() or int(raw) <= 0:
            return f"{label}: введите положительное число."
    usable = net.num_addresses - 2  # minus network + broadcast
    if int(dhcp_start) + int(dhcp_limit) - 1 > usable:
        return _("Диапазон DHCP не помещается в подсеть — уменьшите начало или размер.")
    if not _leasetime_ok(leasetime):
        return _("Время аренды: например 30m, 12h, 1d или infinite.")
    return None


def apply_lan_settings(client: RouterClient, s: LanSettings, *, cidr_mode: bool = False) -> None:
    """Write LAN + DHCP settings and reload the network DETACHED.

    The reload runs after a short delay in the background so this SSH command
    returns BEFORE the address change drops our connection. The caller must then
    reconnect at the new address.

    ``cidr_mode`` (OpenWrt >= 25.12) writes a single CIDR ipaddr and removes the
    separate netmask option; otherwise the classic ipaddr + netmask pair is set.
    """
    ignore = "0" if s.dhcp_enabled else "1"
    if cidr_mode:
        addr_cmds = (
            f"uci set network.lan.ipaddr={shlex.quote(cidr_of(s.ipaddr, s.netmask))}; "
            "uci -q delete network.lan.netmask; ")
    else:
        addr_cmds = (
            f"uci set network.lan.ipaddr={shlex.quote(s.ipaddr.strip())}; "
            f"uci set network.lan.netmask={shlex.quote(s.netmask.strip())}; ")
    client.run(
        addr_cmds
        + f"uci set dhcp.lan.start={shlex.quote(str(s.dhcp_start))}; "
        f"uci set dhcp.lan.limit={shlex.quote(str(s.dhcp_limit))}; "
        f"uci set dhcp.lan.leasetime={shlex.quote(s.leasetime.strip())}; "
        f"uci set dhcp.lan.ignore={ignore}; "
        "uci commit network; uci commit dhcp; "
        "(sleep 2; /etc/init.d/network reload; /etc/init.d/dnsmasq reload) >/dev/null 2>&1 &",
        timeout=15,
    ).check()


# ----- static leases (permanent IP for a device) ------------------------


def list_static_leases(client: RouterClient) -> list[StaticLease]:
    """Existing dhcp ``config host`` reservations, in order."""
    leases: list[StaticLease] = []
    res = client.run("uci show dhcp 2>/dev/null | grep '=host$'")
    if not res.ok:
        return leases
    for line in res.stdout.splitlines():
        # dhcp.@host[N]=host
        sec = line.split("=", 1)[0]
        if "[" not in sec or "]" not in sec:
            continue
        try:
            idx = int(sec.split("[", 1)[1].split("]", 1)[0])
        except ValueError:
            continue
        name = client.uci_get(f"dhcp.@host[{idx}].name") or ""
        mac = client.uci_get(f"dhcp.@host[{idx}].mac") or ""
        ip = client.uci_get(f"dhcp.@host[{idx}].ip") or ""
        leases.append(StaticLease(name=name, mac=mac, ip=ip, index=idx))
    return leases


def add_static_lease(client: RouterClient, *, name: str, mac: str, ip: str) -> None:
    """Pin ``mac`` to ``ip`` permanently (a dhcp host reservation), then reload
    dnsmasq. Replaces any existing reservation for the same MAC so re-pinning a
    device doesn't create duplicates. Low risk — only dnsmasq reloads."""
    mac = mac.strip().lower()
    ip = ip.strip()
    if not mac or not ip:
        raise ValueError(_("Нужны MAC и IP устройства."))
    try:
        ipaddress.ip_address(ip)
    except ValueError as exc:
        raise ValueError(f"неверный IP: {ip}") from exc
    # Drop an existing reservation for this MAC first (idempotent re-pin).
    for lease in list_static_leases(client):
        if lease.mac.strip().lower() == mac:
            client.run(f"uci -q delete dhcp.@host[{lease.index}]")
    client.run(
        "s=$(uci add dhcp host); "
        f"uci set dhcp.$s.name={shlex.quote(name.strip() or ip)}; "
        f"uci set dhcp.$s.mac={shlex.quote(mac)}; "
        f"uci set dhcp.$s.ip={shlex.quote(ip)}; "
        "uci commit dhcp; /etc/init.d/dnsmasq reload >/dev/null 2>&1",
        timeout=15,
    ).check()


def remove_static_lease(client: RouterClient, mac: str) -> None:
    """Remove the reservation matching ``mac`` (looked up fresh to avoid stale
    indices), then reload dnsmasq."""
    mac = mac.strip().lower()
    target = next((lease for lease in list_static_leases(client)
                   if lease.mac.strip().lower() == mac), None)
    if target is None:
        raise RouterError(_("Закрепление для этого устройства не найдено."))
    client.run(
        f"uci -q delete dhcp.@host[{target.index}]; uci commit dhcp; "
        "/etc/init.d/dnsmasq reload >/dev/null 2>&1",
        timeout=15,
    ).check()
