# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Router admin access — SSH authorized keys + the root password.

This is about who can administer the ROUTER (not homeproxy's per-LAN-device proxy
policy — that's engine/access.py). Lists the keys in dropbear's authorized_keys,
flags the one belonging to this app/device, and can revoke any/all of them. A
full lockdown also needs the root password changed, since password login lets
anyone re-add a key — so set_root_password lives here too.
"""

from __future__ import annotations

import base64
import hashlib
import shlex
from dataclasses import dataclass
from typing import Optional

from ..router import RouterClient
from ..router.client import AUTHORIZED_KEYS_PATH


@dataclass(slots=True)
class AuthKey:
    line: str            # the full authorized_keys line (used to revoke it)
    type: str            # e.g. ssh-ed25519
    comment: str
    fingerprint: str     # SHA256:… (matches `ssh-keygen -lf`)
    is_app: bool         # belongs to THIS app/device (the app's own key)


def _fingerprint(blob_b64: str) -> str:
    try:
        raw = base64.b64decode(blob_b64)
    except Exception:  # noqa: BLE001 — malformed key line
        return "?"
    return "SHA256:" + base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")


def list_keys(client: RouterClient, app_public: Optional[str] = None) -> list[AuthKey]:
    """Parse authorized_keys into entries, flagging the app's own key by blob."""
    app_blob = ""
    if app_public:
        parts = app_public.split()
        if len(parts) >= 2:
            app_blob = parts[1]
    out = client.run(f"cat {AUTHORIZED_KEYS_PATH} 2>/dev/null").stdout
    keys: list[AuthKey] = []
    for raw in out.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ktype, blob = parts[0], parts[1]
        comment = " ".join(parts[2:]) if len(parts) > 2 else ""
        keys.append(AuthKey(line=line, type=ktype, comment=comment,
                            fingerprint=_fingerprint(blob), is_app=(blob == app_blob)))
    return keys


def revoke_key(client: RouterClient, line: str) -> bool:
    """Remove one exact authorized_keys line. Returns True if removed."""
    line = line.strip()
    if not line:
        return False
    if not client.run(f"grep -qxF {shlex.quote(line)} {AUTHORIZED_KEYS_PATH} 2>/dev/null").ok:
        return False
    client.run(
        f"tmp=$(mktemp) && grep -vxF {shlex.quote(line)} {AUTHORIZED_KEYS_PATH} > \"$tmp\" "
        f"2>/dev/null; mv \"$tmp\" {AUTHORIZED_KEYS_PATH} && chmod 600 {AUTHORIZED_KEYS_PATH}"
    ).check()
    return True


def revoke_all_keys(client: RouterClient) -> int:
    """Remove ALL authorized keys. Returns how many were present."""
    n = len(list_keys(client))
    if n:
        client.run(f": > {AUTHORIZED_KEYS_PATH} && chmod 600 {AUTHORIZED_KEYS_PATH}").check()
    return n


def set_root_password(client: RouterClient, password: str) -> None:
    """Set the router's root password (busybox passwd reads it twice from stdin)."""
    if not password:
        raise ValueError("empty password")
    res = client.run(
        f"printf '%s\\n%s\\n' {shlex.quote(password)} {shlex.quote(password)} | passwd root",
        timeout=20,
    )
    if not res.ok:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip() or "passwd failed")
