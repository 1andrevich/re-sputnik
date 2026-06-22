# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""SQM (sqm-scripts) — Smart Queue Management / bufferbloat control.

Reads and writes the first ``sqm`` queue section: WAN interface, down/up rate
caps, queue discipline (cake / fq_codel), the qos script template, and the
per-packet overhead. Only meaningful when ``sqm-scripts`` is installed.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

from ..router import RouterClient
from . import network as net
from ..i18n import _

_REF = "sqm.@queue[0]"  # uci anonymous ref to the first queue section

# Queue script templates offered (script ↔ human label). piece_of_cake = simple
# single-tier shaping (best with cake); layer_cake = cake with built-in
# diffserv classification; simple/simplest = the fq_codel-era scripts.
SCRIPTS = [
    ("piece_of_cake.qos", "Простой (piece_of_cake) — рекомендуется"),
    ("layer_cake.qos", "С приоритизацией (layer_cake)"),
    ("simple.qos", "Простой для fq_codel (simple)"),
    ("simplest.qos", "Минимальный (simplest)"),
]
QDISCS = ["cake", "fq_codel"]


@dataclass(slots=True)
class SqmSettings:
    installed: bool = False
    enabled: bool = False
    interface: str = ""
    download: int = 0      # kbit/s, ingress cap (0 = unset)
    upload: int = 0        # kbit/s, egress cap
    qdisc: str = "cake"
    script: str = "piece_of_cake.qos"
    linklayer: str = "ethernet"
    overhead: int = 44
    exists: bool = False   # a queue section already exists in uci


def is_installed(client: RouterClient) -> bool:
    return client.run("[ -x /etc/init.d/sqm ] && echo y").stdout.strip() == "y"


# --- speed measurement (download test, upload derived) -------------------

_MEASURE_WINDOW = 8  # seconds to pull data — accuracy vs. data used (~speed×8s)
# Big files to stream from. Host-agnostic method (count bytes over a fixed window)
# means the exact size doesn't matter — any large file works, so RU-reachable
# mirrors are fine. Tried in order; first that delivers enough data wins. Edit
# freely if a host gets blocked/throttled for a given ISP.
_MEASURE_URLS: list[str] = [
    "https://speedtest.selectel.ru/1GB",                     # RU mirror (Selectel), confirmed
    "https://speed.cloudflare.com/__down?bytes=1000000000",  # global fallback
    "https://speedtest.selectel.ru/100MB",                   # RU, smaller — slow-link fallback
]
MEASURE_MARGIN_KBIT = 1500  # SQM wants a hair under the line: shave ~1.5 Mbit/s (1–2 Mbit/s) off the measured rate
UPLOAD_FRACTION = 0.5       # upload guessed as this share of download — user adjusts


def measure_speeds(client: RouterClient) -> tuple[int, int]:
    """Best-effort WAN download test, with upload derived as a fraction of it.
    Returns (download_kbit, upload_kbit); download is the measured rate minus a
    ~1.5 Mbit/s margin, upload derived as a fraction of it.

    Counts bytes pulled over a fixed ``_MEASURE_WINDOW`` (``wget -O - | wc -c``
    under ``timeout``) and times the window via ``/proc/uptime`` — so it needs
    NO known file size (any big file works, incl. RU mirrors) and bounds the data
    used. Raises if no host delivers enough data.

    NOTE: measures the router's CURRENT egress. If the router itself routes
    through a VPN, the figure reflects the VPN, not the raw line — that's a
    routing fact, not a host issue (no test host changes it)."""
    last = ""
    for url in _MEASURE_URLS:
        # No `timeout`/`usleep` on this busybox, so bound the pull by time with a
        # backgrounded wget + integer `sleep` + `kill`, and count throughput from
        # the WAN egress interface's rx_bytes counter (no temp file, any link speed).
        cmd = (
            "DEV=$(ip route | awk '/^default/{for(i=1;i<=NF;i++) if($i==\"dev\") "
            "print $(i+1)}' | head -1); "
            "RXF=/sys/class/net/$DEV/statistics/rx_bytes; "
            "R1=$(cat $RXF 2>/dev/null || echo 0); S=$(cut -d' ' -f1 /proc/uptime); "
            f"wget -q -O /dev/null {shlex.quote(url)} & WP=$!; "
            f"sleep {_MEASURE_WINDOW}; kill $WP 2>/dev/null; "
            "E=$(cut -d' ' -f1 /proc/uptime); R2=$(cat $RXF 2>/dev/null || echo 0); "
            'echo "$((R2-R1)) $S $E"'
        )
        res = client.run(cmd, timeout=_MEASURE_WINDOW + 20)
        try:
            b, s, e = res.stdout.strip().split()
            nbytes, elapsed = int(b), float(e) - float(s)
        except ValueError:
            last = (res.stderr or "").strip() or _("нет ответа")
            continue
        if nbytes > 1_000_000 and elapsed > 1.0:
            kbit = (nbytes * 8) / 1000.0 / elapsed
            # SQM wants a value just under the real line: subtract ~1.5 Mbit/s from
            # the measured rate (not a flat %), with a floor so slow links stay sane.
            down = max(int(kbit) - MEASURE_MARGIN_KBIT, 256)
            return down, int(down * UPLOAD_FRACTION)
        last = f"мало данных ({nbytes} Б за {elapsed:.1f} с)"
    raise RuntimeError(_("Не удалось измерить скорость — тест-серверы недоступны "
                       "(или у роутера нет прямого выхода в интернет). Введите значения вручную.")
                       + (f" [{last}]" if last else ""))


