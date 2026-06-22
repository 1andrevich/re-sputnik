# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Final housekeeping tweaks offered at the end of setup.

Small, optional system settings that aren't homeproxy-specific:
  * the LuCI "Check online for firmware upgrades" login check
    (attendedsysupgrade.client.login_check_for_upgrades);
  * an optional zram-swap install (recommended on low-RAM devices).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..router import RouterClient
from ..i18n import N_

ASU_CHECK_OPT = "login_check_for_upgrades"


# ----- firmware upgrade login check -------------------------------------


def _client_ref(client: RouterClient) -> Optional[str]:
    """Resolve the attendedsysupgrade 'client' section reference.

    It may be a NAMED section (``attendedsysupgrade.client``) or an ANONYMOUS one
    (``attendedsysupgrade.@client[0]``) depending on how the package shipped its
    config. The earlier code only checked the named form, so on images with an
    anonymous section every get/set silently no-op'd — which is why the toggle
    "didn't apply". Try both.
    """
    for ref in ("attendedsysupgrade.client", "attendedsysupgrade.@client[0]"):
        if client.run(f"uci -q get {ref}").ok:
            return ref
    return None


def asu_available(client: RouterClient) -> bool:
    """Is the attendedsysupgrade client config present (package installed)?"""
    return _client_ref(client) is not None


def get_check_for_upgrades(client: RouterClient) -> Optional[bool]:
    """Current setting, or None if attendedsysupgrade isn't installed."""
    ref = _client_ref(client)
    if ref is None:
        return None
    return client.uci_get(f"{ref}.{ASU_CHECK_OPT}") == "1"


def set_check_for_upgrades(client: RouterClient, on: bool) -> bool:
    """Enable/disable the login-page firmware-upgrade online check."""
    ref = _client_ref(client)
    if ref is None:
        return False
    client.uci_set(f"{ref}.{ASU_CHECK_OPT}", "1" if on else "0")
    client.uci_commit("attendedsysupgrade")
    return True


# ----- zram swap --------------------------------------------------------


@dataclass(slots=True)
class ZramStatus:
    installed: bool
    active: bool


def zram_status(client: RouterClient) -> ZramStatus:
    installed = client.run(
        "apk info 2>/dev/null | grep -qx zram-swap && echo y || "
        "{ opkg list-installed 2>/dev/null | grep -q '^zram-swap ' && echo y; }"
    ).stdout.strip() == "y"
    active = client.run("grep -qi zram /proc/swaps && echo y").stdout.strip() == "y"
    return ZramStatus(installed=installed, active=active)


def install_zram(client: RouterClient) -> ZramStatus:
    """Install + enable zram-swap (online). Returns the resulting status."""
    pm_apk = client.run("command -v apk >/dev/null 2>&1").ok
    add = "apk add zram-swap" if pm_apk else "opkg update >/dev/null 2>&1; opkg install zram-swap"
    client.run(f"{add} >/dev/null 2>&1; true", timeout=120)
    # The package ships /etc/init.d/zram; enable + start so swap is set up now.
    client.run("/etc/init.d/zram enable 2>/dev/null; /etc/init.d/zram start 2>/dev/null; true",
               timeout=30)
    return zram_status(client)


# ----- optional LuCI apps (UPnP, SQM) -----------------------------------

# (package, title, one-line description) — installed on demand from the feed,
# each with its ru language pack.
OPTIONAL_APPS: list[tuple[str, str, str]] = [
    ("luci-app-upnp", N_("UPnP / NAT-PMP — автопроброс портов"),
     N_("Позволяет приставкам, играм, торрент-клиентам и видеозвонкам самим открывать "
        "нужные порты — без ручной настройки проброса. Удобно, но любое приложение в сети "
        "сможет открыть порт наружу, поэтому включайте, если это действительно нужно.")),
    ("luci-app-sqm", N_("SQM — умная очередь (борьба с лагами)"),
     N_("Не даёт каналу «захлёбываться», когда кто-то качает или раздаёт большой трафик: "
        "пинг остаётся низким. Заметно улучшает игры и видеозвонки во время загрузок "
        "(устраняет буфер-блоат).")),
]


