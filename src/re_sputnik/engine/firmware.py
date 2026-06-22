# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Firmware compatibility check — warn before things break.

HomeProxy relies on firewall4/nftables + nft-tproxy. Several OpenWrt-derived
firmwares ship configurations that quietly break that, so we probe for the known
offenders right after connecting and surface a clear warning (or a hard block)
instead of letting the user hit a confusing failure later:

  * Koshev builds — compiled WITHOUT nftables support → nft-tproxy can't exist
    (hard block: HomeProxy cannot work).
  * FriendlyWrt — br_netfilter routes bridge traffic through iptables, so
    nft-tproxy never sees the connections (warn + fix).
  * GL.iNet (v4.8.*-op24) — the built-in vpn-client service installs conflicting
    nftables marking rules, so traffic never reaches sing-box (warn + fix).

Detection is read-only; it never changes the device.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..router import RouterClient
from ..i18n import _, N_

BLOCK = "block"
WARN = "warn"


@dataclass(slots=True)
class CompatIssue:
    severity: str       # BLOCK | WARN
    title: str
    detail: str
    fix: str = ""       # optional remediation hint


@dataclass(slots=True)
class CompatReport:
    distro: str = "OpenWrt"
    issues: list[CompatIssue] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(i.severity == BLOCK for i in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == WARN for i in self.issues)


def _os_release(client: RouterClient) -> dict[str, str]:
    out = client.run("cat /etc/os-release 2>/dev/null").stdout
    data: dict[str, str] = {}
    for line in out.splitlines():
        if "=" in line:
            key, val = line.split("=", 1)
            data[key.strip()] = val.strip().strip('"').strip("'")
    return data


def check_compat(client: RouterClient) -> CompatReport:
    """Probe the router for known firmware incompatibilities. Read-only."""
    rep = CompatReport()
    osr = _os_release(client)
    name = osr.get("PRETTY_NAME") or osr.get("NAME") or "OpenWrt"
    rep.distro = name
    ident = f"{name} {osr.get('ID', '')} {osr.get('ID_LIKE', '')}".lower()

    # --- 1. nftables present at all (Koshev = built without it) → hard block ---
    has_nft = client.run("command -v nft >/dev/null 2>&1 && echo Y").stdout.strip() == "Y"
    if not has_nft:
        rep.issues.append(CompatIssue(
            BLOCK,
            _("Прошивка без поддержки nftables"),
            _("В прошивке нет nftables (команды nft). HomeProxy использует nft-tproxy "
            "и не сможет работать на этой сборке (например, некоторые кастомные сборки "
            "собраны без firewall4/nftables)."),
            _("Нужна прошивка OpenWrt с firewall4 (nftables).")))
    else:
        nft_ok = client.run("nft list ruleset >/dev/null 2>&1 && echo OK").stdout.strip() == "OK"
        if not nft_ok:
            rep.issues.append(CompatIssue(
                WARN,
                _("nftables не отвечает"),
                _("Команда nft есть, но «nft list ruleset» завершилась с ошибкой — "
                "возможно, активен firewall на iptables, а не firewall4."),
                _("Убедитесь, что используется firewall4 (nftables).")))

    # --- 1b. firewall4/fw4 present (nft without fw4 ≈ iptables firewall) -------
    if has_nft:
        has_fw4 = client.run("command -v fw4 >/dev/null 2>&1 && echo Y").stdout.strip() == "Y"
        if not has_fw4:
            rep.issues.append(CompatIssue(
                WARN,
                _("Похоже, firewall не на nftables"),
                _("nftables есть, но firewall4 (fw4) не найден — возможно, прошивка использует "
                "firewall на iptables. HomeProxy рассчитан на firewall4 и nft-tproxy."),
                _("Используйте прошивку OpenWrt с firewall4 (nftables).")))

    # --- 2. FriendlyWrt: br_netfilter sends bridge traffic via iptables --------
    is_friendly = "friendlywrt" in ident or "friendlyelec" in ident
    brnf_hit = client.run(
        "lsmod 2>/dev/null | grep -q '^br_netfilter' && "
        "[ \"$(cat /proc/sys/net/bridge/bridge-nf-call-iptables 2>/dev/null)\" = 1 ] && echo HIT"
    ).stdout.strip() == "HIT"
    if is_friendly or brnf_hit:
        rep.issues.append(CompatIssue(
            WARN,
            _("FriendlyWrt: br-netfilter ломает nft-tproxy"),
            _("Модуль br_netfilter направляет трафик моста через iptables, из-за чего "
            "nft-tproxy не перехватывает соединения и прокси не работает."),
            _("Отключите bridge-nf-call-iptables (sysctl) или выгрузите модуль br_netfilter.")))

    # --- 3. GL.iNet: built-in vpn-client adds conflicting nft marking ----------
    is_glinet = ("glinet" in ident or "gl.inet" in ident or "gl-inet" in ident
                 or client.run("[ -f /etc/glversion ] && echo Y").stdout.strip() == "Y")
    if is_glinet:
        glver = client.run("cat /etc/glversion 2>/dev/null").stdout.strip()
        if glver:
            rep.distro = f"GL.iNet {glver}"
        enabled = client.run(
            "[ -x /etc/init.d/vpn-client ] && /etc/init.d/vpn-client enabled 2>/dev/null && echo EN"
        ).stdout.strip() == "EN"
        rep.issues.append(CompatIssue(
            WARN,
            _("GL.iNet: конфликт правил маркировки трафика"),
            _("Встроенная служба vpn-client GL.iNet создаёт собственные правила маркировки "
            "в nftables, из-за чего трафик не доходит до sing-box")
            + (_(" (служба vpn-client сейчас включена).") if enabled else "."),
            _("Отключите GL.iNet VPN (vpn-client) перед использованием HomeProxy.")))

    return rep