def _int(val: str | None, default: int) -> int:
    try:
        return int((val or "").strip())
    except (TypeError, ValueError):
        return default


def detected_wan(client: RouterClient) -> str:
    """Best guess at the WAN egress device (what SQM should shape)."""
    try:
        info = net.uplink_info(client)
        if info.device:
            return info.device
    except Exception:  # noqa: BLE001 — detection is best-effort
        pass
    return ""


def wan_candidates(client: RouterClient) -> list[str]:
    """Physical netdevs eligible as the SQM interface — excludes loopback, the
    LAN bridge, proxy TUNs and SQM's own ifb shaper devices."""
    out = client.run("ls /sys/class/net 2>/dev/null").stdout.split()
    skip = ("lo", "br-lan")
    bad_prefix = ("ifb", "sing", "tun", "tap", "wg", "awg")
    return [d for d in out if d not in skip and not d.startswith(bad_prefix)]


def get_settings(client: RouterClient) -> SqmSettings:
    if not is_installed(client):
        return SqmSettings(installed=False)
    exists = client.run(f"uci -q get {_REF} >/dev/null 2>&1 && echo y").stdout.strip() == "y"
    if not exists:
        return SqmSettings(installed=True, exists=False, interface=detected_wan(client))
    g = lambda opt: client.uci_get(f"{_REF}.{opt}")  # noqa: E731
    # The stock SQM section ships named "eth1" with interface='eth1' — correct only
    # on x86. On real routers the WAN device is eth0.2 / wan / pppoe-wan / wwan0…,
    # so trust the configured value ONLY if it's an actually-present device;
    # otherwise fall back to the detected WAN egress device.
    configured = g("interface") or ""
    present = wan_candidates(client)
    if configured and configured in present:
        iface = configured
    else:
        iface = detected_wan(client) or (present[0] if present else configured)
    return SqmSettings(
        installed=True, exists=True,
        enabled=(g("enabled") or "0") == "1",
        interface=iface,
        download=_int(g("download"), 0),
        upload=_int(g("upload"), 0),
        qdisc=g("qdisc") or "cake",
        script=g("script") or "piece_of_cake.qos",
        linklayer=g("linklayer") or "ethernet",
        overhead=_int(g("overhead"), 44))


def apply_settings(client: RouterClient, s: SqmSettings) -> None:
    """Write the queue section and (re)start / stop the SQM service."""
    if not s.interface:
        raise ValueError(_("Не выбран WAN-интерфейс."))
    if s.enabled and (s.download <= 0 or s.upload <= 0):
        raise ValueError(_("Укажите скорости приёма и отдачи (кбит/с) больше нуля."))
    cmds: list[str] = []
    if not s.exists:
        cmds.append("uci add sqm queue >/dev/null")
    fields = [
        ("interface", s.interface), ("download", str(s.download)),
        ("upload", str(s.upload)), ("qdisc", s.qdisc), ("script", s.script),
        ("linklayer", s.linklayer or "ethernet"), ("overhead", str(s.overhead)),
        ("enabled", "1" if s.enabled else "0"),
    ]
    for opt, val in fields:
        cmds.append(f"uci set {_REF}.{opt}={shlex.quote(val)}")
    cmds.append("uci commit sqm")
    client.run("; ".join(cmds)).check()
    if s.enabled:
        client.run("/etc/init.d/sqm enable 2>/dev/null; "
                   "/etc/init.d/sqm restart 2>/dev/null; true")
    else:
        client.run("/etc/init.d/sqm stop 2>/dev/null; "
                   "/etc/init.d/sqm disable 2>/dev/null; true")
