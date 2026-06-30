# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Optional GitHub release mirror(s) (see ../../../mirror/).

Some ISPs throttle github.com / its asset CDN to a trickle, so router-side
downloads of release assets crawl and time out. When one or more mirror hosts are
configured, ``download_candidates(url)`` interleaves them with the original GitHub
URL — GitHub-first by default, mirror-first once the throttle-probe latches the
session — so callers get the fast path with automatic fallback. No mirrors
configured = GitHub direct (original behaviour)."""

from __future__ import annotations

import os
import re

# Mirror host(s), tried in order (see download_candidates) — a LIST so the program
# can fall back across MULTIPLE mirrors if one lapses or is blocked. SINGLE source of
# truth: the URL-rewrite and the router-side uci value both derive from here.
#
# Add resilience by appending more hosts below (e.g. a custom domain), or set the
# RS_MIRROR_BASE env var to a comma-separated list to override at runtime WITHOUT a
# rebuild. An empty value disables the mirror entirely. Only the PRIMARY (first) host
# is handed to the router — its gh_fetch supports a single mirror. See mirror/README.md.
_DEFAULT_MIRROR_BASES = (
    "https://resputnik-mirror.plex-stream-server.workers.dev",
    # add fallback mirror hosts here for resilience, e.g.:
    # "https://mirror.example.org",
)


def _load_mirror_bases() -> list[str]:
    """The configured mirror hosts, normalized (trailing slash stripped, blanks
    dropped). RS_MIRROR_BASE overrides the built-in list — comma-separated for
    several, empty to disable."""
    raw = os.environ.get("RS_MIRROR_BASE")
    items = raw.split(",") if raw is not None else _DEFAULT_MIRROR_BASES
    return [s.strip().rstrip("/") for s in items if s.strip()]


# Full fallback list the PC tries (in order). MIRROR_BASE = the PRIMARY host — kept
# for back-compat and as the single mirror handed to the router's gh_fetch.
MIRROR_BASES = _load_mirror_bases()
MIRROR_BASE = MIRROR_BASES[0] if MIRROR_BASES else ""

# Only these repos are mirrored (must match each Worker's ALLOW set).
_MIRRORED = frozenset({
    "1andrevich/homeproxy-hiddify",
    "1andrevich/hiddify-core",
    "1andrevich/zapret2-openwrt",
    "1andrevich/ByeDPI-OpenWrt",
    "shtorm-7/sing-box-extended",
})

_GH_RELEASE = re.compile(r"^https://github\.com/([^/]+/[^/]+)/releases/(.+)$")


def _mirror_url_for(url: str, base: str) -> "str | None":
    """``url`` rewritten onto a specific mirror ``base``, or None if it's not a
    mirrorable GitHub *release* URL (non-GitHub host, or a repo we don't proxy)."""
    m = _GH_RELEASE.match(url)
    if not m or m.group(1) not in _MIRRORED:
        return None
    return f"{base}/{m.group(1)}/releases/{m.group(2)}"


def mirror_url(url: str) -> "str | None":
    """PRIMARY-mirror equivalent of a GitHub release URL, or None if not mirrorable
    (no mirror configured, non-GitHub host, or a repo we don't proxy). Back-compat +
    the URL handed to the router; the PC tries the full list via download_candidates."""
    return _mirror_url_for(url, MIRROR_BASE) if MIRROR_BASE else None


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
    """Ordered URLs to try for ``url``: every configured mirror (in order) plus GitHub.
    After the probe latches the session, the mirrors go FIRST (GitHub kept only as a
    last resort); otherwise GitHub-first with the mirrors as fallback. Non-mirrorable
    URLs (non-GitHub, or a repo we don't proxy) are returned unchanged."""
    mirrors = []
    for base in MIRROR_BASES:
        mu = _mirror_url_for(url, base)
        if mu:
            mirrors.append(mu)
    if not mirrors:
        return [url]
    return mirrors + [url] if _session_mirror else [url] + mirrors
