# SPDX-License-Identifier: GPL-2.0-only
"""UPnP / NAT-PMP (miniupnpd) — read state, toggle the service, list active
port-forwards. Only meaningful when the ``miniupnpd`` package is installed; the
Advanced screen shows the card only then.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field

from ..router import RouterClient

_LEASE_DEFAULT = "/var/run/miniupnpd.leases"


@dataclass(slots=True)
class UpnpRedirect:
    proto: str       # TCP / UDP
    ext_port: str
    int_ip: str
    int_port: str
    desc: str


@dataclass(slots=True)
class UpnpStatus:
    installed: bool = False
    enabled: bool = False        # uci upnpd.config.enabled
    running: bool = False        # miniupnpd process alive
    redirects: list = field(default_factory=list)


def is_installed(client: RouterClient) -> bool:
    return client.run("[ -x /etc/init.d/miniupnpd ] && echo y").stdout.strip() == "y"


def get_status(client: RouterClient) -> UpnpStatus:
    if not is_installed(client):
        return UpnpStatus(installed=False)
    enabled = client.uci_get("upnpd.config.enabled") == "1"
    running = client.run("pidof miniupnpd >/dev/null 2>&1 && echo y").stdout.strip() == "y"
    return UpnpStatus(installed=True, enabled=enabled, running=running,
                      redirects=_read_redirects(client))


def _read_redirects(client: RouterClient) -> list[UpnpRedirect]:
    """Active mappings from miniupnpd's lease file.

    Format per line: ``PROTO:EPORT:IADDR:IPORT:EXPIRE:DESCRIPTION``.
    """
    lease = client.uci_get("upnpd.config.upnp_lease_file") or _LEASE_DEFAULT
    out = client.run(f"cat {shlex.quote(lease)} 2>/dev/null").stdout
    res: list[UpnpRedirect] = []
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(":", 5)
        if len(parts) >= 4:
            res.append(UpnpRedirect(
                proto=parts[0], ext_port=parts[1], int_ip=parts[2], int_port=parts[3],
                desc=parts[5] if len(parts) > 5 else ""))
    return res


def set_enabled(client: RouterClient, on: bool) -> None:
    """Enable/disable the UPnP service (uci + init.d)."""
    client.run(
        f"uci set upnpd.config.enabled={'1' if on else '0'}; uci commit upnpd").check()
    if on:
        client.run("/etc/init.d/miniupnpd enable 2>/dev/null; "
                   "/etc/init.d/miniupnpd restart 2>/dev/null; true")
    else:
        client.run("/etc/init.d/miniupnpd stop 2>/dev/null; "
                   "/etc/init.d/miniupnpd disable 2>/dev/null; true")
