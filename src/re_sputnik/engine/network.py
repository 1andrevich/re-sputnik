# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Router internet/uplink setup — initial network configuration (not homeproxy).

This is the "make the router reach the internet" piece, needed before any
package install. Two uplinks: a wired WAN (DHCP on the WAN port) or a Wi-Fi
client (STA) joining the user's home network. Mirrors the stock OpenWrt
wireless.sta / wwan pattern observed on a working device.
"""

from __future__ import annotations

import ipaddress
import json
import re
import shlex
from dataclasses import dataclass, field

from ..router import RouterClient
from ..i18n import _


@dataclass(slots=True)
class WanInfo:
    proto: str
    device: str
    up: bool
    carrier: bool  # is a cable physically plugged into the WAN port?


@dataclass(slots=True)
class Radio:
    name: str       # e.g. radio0
    band: str       # 2g / 5g / 6g
    disabled: bool


@dataclass(slots=True)
class WifiNetwork:
    ssid: str
    band: str        # "2.4" / "5" / "6" (GHz, as iwinfo reports)
    signal: int      # dBm (higher = closer to 0 = stronger)
    encryption: str  # human label from iwinfo, e.g. "WPA2 PSK (CCMP)" or "none"
    open: bool       # no passphrase needed
    uci_encryption: str  # value for wireless.<iface>.encryption: none/psk2/sae


def _uci_encryption(enc: str) -> tuple[str, bool]:
    """Map iwinfo's encryption text to a (uci value, is_open) pair."""
    low = enc.lower()
    if "none" in low or low in ("", "open"):
        return "none", True
    # WPA3-only networks need SAE; mixed WPA2/WPA3 (PSK + SAE) joins fine as psk2.
    if "sae" in low and "psk" not in low:
        return "sae", False
    return "psk2", False


def _band_to_radio_band(band: str) -> str:
    """iwinfo band ("2.4"/"5"/"6") -> uci wifi-device band ("2g"/"5g"/"6g")."""
    return {"2.4": "2g", "5": "5g", "6": "6g"}.get(band, "")


def band_label(band: str) -> str:
    """Human, compact band name. Accepts either uci ("2g"/"5g"/"6g") or iwinfo
    ("2.4"/"5"/"6") forms → "2,4G" / "5G" / "6G" (Russian decimal comma)."""
    return {"2g": "2,4G", "5g": "5G", "6g": "6G",
            "2.4": "2,4G", "5": "5G", "6": "6G"}.get(band, band)


def format_bands(bands: list[str]) -> str:
    """"Диапазоны 2,4G, 5G, 6G" for a list of bands (empty string if none)."""
    labels = [band_label(b) for b in bands if b and b != "?"]
    return (_("Диапазоны ") + ", ".join(labels)) if labels else ""


def check_internet(client: RouterClient) -> bool:
    """True if the router itself can reach the internet (direct, not via proxy).

    Two probes, because either alone gives false negatives:
      * ICMP ping to two anycast IPs — survives a single dropped packet;
      * an HTTP fallback (Cloudflare's captive-portal 204 endpoint) for the many
        uplinks that silently filter outbound ICMP but pass real traffic — the
        case where the link is clearly up (lease + default route) yet ping fails.
    Either one succeeding means the router has internet.
    """
    cmd = (
        'ok=; for ip in 1.1.1.1 8.8.8.8; do '
        'ping -c1 -W2 "$ip" >/dev/null 2>&1 && { ok=1; break; }; done; '
        '[ -z "$ok" ] && wget -q -T5 -O /dev/null http://cp.cloudflare.com/ 2>/dev/null && ok=1; '
        '[ -n "$ok" ] && echo OK'
    )
    r = client.run(cmd)
    return "OK" in r.stdout


def wait_for_internet(client: RouterClient, timeout: int = 25, interval: int = 2) -> bool:
    """Poll check_internet until it succeeds or ``timeout`` seconds elapse.

    A freshly-(re)configured uplink needs time to come up: after a ``wifi reload``
    the STA re-associates (~3 s) and only then does DHCP obtain a lease + default
    route. A single ping at a fixed delay races that and falsely reports failure,
    so we retry until the link is actually ready (returning as soon as it is)."""
    import time

    deadline = time.monotonic() + timeout
    while True:
        if check_internet(client):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


# ----- live uplink status (for the Overview card) -----------------------


@dataclass(slots=True)
class UplinkInfo:
    present: bool = False
    iface: str = ""            # logical interface (wan / wwan / …)
    kind: str = ""             # "wired" | "wifi"
    proto: str = ""            # dhcp / pppoe / static / …
    device: str = ""           # l3 device (eth1, wlan0, …)
    ip: str = ""               # IPv4 address
    up: bool = False
    internet: bool = False     # uplink can reach the internet (green/red dot)
    link_speed_mbps: int = 0   # wired link speed
    wifi_ssid: str = ""
    wifi_band: str = ""        # "2.4" / "5" / "6"
    wifi_rate_mbps: int = 0
    wifi_signal_dbm: int = 0


def link_speed_label(mbps: int) -> str:
    """1000 → '1 Гбит/с', 2500 → '2.5 Гбит/с', 100 → '100 Мбит/с'."""
    if mbps <= 0:
        return ""
    if mbps >= 1000:
        return _("{0} Гбит/с").format(f"{mbps / 1000:g}")
    return _("{0} Мбит/с").format(mbps)


