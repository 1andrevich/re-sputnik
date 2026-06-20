# SPDX-License-Identifier: GPL-2.0-only
"""Overview / dashboard data — system stats and the Wi-Fi join QR payload.

System figures (hostname, model, uptime, CPU %, RAM %, LAN IP) come from a single
``/proc`` read over SSH so the page paints from one round-trip. The CPU figure is
a short two-sample delta of ``/proc/stat`` (busybox-safe). The Wi-Fi QR uses the
standard ``WIFI:`` payload that Android/iOS cameras understand.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Optional

from ..router import RouterClient


@dataclass(slots=True)
class SystemInfo:
    hostname: str = ""
    model: str = ""
    uptime_s: int = 0
    cpu_pct: int = 0
    mem_pct: int = 0
    mem_used_mb: int = 0
    mem_total_mb: int = 0
    lan_ip: str = ""


# One busybox-sh script: read /proc once, sample /proc/stat twice for a live CPU%.
_SYS_CMD = r"""
H=$(cat /proc/sys/kernel/hostname 2>/dev/null)
M=$(cat /tmp/sysinfo/model 2>/dev/null)
U=$(cut -d. -f1 /proc/uptime 2>/dev/null)
LAN=$(uci -q get network.lan.ipaddr)
MT=$(awk '/^MemTotal:/{print $2}' /proc/meminfo 2>/dev/null)
MA=$(awk '/^MemAvailable:/{print $2}' /proc/meminfo 2>/dev/null)
[ -z "$MA" ] && MA=$(awk '/^MemFree:/{print $2}' /proc/meminfo 2>/dev/null)
# CPU% — prefer busybox top's own idle figure (already computed, no sleep);
# fall back to a /proc/stat 2-sample only if top's idle line can't be parsed.
ID=$(top -bn1 2>/dev/null | awk '/[0-9]% *idle/{for(j=1;j<=NF;j++){if($j=="idle"){v=$(j-1);gsub(/%/,"",v);print v;exit}}}')
if [ -n "$ID" ]; then
	CPU=$((100-ID))
else
	read _ u n s i io r1 r2 r3 < /proc/stat; t1=$((u+n+s+i+io+r1+r2+r3)); d1=$((i+io))
	sleep 1
	read _ u n s i io r1 r2 r3 < /proc/stat; t2=$((u+n+s+i+io+r1+r2+r3)); d2=$((i+io))
	DT=$((t2-t1)); DD=$((d2-d1)); CPU=0
	[ "$DT" -gt 0 ] && CPU=$(( (100*(DT-DD))/DT ))
fi
printf 'host\t%s\n' "$H"
printf 'model\t%s\n' "$M"
printf 'uptime\t%s\n' "$U"
printf 'lan\t%s\n' "$LAN"
printf 'memtotal\t%s\n' "$MT"
printf 'memavail\t%s\n' "$MA"
printf 'cpu\t%s\n' "$CPU"
"""


def system_info(client: RouterClient) -> SystemInfo:
    """One-shot system stats for the overview header (best-effort, never raises)."""
    info = SystemInfo(lan_ip=client.host)
    res = client.run(_SYS_CMD, timeout=15)
    if not res.ok:
        return info
    vals: dict[str, str] = {}
    for line in res.stdout.splitlines():
        if "\t" in line:
            k, v = line.split("\t", 1)
            vals[k] = v.strip()

    def _int(key: str) -> int:
        try:
            return int(vals.get(key, "") or 0)
        except ValueError:
            return 0

    info.hostname = vals.get("host", "") or client.host
    info.model = vals.get("model", "")
    info.uptime_s = _int("uptime")
    info.lan_ip = vals.get("lan", "") or client.host
    info.cpu_pct = max(0, min(100, _int("cpu")))
    mt, ma = _int("memtotal"), _int("memavail")
    if mt > 0:
        used = max(0, mt - ma)
        info.mem_pct = max(0, min(100, round(100 * used / mt)))
        info.mem_total_mb = round(mt / 1024)
        info.mem_used_mb = round(used / 1024)
    return info


# RFC-1123 label: letters/digits/hyphen, no leading/trailing hyphen, ≤63 chars.
_HOSTNAME_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def set_hostname(client: RouterClient, name: str) -> str:
    """Rename the router (system hostname). Mirrors the SETUP_AGENT recipe:
    uci set + commit + `/etc/init.d/system reload` to apply it live. Validates the
    name (a space or '/' would otherwise produce an invalid hostname). Returns the
    applied name; raises ValueError on a bad name."""
    name = name.strip()
    if not _HOSTNAME_RE.match(name):
        raise ValueError("Имя: латинские буквы, цифры и дефис, без пробелов (1–63 символа).")
    client.run(
        f"uci set system.@system[0].hostname={shlex.quote(name)}; "
        "uci commit system; /etc/init.d/system reload",
        timeout=30,
    )
    return name


def format_uptime(seconds: int) -> str:
    """Human uptime: ``3д 4ч 5м`` (drops leading zero units)."""
    if seconds <= 0:
        return "—"
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    parts = []
    if d:
        parts.append(f"{d}д")
    if h:
        parts.append(f"{h}ч")
    if m or not parts:
        parts.append(f"{m}м")
    return " ".join(parts)


# ----- Wi-Fi join QR ----------------------------------------------------

# encryption tokens (uci 'encryption' option) that mean "has a passphrase".
_PSK_ENC = ("psk", "sae", "wpa", "owe")


def _qr_escape(value: str) -> str:
    """Escape the special characters of the WIFI: payload grammar."""
    out = []
    for ch in value:
        if ch in "\\;,:\"":
            out.append("\\")
        out.append(ch)
    return "".join(out)


def wifi_qr_payload(ssid: str, key: str, encryption: str, hidden: bool = False) -> str:
    """Standard ``WIFI:`` join string understood by phone cameras."""
    enc = (encryption or "").lower()
    has_pass = bool(key) and any(tok in enc for tok in _PSK_ENC) and "none" not in enc
    auth = "WPA" if has_pass else "nopass"
    payload = f"WIFI:T:{auth};S:{_qr_escape(ssid)};"
    if has_pass:
        payload += f"P:{_qr_escape(key)};"
    if hidden:
        payload += "H:true;"
    return payload + ";"


def wifi_qr_image(payload: str, *, box_size: int = 5, border: int = 2):
    """Render a WIFI payload to a PIL image (off the Tk thread). Returns None if the
    qrcode lib is unavailable, so the caller can fall back to plain text."""
    try:
        import qrcode  # lazy: missing dep degrades to text, never crashes the page

        qr = qrcode.QRCode(box_size=box_size, border=border,
                           error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(payload)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").get_image()
    except Exception:  # noqa: BLE001 — QR is a nicety, not worth a crash
        return None