# ----- kernel-module capability (checked at INSTALL time, has internet) -------
#
# These provide the kernel features the proxy needs. They're SUPPOSED to be
# absent on a clean router (we install them), so presence isn't checked at
# connect — only installability. If a "strangely built" firmware's kernel can't
# get them (no matching package for its kernel), that's a real incompatibility,
# not something an install can fix.
REQUIRED_KMODS = [
    ("nft_tproxy", "kmod-nft-tproxy", N_("перехват трафика (nft-tproxy)")),
    ("tun", "kmod-tun", N_("режим TUN")),
]


def _module_present(client: RouterClient, mod: str) -> bool:
    """True if the kernel module exists (loadable or built-in) — offline-safe."""
    return client.run(
        f"modprobe -n {mod} 2>/dev/null && echo Y || "
        f"([ -d /sys/module/{mod} ] && echo Y)"
    ).stdout.strip() == "Y"


def _pkg_available(client: RouterClient, pkg_manager: str, pkg: str) -> "bool | None":
    """Tri-state: True installable, False positively unavailable, None unknown.

    Conservative — only returns False when the repo positively reports the
    package as unknown, so a transient/network hiccup never masquerades as an
    incompatibility.
    """
    if pkg_manager == "apk":
        sim = client.run(f"apk add --simulate {pkg} 2>&1", timeout=60)
        if sim.ok:
            return True
        low = sim.stdout.lower()
        if "unable to select" in low or "not found" in low or "no such package" in low:
            return False
        lst = client.run(f"apk list {pkg} 2>/dev/null", timeout=60)
        return True if (lst.ok and pkg in lst.stdout) else None
    # opkg
    upd = client.run("opkg update >/dev/null 2>&1; echo $?", timeout=120)
    info = client.run(f"opkg info {pkg} 2>/dev/null", timeout=30)
    if f"Package: {pkg}" in info.stdout:
        return True
    lst = client.run(f"opkg list {pkg} 2>/dev/null", timeout=30)
    if lst.stdout.strip().startswith(pkg):
        return True
    # Only trust an "unavailable" verdict if the package lists refreshed cleanly.
    return False if upd.stdout.strip().endswith("0") else None


def diagnose_kmods(client: RouterClient, pkg_manager: str) -> str:
    """After a kmod install fails, explain WHY in firmware terms (or '' if unclear).

    Distinguishes 'this firmware's kernel can't get the module' (incompatible)
    from a plain install failure.
    """
    notes: list[str] = []
    for mod, pkg, label in REQUIRED_KMODS:
        if _module_present(client, mod):
            continue
        avail = _pkg_available(client, pkg_manager, pkg)
        if avail is False:
            notes.append(_("{0}: пакет {1} недоступен для ядра этой прошивки — прошивка несовместима").format(_(label), pkg))
        elif avail is None:
            notes.append(_("{0}: пакет {1} не установился").format(_(label), pkg))
    return "; ".join(notes)