def uplink_info(client: RouterClient) -> UplinkInfo:
    """The active internet uplink (the real WAN/WWAN, not the proxy TUN): type,
    link speed / Wi-Fi band+rate, IP, protocol, and whether it has internet.

    Picks the logical interface that is up and carries the default route (ignoring
    tun/sing-box/bridge devices), then reads link speed + iwinfo + a device-bound
    ping. Best-effort — never raises; an empty/partial result just shows less."""
    info = UplinkInfo()
    out = client.run("ubus call network.interface dump 2>/dev/null", timeout=15).stdout
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return info
    best: "tuple[int, dict] | None" = None
    for iface in data.get("interface", []):
        name = iface.get("interface", "")
        if not iface.get("up") or name in ("loopback", "lan", "lan6"):
            continue
        l3 = iface.get("l3_device", "") or iface.get("device", "")
        if not l3 or l3.startswith(("tun", "sing", "lo", "br-lan")):
            continue
        has_def = any(r.get("target") == "0.0.0.0" and r.get("mask") == 0
                      for r in iface.get("route", []))
        score = ((4 if has_def else 0) + (2 if name.startswith("wan") else 0)
                 + (1 if name.startswith("wwan") else 0))
        if best is None or score > best[0]:
            best = (score, iface)
    if best is None:
        return info
    iface = best[1]
    info.present = True
    info.iface = iface.get("interface", "")
    info.proto = iface.get("proto", "")
    info.device = iface.get("l3_device", "") or iface.get("device", "")
    info.up = bool(iface.get("up"))
    addrs = iface.get("ipv4-address") or []
    if addrs:
        info.ip = addrs[0].get("address", "")
    if not info.device:
        return info

    cmd = (
        'D={d}; '
        'if [ -d /sys/class/net/"$D"/wireless ] || [ -d /sys/class/net/"$D"/phy80211 ]; '
        'then echo "KIND wifi"; else echo "KIND wired"; fi; '
        'echo "SPEED $(cat /sys/class/net/"$D"/speed 2>/dev/null)"; '
        'if ping -I "$D" -c1 -W1 1.1.1.1 >/dev/null 2>&1 || ping -c1 -W1 1.1.1.1 >/dev/null 2>&1; '
        'then echo "NET ok"; else echo "NET no"; fi; '
        'echo IWINFO; iwinfo "$D" info 2>/dev/null'
    ).format(d=shlex.quote(info.device))
    res = client.run(cmd, timeout=12)
    iw_lines: list[str] = []
    in_iw = False
    for line in res.stdout.splitlines():
        if in_iw:
            iw_lines.append(line)
            continue
        s = line.strip()
        if s.startswith("KIND "):
            info.kind = s.split(None, 1)[1]
        elif s.startswith("SPEED "):
            v = s[6:].strip()
            if v.lstrip("-").isdigit() and int(v) > 0:
                info.link_speed_mbps = int(v)
        elif s.startswith("NET "):
            info.internet = s.split(None, 1)[1] == "ok"
        elif s == "IWINFO":
            in_iw = True
    if info.kind == "wifi" and iw_lines:
        iw = "\n".join(iw_lines)
        m = re.search(r'ESSID:\s*"([^"]*)"', iw)
        if m:
            info.wifi_ssid = m.group(1)
        m = re.search(r'Signal:\s*(-?\d+)\s*dBm', iw)
        if m:
            info.wifi_signal_dbm = int(m.group(1))
        m = re.search(r'Bit Rate:\s*([\d.]+)\s*MBit/s', iw)
        if m:
            info.wifi_rate_mbps = int(float(m.group(1)))
        m = re.search(r'\(([\d.]+)\s*GHz\)', iw)
        if m:
            ghz = float(m.group(1))
            info.wifi_band = "2.4" if ghz < 3 else ("5" if ghz < 5.9 else "6")
    return info


def wan_info(client: RouterClient) -> WanInfo:
    """WAN interface state + whether a cable is plugged (carrier)."""
    proto = client.uci_get("network.wan.proto") or "dhcp"
    dev = client.uci_get("network.wan.device") or "wan"
    up = client.run("ubus call network.interface.wan status 2>/dev/null | grep -q '\"up\": true'").ok
    carrier = False
    for cand in (dev, "wan", "eth1", "eth0"):
        res = client.run(f"cat /sys/class/net/{shlex.quote(cand)}/carrier 2>/dev/null")
        if res.ok and res.stdout.strip() in ("0", "1"):
            carrier = res.stdout.strip() == "1"
            break
    return WanInfo(proto=proto, device=dev, up=up, carrier=carrier)


# ----- LAN / WAN subnet conflict (double-NAT) ---------------------------


@dataclass(slots=True)
class SubnetConflict:
    wan_ip: str
    wan_subnet: str       # e.g. "192.168.1.0/24"
    lan_ip: str           # current router LAN address (what the app connects to)
    lan_subnet: str
    suggested_lan_ip: str  # a free LAN address that doesn't overlap WAN


# LAN candidates to move to, in order — first one not inside the WAN subnet wins.
_LAN_CANDIDATES = ("192.168.10.1", "192.168.20.1", "192.168.30.1",
                   "10.0.10.1", "172.16.10.1", "192.168.88.1")


