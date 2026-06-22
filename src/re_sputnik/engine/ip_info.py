# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Public-IP lookup that works on ANY core.

The backend ``clash_ip_info`` reads the ``ipinfo`` field from the Clash API
proxy history — a hiddify-core / clash-meta extension that sing-box-extended
does NOT populate, so on sing-box-extended the diagnostics IP card is always
empty. This module asks the router to fetch its public IP directly, and again
through the mixed proxy inbound (port 5330, always present), so we get a real
"provider vs proxy" answer regardless of which core is running.

Best-effort and read-only: every failure degrades to ``None`` rather than
raising, so it can be used as a fallback without risk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..router import RouterClient

# Mixed (SOCKS+HTTP) proxy inbound — hardcoded default in generate_client.uc.
MIXED_PROXY_PORT = 5330

# Lightweight JSON IP echo; returns {"ip","country","org"} on the free tier.
_IP_ENDPOINT = "https://ipinfo.io/json"


@dataclass(slots=True)
class IpEntry:
    ip: str
    country: Optional[str] = None
    org: Optional[str] = None


def _query(client: RouterClient, proxy_env: str) -> Optional[IpEntry]:
    cmd = f"{proxy_env}wget -qO- --timeout=6 {_IP_ENDPOINT} 2>/dev/null"
    out = client.run(cmd, timeout=15).stdout.strip()
    if not out:
        return None
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    ip = data.get("ip")
    if not ip:
        return None
    return IpEntry(ip=ip, country=data.get("country"), org=data.get("org"))


def fetch_ip_info(client: RouterClient, *, port: int = MIXED_PROXY_PORT) -> dict:
    """Public IP directly and through the mixed proxy. Shape mirrors clash_ip_info.

    Returns ``{"direct": {...}|None, "proxy": {...}|None}`` with each entry a
    dict ``{ip, country, org}`` (or None). Core-independent.
    """
    proxy_env = (f"http_proxy=http://127.0.0.1:{port} "
                 f"https_proxy=http://127.0.0.1:{port} ")
    direct = _query(client, "")
    proxy = _query(client, proxy_env)

    def as_dict(e: Optional[IpEntry]) -> Optional[dict]:
        return None if e is None else {"ip": e.ip, "country": e.country, "org": e.org}

    return {"direct": as_dict(direct), "proxy": as_dict(proxy)}