def _pm_add(client: RouterClient) -> tuple[str, str]:
    """(update-cmd, install-cmd-prefix) for the device's package manager."""
    if client.run("command -v apk >/dev/null 2>&1").ok:
        return "apk update >/dev/null 2>&1; true", "apk add"
    return "opkg update >/dev/null 2>&1; true", "opkg install"


def app_installed(client: RouterClient, pkg: str) -> bool:
    return client.run(
        f"apk info 2>/dev/null | grep -qx {pkg} && echo y || "
        f"{{ opkg list-installed 2>/dev/null | grep -q '^{pkg} ' && echo y; }}"
    ).stdout.strip() == "y"


def install_luci_app(client: RouterClient, pkg: str, language: str = "ru") -> bool:
    """Install a LuCI app from the feed plus its language pack (best-effort).
    Returns True if the app ended up installed."""
    update, add = _pm_add(client)
    client.run(update, timeout=120)
    client.run(f"{add} {pkg} >/dev/null 2>&1; true", timeout=120)
    if language and language != "en":
        i18n = pkg.replace("luci-app-", "luci-i18n-") + f"-{language}"
        client.run(f"{add} {i18n} >/dev/null 2>&1; true", timeout=90)
    return app_installed(client, pkg)


# ----- new-device privacy / locale defaults -----------------------------
# Small hardening applied during guided setup so a fresh router doesn't out
# itself to the ISP (device name in DHCP, OpenWrt NTP pool). All reversible.

_RU_NTP = [f"{i}.ru.pool.ntp.org" for i in range(4)]
_OPENWRT_NTP = [f"{i}.openwrt.pool.ntp.org" for i in range(4)]


def dhcp_hostname_hidden(client: RouterClient) -> bool:
    """True if the WAN DHCP client is set to send NO hostname (option '*')."""
    return (client.uci_get("network.wan.hostname") or "") == "*"


def set_dhcp_hostname_hidden(client: RouterClient, hidden: bool) -> None:
    """Hide ('*' = send nothing) or restore the DHCP-request hostname on the WAN
    interfaces, so the device model/name isn't leaked to the ISP. Commits but does
    NOT reload the network (takes effect on the next lease — keeps us connected)."""
    touched = False
    for iface in ("wan", "wan6"):
        if not client.run(f"uci -q get network.{iface}").ok:
            continue
        touched = True
        if hidden:
            client.run(f"uci set network.{iface}.hostname='*'")
        else:
            client.run(f"uci -q delete network.{iface}.hostname")
    if touched:
        client.uci_commit("network")


def _ntp_section(client: RouterClient) -> Optional[str]:
    """The timeserver section to edit (named 'ntp', else the first anonymous one)."""
    if client.run("uci -q get system.ntp").ok:
        return "system.ntp"
    if client.run("uci -q get system.@timeserver[0]").ok:
        return "system.@timeserver[0]"
    return None


def ntp_is_ru(client: RouterClient) -> bool:
    sec = _ntp_section(client)
    if sec is None:
        return False
    return any("ru.pool.ntp.org" in s for s in client.uci_get_list(f"{sec}.server"))


def set_ru_ntp(client: RouterClient, ru: bool) -> None:
    """Point NTP at the RU pool (so the device doesn't out itself as OpenWrt via
    *.openwrt.pool.ntp.org), or restore the OpenWrt pool."""
    sec = _ntp_section(client)
    if sec is None:
        return
    client.run(f"uci -q delete {sec}.server")
    for s in (_RU_NTP if ru else _OPENWRT_NTP):
        client.uci_add_list(f"{sec}.server", s)
    client.uci_commit("system")
    client.run("/etc/init.d/sysntpd restart >/dev/null 2>&1; true")