def _pick_free_lan_ip(wan_net: "ipaddress.IPv4Network") -> str:
    for cand in _LAN_CANDIDATES:
        if ipaddress.ip_address(cand) not in wan_net:
            return cand
    return "192.168.10.1"


def detect_subnet_conflict(client: RouterClient) -> "SubnetConflict | None":
    """Detect the double-NAT trap: the upstream ISP router handed the WAN an address
    in the SAME subnet the router uses for LAN (classically both 192.168.1.0/24).
    Then LAN and WAN are the same 'directly connected' network and routing breaks
    (the default gateway equals the router's own LAN IP). Returns the conflict (with
    a suggested free LAN address) or None."""
    out = client.run("ubus call network.interface.wan status 2>/dev/null").stdout
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return None
    addrs = data.get("ipv4-address") or []
    if not addrs:
        return None  # WAN has no IPv4 lease (no uplink yet) — nothing to compare
    wan_ip, wan_mask = addrs[0].get("address"), addrs[0].get("mask")
    lan_ip = client.uci_get("network.lan.ipaddr")
    lan_mask = client.uci_get("network.lan.netmask") or "255.255.255.0"
    if not (wan_ip and wan_mask is not None and lan_ip):
        return None
    try:
        wan_net = ipaddress.ip_network(f"{wan_ip}/{wan_mask}", strict=False)
        lan_net = ipaddress.ip_network(f"{lan_ip}/{lan_mask}", strict=False)
    except ValueError:
        return None
    if not wan_net.overlaps(lan_net):
        return None
    return SubnetConflict(
        wan_ip=wan_ip, wan_subnet=str(wan_net), lan_ip=lan_ip,
        lan_subnet=str(lan_net), suggested_lan_ip=_pick_free_lan_ip(wan_net))


def validate_new_lan_ip(new_ip: str, wan_subnet: str) -> "str | None":
    """Idiot-proofing for a user-chosen LAN address. Returns an error message, or
    None if the address is a sane choice that actually resolves the conflict."""
    try:
        ip = ipaddress.ip_address(new_ip.strip())
    except ValueError:
        return _("Неверный IP-адрес.")
    if ip.version != 4:
        return _("Нужен адрес IPv4.")
    if not ip.is_private:
        return _("Используйте частный адрес (192.168.x.x, 10.x.x.x или 172.16–31.x.x).")
    if int(str(ip).split(".")[-1]) in (0, 255):
        return _("Это адрес сети/широковещания — выберите хост .1–.254.")
    try:
        wan_net = ipaddress.ip_network(wan_subnet, strict=False)
        new_net = ipaddress.ip_network(f"{ip}/24", strict=False)
        if new_net.overlaps(wan_net):
            return _("Подсеть пересекается с сетью провайдера — конфликт останется. Выберите другую.")
    except ValueError:
        pass
    return None


def change_lan_ip(client: RouterClient, new_ip: str, netmask: str = "255.255.255.0") -> str:
    """Move the router's LAN to ``new_ip``. Reloads the network in the BACKGROUND
    (after a short delay) so this SSH command returns BEFORE the address changes and
    drops our own connection — the caller must then reconnect at ``new_ip``. Returns
    the new IP; raises ValueError on a malformed address."""
    new_ip = new_ip.strip()
    try:
        ipaddress.ip_address(new_ip)
    except ValueError as exc:
        raise ValueError(f"неверный IP-адрес: {new_ip}") from exc
    # Apply + commit immediately, then reload network + dnsmasq detached so the live
    # connection survives long enough for this call to return cleanly.
    client.run(
        f"uci set network.lan.ipaddr={shlex.quote(new_ip)}; "
        f"uci set network.lan.netmask={shlex.quote(netmask)}; "
        "uci commit network; "
        "(sleep 2; /etc/init.d/network reload; /etc/init.d/dnsmasq reload) "
        ">/dev/null 2>&1 &",
        timeout=15)
    return new_ip


def list_radios(client: RouterClient) -> list[Radio]:
    radios: list[Radio] = []
    res = client.run("uci show wireless | grep '=wifi-device'")
    if res.ok:
        for line in res.stdout.splitlines():
            name = line.split(".")[1].split("=")[0] if "." in line else ""
            if not name:
                continue
            band = client.uci_get(f"wireless.{name}.band") or "?"
            disabled = client.uci_get(f"wireless.{name}.disabled") == "1"
            radios.append(Radio(name=name, band=band, disabled=disabled))
    return radios


