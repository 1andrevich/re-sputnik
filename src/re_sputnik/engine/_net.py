# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""PC-side HTTP helper — one place for TLS trust + dead-proxy fallback.

Two failure modes this centralises, both seen in the wild on Windows:

* ``[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate`` —
  the bundled/frozen Python has no usable CA store (OpenSSL's default
  ``cert.pem`` path doesn't exist, and the Windows cert store isn't always
  reachable from a PyInstaller freeze). We pin a known-good CA bundle via
  ``certifi`` so verification always has trust anchors, independent of the OS.

* ``WinError 10061`` (connection refused) — a stale 127.0.0.1 proxy left
  configured by a prior VPN. urllib honours the WinINET proxy by default; on a
  connection-level error we retry DIRECT, bypassing every proxy. The targets are
  fixed public hosts (GitHub), so a proxy bypass is safe.
"""
from __future__ import annotations

import ssl
import urllib.error
import urllib.request


def _build_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi  # bundled in the frozen app; optional in a bare checkout

        ctx.load_verify_locations(certifi.where())
    except Exception:  # noqa: BLE001 — fall back to whatever the OS provides
        pass
    return ctx


_SSL = _build_ssl_context()


def http_get(url: str, *, timeout: int = 60, headers: dict[str, str] | None = None) -> bytes:
    """GET ``url`` and return the raw body.

    Verifies TLS against certifi's CA bundle. On a connection-level error
    (refused/unreachable, typically a dead local proxy) retries once DIRECT.
    A real HTTP status (404 etc.) propagates as ``HTTPError`` — a bypass won't
    change it.
    """
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "re-companion"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:  # noqa: S310
            return r.read()
    except urllib.error.HTTPError:
        raise
    except OSError:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=_SSL),
        )
        with opener.open(req, timeout=timeout) as r:  # noqa: S310
            return r.read()
