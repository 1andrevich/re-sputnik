# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Router-side lease for the app's SSH key — a renewable dead-man's-switch.

Dropbear can't natively expire an ``authorized_keys`` entry (that's an OpenSSH
feature), so we enforce expiry from the router itself: a tiny daily cron job
prunes the app's key line once a stored lease timestamp passes. The app
*renews* the lease on every successful connect, so:

  • connect at least once within the lease window  → the key stays;
  • stop using the app (lost laptop, etc.)          → the key auto-prunes
    from every router after the window, with no action needed.

The lease is enforced by the router regardless of which SSH client is used, so
it also bounds a stolen key's usefulness once the window lapses. All on-device
state lives next to ``authorized_keys`` in ``/etc/dropbear``; everything here is
best-effort and must never break connect/setup if cron or the FS misbehaves.
"""

from __future__ import annotations

import shlex

from ..router.client import AUTHORIZED_KEYS_PATH, RouterClient

# One year. The window is deliberately generous: the point is to expire keys of
# routers you've abandoned, not to nag active users.
LEASE_DAYS = 365

_BLOB = "/etc/dropbear/.rc_blob"      # base64 blob of the app's key (match target)
_LEASE = "/etc/dropbear/.rc_lease"    # epoch seconds after which the key is pruned
_SCRIPT = "/etc/dropbear/rc-key-prune.sh"
_CRONTAB = "/etc/crontabs/root"
_CRON_LINE = f"23 4 * * * /bin/sh {_SCRIPT} >/dev/null 2>&1"

# Prune script: if the lease has lapsed, drop every authorized_keys line that
# contains the app's key blob, then clean up its own lease/blob files. Uses only
# busybox-available tools and preserves the authorized_keys file in place.
_PRUNE_SCRIPT = f"""#!/bin/sh
L={_LEASE}
B={_BLOB}
A={AUTHORIZED_KEYS_PATH}
[ -f "$L" ] && [ -f "$B" ] && [ -f "$A" ] || exit 0
exp=$(cat "$L" 2>/dev/null)
blob=$(cat "$B" 2>/dev/null)
[ -n "$exp" ] && [ -n "$blob" ] || exit 0
now=$(date +%s)
[ "$now" -gt "$exp" ] 2>/dev/null || exit 0
tmp="$A.rc_tmp"
if grep -vF "$blob" "$A" > "$tmp" 2>/dev/null; then
    cat "$tmp" > "$A"
fi
rm -f "$tmp" "$L" "$B"
logger -t re-companion "expired app SSH key pruned from authorized_keys" 2>/dev/null
exit 0
"""


def _blob_of(public_line: str) -> str:
    """The base64 token of an OpenSSH public-key line — the stable match key."""
    parts = (public_line or "").split()
    return parts[1] if len(parts) >= 2 else (public_line or "").strip()


def arm(client: RouterClient, public_line: str, days: int = LEASE_DAYS) -> bool:
    """Install the prune script + cron job and set the initial lease window.

    Idempotent: re-arming just refreshes the script/cron and (re)sets the lease.
    The expiry epoch is computed on the ROUTER to avoid PC/router clock skew.
    Returns True on success; never raises.
    """
    blob = _blob_of(public_line)
    if not blob:
        return False
    secs = max(1, int(days)) * 86400
    try:
        client.write_file(_SCRIPT, _PRUNE_SCRIPT)
        client.run(
            f"printf '%s\\n' {shlex.quote(blob)} > {_BLOB}; "
            f"printf '%s\\n' \"$(( $(date +%s) + {secs} ))\" > {_LEASE}; "
            f"chmod 600 {_BLOB} {_LEASE} 2>/dev/null; "
            f"mkdir -p $(dirname {_CRONTAB}); "
            f"grep -qF 'rc-key-prune.sh' {_CRONTAB} 2>/dev/null || "
            f"printf '%s\\n' {shlex.quote(_CRON_LINE)} >> {_CRONTAB}; "
            "/etc/init.d/cron enable >/dev/null 2>&1; "
            "/etc/init.d/cron restart >/dev/null 2>&1"
        )
        return True
    except Exception:
        return False


def renew(client: RouterClient, days: int = LEASE_DAYS) -> bool:
    """Push the lease forward by ``days`` — but only if a lease is already armed.

    Cheap (no cron restart): just rewrites the expiry epoch. Safe to call on
    every connect; does nothing if this router has no lease. Never raises.
    """
    secs = max(1, int(days)) * 86400
    try:
        client.run(
            f"[ -f {_BLOB} ] && "
            f"printf '%s\\n' \"$(( $(date +%s) + {secs} ))\" > {_LEASE} || true"
        )
        return True
    except Exception:
        return False


def disarm(client: RouterClient) -> bool:
    """Remove the lease, prune script and cron job (e.g. on key revocation).

    Leaves ``authorized_keys`` untouched — revoking the key itself is separate.
    Never raises.
    """
    try:
        client.run(
            f"sed -i '/rc-key-prune.sh/d' {_CRONTAB} 2>/dev/null; "
            f"rm -f {_LEASE} {_BLOB} {_SCRIPT}; "
            "/etc/init.d/cron restart >/dev/null 2>&1"
        )
        return True
    except Exception:
        return False
