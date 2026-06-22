# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Router state detection.

The very first thing the app does after connecting is READ the router's state.
That state is an input signal: it decides which Quick-Setup phases to show or
skip, and it guarantees we never reinstall what is already there. Working with
an already-configured router is a first-class case, not an edge case.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Optional

from .client import RouterClient

# uci package / config presence marker for the homeproxy package.
HOMEPROXY_CONFIG = "/etc/config/homeproxy"


class PackageManager(enum.Enum):
    OPKG = "opkg"
    APK = "apk"
    UNKNOWN = "unknown"


class Readiness(enum.Enum):
    """How far along this router already is."""

    CLEAN = "clean"          # OpenWRT reachable, homeproxy not installed
    PARTIAL = "partial"      # homeproxy installed but not configured / no node
    CONFIGURED = "configured"  # homeproxy installed AND has a usable config


@dataclass(slots=True)
class RouterState:
    """A snapshot of what the router already has.

    Everything here is read-only discovery — no changes are made while detecting.
    """

    reachable: bool = False
    is_openwrt: bool = False
    openwrt_version: Optional[str] = None
    board: Optional[str] = None
    arch: Optional[str] = None

    package_manager: PackageManager = PackageManager.UNKNOWN
    homeproxy_installed: bool = False
    preferred_core: Optional[str] = None        # 'hiddify' / 'sing-box' / None
    has_config: bool = False                    # homeproxy has a main node set

    # Free space, in megabytes (overlay is the one that matters for big cores).
    free_tmp_mb: Optional[int] = None
    free_overlay_mb: Optional[int] = None

    our_key_installed: bool = False             # our SSH pubkey already authorized
    root_has_password: bool = False             # root already has a non-empty password
    notes: list[str] = field(default_factory=list)

    @property
    def readiness(self) -> Readiness:
        if not self.homeproxy_installed:
            return Readiness.CLEAN
        if self.has_config:
            return Readiness.CONFIGURED
        return Readiness.PARTIAL


def root_has_password(client: RouterClient) -> bool:
    """True if root already has a non-empty password in /etc/shadow.

    An empty field or a locked marker (``*``, ``!``, ``!!``) means no password.
    Used to AVOID overwriting a password the user already set.
    """
    res = client.run("awk -F: '$1==\"root\"{print $2}' /etc/shadow 2>/dev/null")
    if not res.ok:
        return False
    h = res.stdout.strip()
    return bool(h) and h not in ("*", "!", "!!")


def _first_int(text: str) -> Optional[int]:
    m = re.search(r"\d+", text)
    return int(m.group()) if m else None


def _avail_mb(client: RouterClient, mount: str) -> Optional[int]:
    """Available space at a mount point, in MB, via busybox df."""
    # -m = megabytes; column 4 is "Available" in busybox df output.
    res = client.run(f"df -m {mount} 2>/dev/null | awk 'NR==2 {{print $4}}'")
    if res.ok and res.stdout.strip():
        return _first_int(res.stdout)
    return None


def detect_state(client: RouterClient, *, our_public_key: Optional[str] = None) -> RouterState:
    """Probe the router and return a RouterState. Never mutates the device.

    Mirrors the dual-core selection used elsewhere: ``preferred_core`` is read
    from uci so the app and the router agree on which core is active.
    """
    st = RouterState(reachable=True)

    # OpenWRT identity.
    rel = client.run("cat /etc/openwrt_release 2>/dev/null")
    if rel.ok and "OpenWrt" in rel.stdout:
        st.is_openwrt = True
        ver = re.search(r"DISTRIB_RELEASE='([^']+)'", rel.stdout)
        if ver:
            st.openwrt_version = ver.group(1)
    board = client.run("cat /tmp/sysinfo/board_name 2>/dev/null")
    if board.ok:
        st.board = board.stdout.strip() or None

    # Package manager — apk on newer images, opkg on 23.05 and earlier.
    if client.run("command -v apk >/dev/null 2>&1").ok:
        st.package_manager = PackageManager.APK
    elif client.run("command -v opkg >/dev/null 2>&1").ok:
        st.package_manager = PackageManager.OPKG

    # Architecture (from the package manager's own view, falls back to uname).
    arch = client.run(
        "opkg print-architecture 2>/dev/null | awk '$3>1{print $2}' | tail -1"
    )
    if arch.ok and arch.stdout.strip():
        st.arch = arch.stdout.strip()
    else:
        uname = client.run("uname -m")
        st.arch = uname.stdout.strip() or None if uname.ok else None

    # homeproxy presence + config.
    st.homeproxy_installed = client.run(f"test -f {HOMEPROXY_CONFIG}").ok
    if st.homeproxy_installed:
        st.preferred_core = client.uci_get("homeproxy.config.preferred_core") or None
        main_node = client.uci_get("homeproxy.config.main_node")
        st.has_config = bool(main_node) and main_node not in ("", "nil")

    # Does root already have a password? (so we never overwrite it)
    st.root_has_password = root_has_password(client)

    # Free space.
    st.free_tmp_mb = _avail_mb(client, "/tmp")
    st.free_overlay_mb = _avail_mb(client, "/overlay")

    # Is our SSH key already trusted?
    if our_public_key:
        from .client import AUTHORIZED_KEYS_PATH
        import shlex

        st.our_key_installed = client.run(
            f"grep -qF {shlex.quote(our_public_key.strip())} {AUTHORIZED_KEYS_PATH} 2>/dev/null"
        ).ok

    if st.free_overlay_mb is not None and st.free_overlay_mb < 10:
        st.notes.append("low overlay space — large cores may not fit")

    return st