def scan_networks(client: RouterClient) -> list[WifiNetwork]:
    """Scan for nearby Wi-Fi via OpenWrt, across every radio (2.4/5/6 GHz).

    The radios are disabled by default on a fresh router and have no netdev, so
    for each phy we add a throwaway station interface, bring it up, scan with
    iwinfo (which already parses ESSID/Band/Signal/Encryption), then remove it.
    Networks are merged by SSID keeping the strongest signal; hidden SSIDs are
    dropped (can't be joined from a list).
    """
    phys = client.run("ls /sys/class/ieee80211/ 2>/dev/null").stdout.split()
    best: dict[str, WifiNetwork] = {}
    for i, phy in enumerate(phys):
        dev = f"rescan{i}"
        cmd = (f"iw phy {shlex.quote(phy)} interface add {dev} type station 2>/dev/null; "
               f"ip link set {dev} up 2>/dev/null; sleep 2; "
               f"iwinfo {dev} scan 2>/dev/null; "
               f"ip link set {dev} down 2>/dev/null; iw dev {dev} del 2>/dev/null")
        out = client.run(cmd, timeout=30).stdout
        for cell in re.split(r"\nCell \d+", out):
            m = re.search(r'ESSID:\s*"([^"]*)"', cell)
            if not m or not m.group(1):
                continue  # hidden / unnamed
            ssid = m.group(1)
            band_m = re.search(r"Band:\s*([\d.]+)\s*GHz", cell)
            sig_m = re.search(r"Signal:\s*(-?\d+)\s*dBm", cell)
            enc_m = re.search(r"Encryption:\s*(.+)", cell)
            band = band_m.group(1) if band_m else "?"
            signal = int(sig_m.group(1)) if sig_m else -999
            enc = enc_m.group(1).strip() if enc_m else "none"
            uci_enc, is_open = _uci_encryption(enc)
            prev = best.get(ssid)
            if prev is None or signal > prev.signal:
                best[ssid] = WifiNetwork(ssid=ssid, band=band, signal=signal,
                                         encryption=enc, open=is_open, uci_encryption=uci_enc)
    return sorted(best.values(), key=lambda n: n.signal, reverse=True)


def radio_for_band(radios: list[Radio], band: str) -> str:
    """Pick the wifi-device whose band matches a scanned network's band."""
    want = _band_to_radio_band(band)
    for r in radios:
        if r.band == want:
            return r.name
    return radios[0].name if radios else "radio0"


# Wired WAN protocols offered in the UI (uci proto value, human label, needs).
WAN_PROTOCOLS: list[tuple[str, str]] = [
    ("dhcp", "DHCP — получить адрес автоматически"),
    ("pppoe", "PPPoE — логин и пароль от провайдера"),
    ("static", "Статический IP — адрес вручную"),
    ("dhcpv6", "DHCPv6 — автоматически (IPv6)"),
]


def configure_wan(client: RouterClient, *, proto: str = "dhcp", username: str = "",
                  password: str = "", ipaddr: str = "", netmask: str = "255.255.255.0",
                  gateway: str = "", dns: str = "", wait: int = 8) -> bool:
    """Configure the wired WAN with the chosen protocol; True if internet follows.

    DHCP just asks for an address; PPPoE needs ISP credentials; Static needs an
    address/gateway. Stale options from a previous protocol are cleared first so
    e.g. leftover pppoe creds don't linger when switching back to DHCP.
    """
    cmds = [f"uci set network.wan.proto={shlex.quote(proto)}"]
    for opt in ("username", "password", "ipaddr", "netmask", "gateway", "dns"):
        # '-q' silences the message but NOT the exit code: deleting an absent
        # option still returns 1, and as the last command in a ';'-joined chain
        # that fails the whole .check() ("command failed exit 1") on a clean WAN
        # that has nothing to delete. Swallow each delete's status.
        cmds.append(f"uci -q delete network.wan.{opt} || true")
    if proto == "pppoe":
        cmds.append(f"uci set network.wan.username={shlex.quote(username)}")
        cmds.append(f"uci set network.wan.password={shlex.quote(password)}")
    elif proto == "static":
        cmds.append(f"uci set network.wan.ipaddr={shlex.quote(ipaddr)}")
        cmds.append(f"uci set network.wan.netmask={shlex.quote(netmask or '255.255.255.0')}")
        if gateway:
            cmds.append(f"uci set network.wan.gateway={shlex.quote(gateway)}")
        if dns:
            for srv in dns.split():
                cmds.append(f"uci add_list network.wan.dns={shlex.quote(srv)}")
    client.run("; ".join(cmds)).check()
    client.uci_commit("network")
    client.run("ifup wan")
    # DHCP/PPPoE negotiation isn't instant; poll rather than ping once at a fixed
    # delay (which can race the lease and falsely report "no internet").
    return wait_for_internet(client, timeout=max(wait + 12, 20))


@dataclass(slots=True)
class ApStatus:
    ssid: str            # current AP SSID ("" if none enabled)
    bands: list[str]     # radio bands currently broadcasting it


def ap_status(client: RouterClient) -> ApStatus:
    """Current home-AP SSID + the bands it runs on (mode=ap, enabled ifaces)."""
    ssid = ""
    bands: list[str] = []
    res = client.run("uci show wireless 2>/dev/null")
    if res.ok:
        ifaces = {}
        for line in res.stdout.splitlines():
            # wireless.<sec>.<opt>='val'
            if "=" not in line or "." not in line:
                continue
            path, val = line.split("=", 1)
            val = val.strip("'")
            parts = path.split(".")
            if len(parts) == 3:
                ifaces.setdefault(parts[1], {})[parts[2]] = val
        for sec, opt in ifaces.items():
            if opt.get("mode") == "ap" and opt.get("disabled", "0") != "1" and opt.get("ssid"):
                ssid = opt["ssid"]
                dev = opt.get("device", "")
                band = next((b for r, b in [(rr.name, rr.band) for rr in list_radios(client)]
                             if r == dev), "?")
                bands.append(band)
    return ApStatus(ssid=ssid, bands=bands)


@dataclass(slots=True)
class ApCred:
    ssid: str
    key: str
    encryption: str   # uci 'encryption' value (none/psk2/sae/…)
    band: str
    hidden: bool


