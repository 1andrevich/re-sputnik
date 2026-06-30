# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Find and identify candidate routers on the local network.

A naive "default gateway = the router" assumption is wrong: a PC can have
several interfaces (e.g. a Mikrotik on the default route AND an OpenWRT box on a
second NIC that is *not* the default route). So we:

1. Enumerate EVERY local IPv4 interface and propose the ``.1`` of each subnet.
2. Add the OS default gateway(s) and the OpenWRT default ``192.168.1.1``.
3. Probe each candidate's SSH banner to identify it — OpenWRT's Dropbear says
   ``dropbear``; Mikrotik says ``ROSSSH``; others are generic. Identified
   OpenWRT candidates are ranked first and pre-selected by the UI.

Banner identification is a fast pre-check; final confirmation happens after
login via ``detect_state`` reading ``/etc/openwrt_release``.
"""

from __future__ import annotations

import enum
import ipaddress
import os
import re
import socket
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

# Fresh OpenWRT default — always included as a guaranteed candidate.
OPENWRT_DEFAULT = "192.168.1.1"
SSH_PORT = 22
_PROBE_TIMEOUT = 1.2


class Identity(enum.Enum):
    OPENWRT = "openwrt"            # Dropbear banner — very likely our target
    OTHER_ROUTER = "other_router"  # known non-OpenWRT (e.g. Mikrotik/ROSSSH)
    SSH_OPEN = "ssh_open"          # SSH answered but banner is generic
    UNREACHABLE = "unreachable"    # no SSH on :22

    @property
    def rank(self) -> int:
        return {
            Identity.OPENWRT: 0,
            Identity.SSH_OPEN: 1,
            Identity.OTHER_ROUTER: 2,
            Identity.UNREACHABLE: 3,
        }[self]


@dataclass(slots=True)
class Candidate:
    ip: str
    port: int = SSH_PORT
    identity: Identity = Identity.UNREACHABLE
    banner: str = ""
    hostname: str = ""  # best-effort, from a pre-login PTR query to the host's own DNS

    @property
    def is_openwrt(self) -> bool:
        return self.identity is Identity.OPENWRT

    @property
    def label(self) -> str:
        tag = {
            Identity.OPENWRT: "OpenWrt",
            Identity.OTHER_ROUTER: "другой роутер",
            Identity.SSH_OPEN: "SSH открыт",
            Identity.UNREACHABLE: "нет ответа",
        }[self.identity]
        head = f"{self.hostname} · {self.ip}" if self.hostname else self.ip
        return f"{head} — {tag}"


# ----- local interface / gateway enumeration ---------------------------


def _primary_local_ip() -> str | None:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _interfaces() -> list[tuple[str, str]]:
    """All local (ipv4, netmask) pairs across every interface."""
    pairs: list[tuple[str, str]] = []
    if sys.platform.startswith("win"):
        text = _run(["ipconfig"])
        # Pair each "IPv4 Address ... : X" with the following "Subnet Mask ... : Y".
        last_ip: str | None = None
        for line in text.splitlines():
            mip = re.search(r"IPv4 Address[ .]*:\s*([0-9.]+)", line)
            if mip:
                last_ip = mip.group(1)
                continue
            mmask = re.search(r"Subnet Mask[ .]*:\s*([0-9.]+)", line)
            if mmask and last_ip:
                pairs.append((last_ip, mmask.group(1)))
                last_ip = None
    elif sys.platform == "darwin":
        text = _run(["ifconfig"])
        for m in re.finditer(r"inet ([0-9.]+) netmask (0x[0-9a-fA-F]+)", text):
            mask = str(ipaddress.IPv4Address(int(m.group(2), 16)))
            pairs.append((m.group(1), mask))
    else:  # linux
        text = _run(["ip", "-4", "-o", "addr", "show"])
        for m in re.finditer(r"inet ([0-9.]+)/(\d+)", text):
            net = ipaddress.IPv4Network(f"0.0.0.0/{m.group(2)}")
            pairs.append((m.group(1), str(net.netmask)))
    return pairs


def _route_gateways() -> list[str]:
    out = _run(["ipconfig"]) if sys.platform.startswith("win") else ""
    gws: list[str] = []
    if out:
        for m in re.finditer(r"(?im)^\s*Default Gateway[ .]*:\s*([0-9.]+)\s*$", out):
            gws.append(m.group(1))
    elif sys.platform == "darwin":
        m = re.search(r"gateway:\s*([0-9.]+)", _run(["route", "-n", "get", "default"]))
        if m:
            gws.append(m.group(1))
    else:
        for m in re.finditer(r"default via ([0-9.]+)", _run(["ip", "route"])):
            gws.append(m.group(1))
    return [g for g in gws if g != "0.0.0.0"]


def _candidate_ips() -> list[str]:
    """Collect candidate router IPs from every subnet + gateways + default."""
    ips: list[str] = []

    def add(ip: str) -> None:
        try:
            addr = ipaddress.IPv4Address(ip)
        except ValueError:
            return
        if str(addr) not in ips and not addr.is_loopback and not addr.is_link_local:
            ips.append(str(addr))

    # The ".1" of each interface subnet — this is where a second-NIC OpenWRT hides.
    for ip, mask in _interfaces():
        try:
            net = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
        except ValueError:
            continue
        if net.num_addresses >= 4:  # skip /31, /32 oddities
            add(str(net.network_address + 1))

    for gw in _route_gateways():
        add(gw)

    add(OPENWRT_DEFAULT)
    return ips


# ----- identity probing -------------------------------------------------


def _read_dns_name(data: bytes, off: int) -> tuple[str, int]:
    """Read a (possibly compressed) DNS name; return (name, offset_after)."""
    labels: list[str] = []
    jumped = False
    after = off
    while off < len(data):
        length = data[off]
        if length & 0xC0 == 0xC0:  # compression pointer
            if off + 1 >= len(data):
                break
            ptr = ((length & 0x3F) << 8) | data[off + 1]
            if not jumped:
                after = off + 2
            off = ptr
            jumped = True
            continue
        if length == 0:
            off += 1
            if not jumped:
                after = off
            break
        labels.append(data[off + 1 : off + 1 + length].decode("latin-1", "replace"))
        off += 1 + length
    return ".".join(labels), after


def _query_ptr(ip: str, timeout: float = 1.0) -> str:
    """Ask the host ITSELF (its dnsmasq) for its reverse name.

    Most reliable pre-login hostname trick for OpenWRT — the router usually
    knows its own name, while the PC's configured resolver does not. Best
    effort: any failure returns "".
    """
    octets = ip.split(".")
    if len(octets) != 4:
        return ""
    qname = ".".join(reversed(octets)) + ".in-addr.arpa"
    header = os.urandom(2) + b"\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00"
    question = b""
    for label in qname.split("."):
        question += bytes([len(label)]) + label.encode("ascii")
    question += b"\x00" + struct.pack(">HH", 12, 1)  # QTYPE=PTR, QCLASS=IN
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(header + question, (ip, 53))
            data, _ = s.recvfrom(512)
    except OSError:
        return ""
    if len(data) < 12:
        return ""
    qd, an = struct.unpack(">HH", data[4:8])
    if an < 1:
        return ""
    off = 12
    for _ in range(qd):  # skip questions
        _, off = _read_dns_name(data, off)
        off += 4
    for _ in range(an):  # walk answers, return first PTR name
        _, off = _read_dns_name(data, off)
        if off + 10 > len(data):
            break
        rtype, _rclass, _ttl, rdlen = struct.unpack(">HHIH", data[off : off + 10])
        off += 10
        if rtype == 12:  # PTR
            name, _ = _read_dns_name(data, off)
            return name.rstrip(".")
        off += rdlen
    return ""


def _probe(ip: str, port: int = SSH_PORT, timeout: float = _PROBE_TIMEOUT) -> Candidate:
    """TCP-connect to :22 and read the SSH banner to classify the host."""
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            try:
                banner = sock.recv(128).decode("latin-1", "replace").strip()
            except OSError:
                banner = ""
    except OSError:
        return Candidate(ip, port, Identity.UNREACHABLE)

    low = banner.lower()
    if "dropbear" in low:
        identity = Identity.OPENWRT
    elif "rosssh" in low or "mikrotik" in low or "routeros" in low:
        identity = Identity.OTHER_ROUTER
    else:
        identity = Identity.SSH_OPEN
    # Reachable host → best-effort hostname from its own DNS (pre-login).
    hostname = _query_ptr(ip, timeout=min(timeout, 1.0))
    return Candidate(ip, port, identity, banner, hostname)


def discover_routers() -> list[Candidate]:
    """Enumerate + probe candidates; OpenWRT-identified ones ranked first."""
    ips = _candidate_ips()
    with ThreadPoolExecutor(max_workers=min(8, len(ips) or 1)) as pool:
        results = list(pool.map(_probe, ips))
    # Stable sort by identity rank (OpenWRT first), preserving discovery order.
    results.sort(key=lambda c: c.identity.rank)
    return results


def best_guess() -> Candidate | None:
    """The single most-likely OpenWRT router, or the best reachable candidate."""
    cands = discover_routers()
    return cands[0] if cands else None
