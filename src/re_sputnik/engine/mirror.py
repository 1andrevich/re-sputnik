# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Optional GitHub release mirror (see ../../../mirror/).

Some ISPs throttle github.com / its asset CDN to a trickle, so router-side
downloads of release assets crawl and time out. When ``MIRROR_BASE`` is set to a
deployed Cloudflare Worker host, ``download_candidates(url)`` puts the mirror
FIRST and the original GitHub URL second, so callers try the fast path and fall
back to GitHub automatically. Empty ``MIRROR_BASE`` = mirror off (original
behaviour, GitHub direct)."""

from __future__ import annotations

import re

# Deployed Worker host (custom domain preferred — *.workers.dev is often RKN-blocked).
# Empty string disables the mirror entirely. See mirror/README.md.
MIRROR_BASE = "https://resputnik-mirror.plex-stream-server.workers.dev"

# Only these repos are mirrored (must match the Worker's ALLOW set).
_MIRRORED = frozenset({
    "1andrevich/homeproxy-hiddify",
    "1andrevich/hiddify-core",
    "1andrevich/zapret2-openwrt",
    "1andrevich/ByeDPI-OpenWrt",
    "shtorm-7/sing-box-extended",
})

_GH_RELEASE = re.compile(r"^https://github\.com/([^/]+/[^/]+)/releases/(.+)$")


def mirror_url(url: str) -> str | None:
    """Mirror equivalent of a GitHub *release* URL, or ``None`` if not mirrorable
    (mirror disabled, non-GitHub host, or a repo we don't proxy)."""
    if not MIRROR_BASE:
        return None
    m = _GH_RELEASE.match(url)
    if not m or m.group(1) not in _MIRRORED:
        return None
    return f"{MIRROR_BASE.rstrip('/')}/{m.group(1)}/releases/{m.group(2)}"


# Session latch: once the .pub throttle-probe (see install_app) finds GitHub
# throttled, every subsequent mirrorable download goes mirror-FIRST for the rest of
# this install. Off by default → GitHub-first, so a healthy GitHub never touches the
# mirror. Reset at the start of each install/update flow.
_session_mirror = False


def set_session_mirror(on: bool) -> None:
    global _session_mirror
    _session_mirror = bool(on)


def reset_session_mirror() -> None:
    global _session_mirror
    _session_mirror = False


def session_uses_mirror() -> bool:
    return _session_mirror


def download_candidates(url: str) -> list[str]:
    """Ordered URLs to try for ``url``. After the probe latches the session to the
    mirror, mirrorable URLs go mirror-FIRST (GitHub kept only as last resort);
    otherwise GitHub-first with the mirror as a fallback. Non-mirrorable URLs
    (non-GitHub, or a repo we don't proxy) are returned unchanged."""
    mu = mirror_url(url)
    if not mu:
        return [url]
    return [mu, url] if _session_mirror else [url, mu]