def ap_credentials(client: RouterClient) -> list[ApCred]:
    """Enabled home-AP networks with their passphrase — for the Wi-Fi join QR.

    One entry per SSID (deduplicated across bands, keeping the first). The key is
    read straight from uci; an open network has an empty key.
    """
    res = client.run("uci show wireless 2>/dev/null")
    if not res.ok:
        return []
    ifaces: dict[str, dict[str, str]] = {}
    for line in res.stdout.splitlines():
        if "=" not in line or "." not in line:
            continue
        path, val = line.split("=", 1)
        val = val.strip("'")
        parts = path.split(".")
        if len(parts) == 3:
            ifaces.setdefault(parts[1], {})[parts[2]] = val
    radio_band = {rr.name: rr.band for rr in list_radios(client)}
    creds: list[ApCred] = []
    seen: set[str] = set()
    for opt in ifaces.values():
        if opt.get("mode") != "ap" or opt.get("disabled", "0") == "1" or not opt.get("ssid"):
            continue
        ssid = opt["ssid"]
        if ssid in seen:
            continue
        seen.add(ssid)
        creds.append(ApCred(
            ssid=ssid,
            key=opt.get("key", ""),
            encryption=opt.get("encryption", ""),
            band=radio_band.get(opt.get("device", ""), "?"),
            hidden=opt.get("hidden", "0") == "1",
        ))
    return creds


# ----- per-radio Wi-Fi editing (Advanced screen) ------------------------


def _wifi_ifaces(client: RouterClient) -> dict[str, dict[str, str]]:
    """Parse ``uci show wireless`` into {section: {option: value}}."""
    ifaces: dict[str, dict[str, str]] = {}
    res = client.run("uci show wireless 2>/dev/null")
    if res.ok:
        for line in res.stdout.splitlines():
            if "=" not in line or "." not in line:
                continue
            path, val = line.split("=", 1)
            val = val.strip("'")
            parts = path.split(".")
            if len(parts) == 3:
                ifaces.setdefault(parts[1], {})[parts[2]] = val
    return ifaces


def _ap_iface_for_radio(client: RouterClient, radio: str) -> str:
    """Section name of the existing AP wifi-iface bound to ``radio`` (or "")."""
    for sec, opt in _wifi_ifaces(client).items():
        if opt.get("device") == radio and opt.get("mode") == "ap":
            return sec
    return ""


def wifi_channel_options(band: str) -> list[str]:
    """FALLBACK channel choices when the radio's real list can't be read (radio
    down / no iwinfo). The authoritative list comes from radio_supported_channels;
    this is only a safety net. "auto" lets the driver pick a valid channel."""
    if band == "2g":
        return ["auto", "1", "6", "11"]
    if band == "5g":
        return ["auto", "36", "40", "44", "48", "132", "136", "140"]
    return ["auto"]  # 6 GHz: let the driver choose


def _radio_ifname_map(client: RouterClient) -> dict[str, str]:
    """{radio_name: l2 ifname} from ``ubus call network.wireless status`` — the
    interface name iwinfo needs to report a radio's channels."""
    out = client.run("ubus call network.wireless status 2>/dev/null", timeout=15).stdout
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return {}
    m: dict[str, str] = {}
    for radio, info in data.items():
        if not isinstance(info, dict):
            continue
        for iface in info.get("interfaces") or []:
            ifn = iface.get("ifname")
            if ifn:
                m[radio] = ifn
                break
    return m


def radio_supported_channels(client: RouterClient, ifname: str) -> list[str]:
    """The radio's REAL channel list via iwinfo — the same source LuCI uses, so a
    tri-band's two 5 GHz radios report their actual (different) sub-bands instead
    of a hardcoded guess.

    Tries TWO independent methods before giving up, so a single quirk (a build
    without the ubus ``iwinfo`` object, or vice-versa) never falsely reports an
    empty list and marks a working radio unconfigurable: (A) ``ubus call iwinfo
    freqlist`` (JSON, what LuCI uses), then (B) the ``iwinfo <dev> freqlist``
    text output. Returns sorted channel numbers as strings; empty ONLY when both
    genuinely return nothing (radio down / no such interface)."""
    if not ifname:
        return []
    chans: set[int] = set()
    # (A) ubus iwinfo — structured, preferred.
    arg = json.dumps({"device": ifname})
    out = client.run(f"ubus call iwinfo freqlist {shlex.quote(arg)} 2>/dev/null",
                     timeout=15).stdout
    try:
        data = json.loads(out)
        for r in data.get("results", []):
            ch = r.get("channel")
            if ch:
                chans.add(int(ch))
    except (json.JSONDecodeError, ValueError):
        pass
    # (B) text iwinfo — fallback for builds without the ubus iwinfo object.
    if not chans:
        out2 = client.run(f"iwinfo {shlex.quote(ifname)} freqlist 2>/dev/null",
                          timeout=15).stdout
        for m in re.findall(r"Channel\s+(\d+)", out2):
            chans.add(int(m))
    return [str(c) for c in sorted(chans)]


def radio_htmodes(client: RouterClient, ifname: str) -> list[str]:
    """The radio's supported HT/VHT/HE/EHT modes via iwinfo (same source LuCI uses
    for its width dropdown). Two methods before giving up. Empty if unavailable."""
    if not ifname:
        return []
    modes: list[str] = []
    arg = json.dumps({"device": ifname})
    out = client.run(f"ubus call iwinfo info {shlex.quote(arg)} 2>/dev/null",
                     timeout=15).stdout
    try:
        data = json.loads(out)
        hm = data.get("htmodes")
        if isinstance(hm, list):
            modes = [str(x) for x in hm]
    except (json.JSONDecodeError, ValueError):
        pass
    if not modes:  # text fallback (iwinfo <dev> htmodelist)
        out2 = client.run(f"iwinfo {shlex.quote(ifname)} htmodelist 2>/dev/null",
                          timeout=15).stdout
        modes = re.findall(r"\b(?:HT|VHT|HE|EHT)\d+\b", out2)
    return modes


_HTMODE_GEN = {"HT": 1, "VHT": 2, "HE": 3, "EHT": 4}


def channel_width_options(htmodes: list[str]) -> list[tuple[str, str]]:
    """Collapse htmodes (HT20/VHT80/HE160/…) to selectable channel WIDTHS, each
    mapped to the best uci htmode the radio supports for that width (newest
    generation wins: EHT > HE > VHT > HT). Returns [(label, htmode), …] ascending
    by width — e.g. [("20 МГц","HE20"), ("40 МГц","HE40"), ("80 МГц","HE80")]."""
    best: dict[int, tuple[int, str]] = {}  # width -> (gen_rank, htmode)
    for hm in htmodes:
        m = re.match(r"(HT|VHT|HE|EHT)(\d+)$", hm)
        if not m:
            continue
        rank = _HTMODE_GEN[m.group(1)]
        w = int(m.group(2))
        if w not in best or rank > best[w][0]:
            best[w] = (rank, hm)
    return [(f"{w} МГц", best[w][1]) for w in sorted(best)]


def normalize_encryption(enc: str) -> str:
    """Collapse a uci encryption value to one of none/psk2/sae-mixed/sae."""
    low = (enc or "").lower()
    if low in ("", "none", "open"):
        return "none"
    # WPA2/WPA3 mixed: the uci value is "sae-mixed" (has "sae", NOT "psk"), so
    # detecting mixed by "psk" alone wrongly collapsed it to pure WPA3 "sae".
    if "sae" in low and ("mixed" in low or "psk" in low):
        return "sae-mixed"
    if "sae" in low:
        return "sae"
    return "psk2"


@dataclass(slots=True)
class RadioWifi:
    radio: str          # radio0
    band: str           # 2g / 5g / 6g
    radio_disabled: bool
    up: bool            # actually broadcasting right now
    is_sta: bool        # this radio is the Wi-Fi uplink (can't be an AP)
    iface: str          # AP wifi-iface section ("" if none yet)
    ssid: str
    key: str
    encryption: str     # raw uci value
    channel: str        # 'auto' or a number
    channels: list[str] = field(default_factory=list)  # dropdown choices (incl. 'auto')
    htmode: str = ""    # current uci htmode (HT20/VHT80/HE160/…)
    widths: list = field(default_factory=list)  # [(label, htmode), …] real, polled


def list_radio_wifi(client: RouterClient) -> list[RadioWifi]:
    """Per-radio AP Wi-Fi state for the Advanced editor: SSID/key/encryption/
    channel plus enabled/broadcasting status and the radio's REAL channel list.
    Excludes nothing — a radio used as the STA uplink is flagged (``is_sta``) so
    the UI can show it read-only."""
    ifaces = _wifi_ifaces(client)
    # A radio is the Wi-Fi uplink if ANY iface on it is in client mode — not just
    # a section literally named "sta". OpenWrt names STA ifaces variously (sta,
    # wwan, default_radioN…); keying on the name alone misses them and the radio
    # then falls through to the "channel list unavailable" warning. Detect by mode.
    sta_radios = {
        opt.get("device")
        for opt in ifaces.values()
        if opt.get("mode") in ("sta", "mesh", "adhoc") and opt.get("device")
    }
    named_sta = client.uci_get("wireless.sta.device")
    if named_sta:
        sta_radios.add(named_sta)
    up = _radios_up(client)
    ifname_map = _radio_ifname_map(client)
    out: list[RadioWifi] = []
    for r in list_radios(client):
        ap_opt: dict[str, str] = {}
        ap_sec = ""
        for sec, opt in ifaces.items():
            if opt.get("device") == r.name and opt.get("mode") == "ap":
                ap_sec, ap_opt = sec, opt
                break
        channel = client.uci_get(f"wireless.{r.name}.channel") or "auto"
        is_sta = (r.name in sta_radios)
        radio_up = up.get(r.name, not r.disabled)
        ap_disabled = ap_opt.get("disabled") == "1"
        # "Broadcasting" means an AP iface is actually up — not merely that the
        # wifi-DEVICE is enabled. A radio whose only AP iface is disabled (or which
        # has none) is NOT broadcasting, even if the device itself is up. STA radios
        # keep the device-up flag (they're a live client, not an AP).
        broadcasting = radio_up and bool(ap_sec) and not ap_disabled
        # Real per-radio channel list (iwinfo, like LuCI). iwinfo needs an UP netdev,
        # so a radio whose AP is disabled (no netdev, e.g. radio0/radio2 here) reports
        # nothing. Reading the phy (iw phy) doesn't help either: before the regdomain
        # is set the phy marks most 5 GHz channels "disabled", leaving a DFS-only list.
        # So when the real list is unavailable but the device is enabled, fall back to
        # the curated RU-safe per-band set — keeping the radio configurable instead of
        # showing the "unavailable" warning. (configure_ap sets country=RU on save.)
        ifname = ifname_map.get(r.name, "")
        real = radio_supported_channels(client, ifname)
        if real:
            channels = ["auto"] + real
        elif not r.disabled:
            channels = wifi_channel_options(r.band)
        else:
            channels = []
        htmode = client.uci_get(f"wireless.{r.name}.htmode") or ""
        widths = channel_width_options(radio_htmodes(client, ifname))
        out.append(RadioWifi(
            radio=r.name, band=r.band, radio_disabled=r.disabled,
            up=(radio_up if is_sta else broadcasting), is_sta=is_sta,
            iface=ap_sec, ssid=ap_opt.get("ssid", ""), key=ap_opt.get("key", ""),
            encryption=ap_opt.get("encryption", ""), channel=channel, channels=channels,
            htmode=htmode, widths=widths))
    return out


def set_radio_wifi(client: RouterClient, radio: str, *, ssid: str, key: str,
                   encryption: str, channel: str, htmode: str = "",
                   country: str = "RU") -> bool:
    """Update one radio's AP network (SSID/key/encryption/channel) and reload.

    Creates the AP wifi-iface if the radio had none. ``country`` is (re)set — a
    ``00`` regdomain blocks the radio. Returns whether the radio came up after
    reload (best-effort; ``True`` if the status probe is empty on older builds)."""
    ssid = ssid.strip()
    if not ssid:
        raise ValueError(_("Введите имя сети (SSID)."))
    enc = normalize_encryption(encryption)
    if enc != "none":
        if not key:
            raise ValueError(_("Для защищённой сети нужен пароль."))
        if len(key) < 8:
            raise ValueError(_("Пароль должен быть не короче 8 символов."))
    iface = _ap_iface_for_radio(client, radio) or f"default_{radio}"
    cmd = (
        f"uci set wireless.{iface}=wifi-iface; "
        f"uci set wireless.{iface}.device={shlex.quote(radio)}; "
        f"uci set wireless.{iface}.mode=ap; uci set wireless.{iface}.network=lan; "
        f"uci set wireless.{iface}.ssid={shlex.quote(ssid)}; "
    )
    if enc == "none":
        cmd += (f"uci set wireless.{iface}.encryption=none; "
                f"uci -q delete wireless.{iface}.key; ")
    else:
        cmd += (f"uci set wireless.{iface}.encryption={shlex.quote(enc)}; "
                f"uci set wireless.{iface}.key={shlex.quote(key)}; ")
    cmd += f"uci set wireless.{iface}.disabled=0; "
    if channel:
        cmd += f"uci set wireless.{shlex.quote(radio)}.channel={shlex.quote(channel)}; "
    if htmode:
        cmd += f"uci set wireless.{shlex.quote(radio)}.htmode={shlex.quote(htmode)}; "
    cmd += (
        f"uci set wireless.{shlex.quote(radio)}.country={shlex.quote(country)}; "
        f"uci set wireless.{shlex.quote(radio)}.disabled=0; "
        "uci commit wireless"
    )
    client.run(cmd).check()
    client.run("wifi reload")
    import time

    time.sleep(5)
    up = _radios_up(client)
    return up.get(radio, True)


@dataclass(slots=True)
class ApResult:
    enabled: list[str]   # bands now actually broadcasting (radio came up)
    failed: list[str]    # bands we configured but whose radio didn't come up


def _radios_up(client: RouterClient) -> dict[str, bool]:
    """{radio_name: is_up} from ``ubus call network.wireless status`` — the
    authoritative post-reload view of which radios actually came online."""
    out = client.run("ubus call network.wireless status 2>/dev/null", timeout=15).stdout
    try:
        data = json.loads(out)
    except (json.JSONDecodeError, ValueError):
        return {}
    return {name: bool(info.get("up")) for name, info in data.items()
            if isinstance(info, dict)}


def configure_ap(client: RouterClient, *, ssid: str, key: str, country: str = "RU") -> ApResult:
    """Set up the router's own Wi-Fi access point (home network for devices).

    Configures one SSID across every radio EXCEPT the one used for a Wi-Fi STA
    uplink (a radio can't sanely be both client and AP on the same band). 6 GHz is
    attempted automatically and transparently — we set the regdomain (``country``)
    which is what 6 GHz needs, then VERIFY which radios actually came up and report
    any that didn't (typically 6 GHz on builds with an outdated wireless-regdb), so
    the caller can tell the user instead of silently dropping the band.

    Sets ``country`` on every radio: a regdomain of ``00`` makes hostapd refuse to
    start ("Invalid country_code '00'"), so the AP silently never comes up — which
    is exactly what bit the 5 GHz (and 2.4 GHz) radios before this.
    """
    ssid = ssid.strip()
    if not ssid:
        raise ValueError("empty SSID")
    if key and len(key) < 8:
        raise ValueError("Wi-Fi password must be at least 8 characters")
    sta_radio = client.uci_get("wireless.sta.device")  # None if no STA uplink
    configured: list[tuple[str, str]] = []  # (radio_name, band)
    # Channel: clear any stale/fixed 5 GHz channel and let each radio's own driver
    # pick a valid one (ACS / 'auto'). A FIXED channel is dangerous on 5 GHz —
    # a value that's wrong for THIS radio's sub-band, or a DFS channel disallowed
    # under the applied regdomain, makes hostapd refuse to start and the AP
    # silently dies. This bit tri-band HARD: the two 5 GHz radios cover DIFFERENT
    # sub-bands (one ~36–64, the other ~100–165), so a channel valid for one kills
    # the other. 'auto' can never select an unsupported channel, so it can't kill
    # the radio. Fine-grained per-radio channel pinning lives in the Advanced
    # editor, which reads each radio's REAL channel list (radio_supported_channels).
    for r in list_radios(client):
        if r.name == sta_radio:
            continue
        iface = f"default_{r.name}"
        chan_cmd = ""
        if r.band == "5g":
            chan_cmd = f"uci set wireless.{shlex.quote(r.name)}.channel=auto; "
        client.run(
            f"uci set wireless.{iface}=wifi-iface; "
            f"uci set wireless.{iface}.device={shlex.quote(r.name)}; "
            f"uci set wireless.{iface}.mode=ap; uci set wireless.{iface}.network=lan; "
            + f"uci set wireless.{iface}.ssid={shlex.quote(ssid)}; "
            + (f"uci set wireless.{iface}.encryption=psk2; "
               f"uci set wireless.{iface}.key={shlex.quote(key)}; " if key
               else f"uci set wireless.{iface}.encryption=none; ")
            + f"uci set wireless.{iface}.disabled=0; "
            + chan_cmd
            + f"uci set wireless.{shlex.quote(r.name)}.country={shlex.quote(country)}; "
            f"uci set wireless.{shlex.quote(r.name)}.disabled=0"
        ).check()
        configured.append((r.name, r.band))
    client.run("uci commit wireless; wifi reload")

    # Poll which radios actually came up. hostapd bring-up isn't instant and varies
    # a LOT by radio: an embedded 2.4 GHz radio (HE20 on IPQ807x) or one doing ACS
    # can take well over 6 s — a single fixed wait then falsely reported it "failed"
    # while it was still coming up. So poll up to ~25 s, breaking as soon as every
    # configured radio is up. A genuinely stuck band (e.g. 6 GHz on an outdated
    # wireless-regdb) never comes up and is still caught at the deadline. If the
    # status probe yields nothing (older builds), assume success.
    import time

    names = {name for name, _ in configured}
    up: dict[str, bool] = {}
    deadline = time.monotonic() + 25
    while True:
        time.sleep(3)
        up = _radios_up(client)
        if not up or all(up.get(n) for n in names) or time.monotonic() >= deadline:
            break

    enabled: list[str] = []
    failed: list[str] = []
    for name, band in configured:
        if up and name in up and not up[name]:
            failed.append(band)
        else:
            enabled.append(band)
    return ApResult(enabled=enabled, failed=failed)


def configure_wifi_sta(client: RouterClient, *, ssid: str, key: str, radio: str,
                       encryption: str = "psk2", country: str = "RU") -> bool:
    """Join a home Wi-Fi as a client (STA) for a temporary uplink.

    Mirrors the stock wireless.sta + network.wwan pattern, and adds wwan to the
    'wan' firewall zone so it routes/NATs. ``encryption`` is the uci value
    (none/psk2/sae) picked from the scanned network. ``country`` is set on the
    radio too — a ``00`` regdomain blocks the radio from coming up.
    """
    ssid = ssid.strip()
    if not ssid:
        raise ValueError("empty SSID")
    open_net = encryption == "none" or not key

    # Wi-Fi client interface on the chosen radio, attached to the wwan network.
    client.run(
        "uci set wireless.sta=wifi-iface; "
        f"uci set wireless.sta.device={shlex.quote(radio)}; "
        "uci set wireless.sta.mode=sta; "
        "uci set wireless.sta.network=wwan; "
        f"uci set wireless.sta.ssid={shlex.quote(ssid)}; "
        + ("uci set wireless.sta.encryption=none; " if open_net else
           f"uci set wireless.sta.encryption={shlex.quote(encryption)}; "
           f"uci set wireless.sta.key={shlex.quote(key)}; ")
        + "uci set wireless.sta.disabled=0; "
        f"uci set wireless.{shlex.quote(radio)}.country={shlex.quote(country)}; "
        f"uci set wireless.{shlex.quote(radio)}.disabled=0"
    ).check()

    # DHCP client network for the uplink.
    client.run(
        "uci set network.wwan=interface; uci set network.wwan.proto=dhcp"
    ).check()

    # Put wwan into the 'wan' firewall zone so the uplink is forwarded/masqueraded.
    # Zones are anonymous sections (firewall.@zone[N]); find the one named 'wan'
    # by index — a sed on `uci show` misses it because the section id is @zone[N].
    client.run(
        'z=""; i=0; while [ $i -lt 30 ]; do '
        'n=$(uci -q get firewall.@zone[$i].name) || break; '
        '[ "$n" = "wan" ] && { z="@zone[$i]"; break; }; i=$((i+1)); done; '
        '[ -n "$z" ] && uci add_list firewall.$z.network=\'wwan\' 2>/dev/null; true'
    )
    client.run("uci commit wireless; uci commit network; uci commit firewall")
    client.run("wifi reload; /etc/init.d/network reload")
    # Re-association (~3 s) + DHCP lease + default route take a variable moment;
    # poll instead of a single fixed-delay ping that races the bring-up.
    return wait_for_internet(client, timeout=25)
