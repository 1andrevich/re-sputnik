# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Saved router connection profiles (WinBox-style).

A small JSON registry of routers the user has connected to — host, port, user,
label, last-connected — so Advanced users reconnect in one click instead of
retyping the address every time.

SECRETS ARE NOT STORED HERE. The root password stays in the OS keychain
(secrets.store_router_password) and the host-key pin too; this file holds only
non-secret connection metadata. Forgetting a profile also clears its keychain
secrets (unless another profile still uses the same host).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import asdict, dataclass, fields

from . import secrets as app_secrets

APP_DIR_NAME = "re-sputnik"
_LEGACY_DIR_NAME = "re-companion"  # pre-rebrand folder, migrated on first access


def _config_dir() -> str:
    """Per-user config directory, following each OS's convention."""
    if sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    elif os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:  # Linux / other POSIX
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
            os.path.expanduser("~"), ".config")
    path = os.path.join(base, APP_DIR_NAME)
    # Migrate the pre-rebrand folder so saved profiles/settings carry over: rename in
    # place when possible, else copy its contents. Best-effort — never fatal.
    if not os.path.isdir(path):
        legacy = os.path.join(base, _LEGACY_DIR_NAME)
        if os.path.isdir(legacy):
            try:
                os.rename(legacy, path)
            except OSError:
                try:
                    import shutil
                    shutil.copytree(legacy, path)
                except OSError:
                    pass
    os.makedirs(path, exist_ok=True)
    return path


def _registry_path() -> str:
    return os.path.join(_config_dir(), "routers.json")


@dataclass
class RouterProfile:
    host: str
    port: int = 22
    user: str = "root"
    label: str = ""
    last_connected: float = 0.0

    @property
    def title(self) -> str:
        return self.label or self.host

    @property
    def endpoint(self) -> str:
        return f"{self.user}@{self.host}:{self.port}"


def _load_raw() -> list[dict]:
    try:
        with open(_registry_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def list_profiles() -> list[RouterProfile]:
    """Saved profiles, most-recently-connected first."""
    valid = {f.name for f in fields(RouterProfile)}
    out: list[RouterProfile] = []
    for d in _load_raw():
        if isinstance(d, dict) and d.get("host"):
            out.append(RouterProfile(**{k: v for k, v in d.items() if k in valid}))
    return sorted(out, key=lambda p: p.last_connected, reverse=True)


def _save_all(profs: list[RouterProfile]) -> None:
    path = _registry_path()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump([asdict(p) for p in profs], f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # atomic-ish: don't leave a half-written registry


def save_profile(host: str, port: int = 22, user: str = "root", label: str = "") -> None:
    """Upsert a profile and stamp it as just-connected."""
    host = (host or "").strip()
    if not host:
        return
    profs = list_profiles()
    existing = next((p for p in profs if p.host == host and p.port == port), None)
    if existing:
        existing.user = user or existing.user
        if label:
            existing.label = label
        existing.last_connected = time.time()
    else:
        profs.append(RouterProfile(host=host, port=port, user=user or "root",
                                   label=label, last_connected=time.time()))
    _save_all(profs)


def forget_profile(host: str, port: int = 22) -> None:
    """Remove a profile and its keychain secrets — unless another profile on the
    same host still needs the password/host-key."""
    remaining = [p for p in list_profiles() if not (p.host == host and p.port == port)]
    _save_all(remaining)
    if not any(p.host == host for p in remaining):
        app_secrets.forget_router_password(host)
        app_secrets.forget_hostkey(host)


def reset_app_data() -> None:
    """Wipe ALL local Re:Sputnik state on THIS machine — for handing off / cleaning a
    shared or borrowed computer so the next person can't connect to your routers.

    Removes from the OS keychain: the app's SSH identity (private+public key), every
    router root password and host-key pin, and the EULA-accepted flag. Deletes the
    on-disk config dir (router list + settings). The machine is left with no
    credentials and not even the LIST of routers; a fresh, useless SSH key is created
    on next use.

    The ROUTER is not touched: its old authorized public key is harmless once the
    private key here is gone (and the cron lease prunes it), and it keeps its current
    root password — recover it from «Безопасность» BEFORE resetting if you'll still
    need to manage that router."""
    import shutil

    # Read the host list BEFORE deleting routers.json, to clear per-host secrets.
    for prof in list_profiles():
        app_secrets.forget_router_password(prof.host)
        app_secrets.forget_hostkey(prof.host)
    app_secrets.delete_app_identity()
    app_secrets.forget_disclaimer()
    # On-disk config (router list + settings). Recreated empty on next save.
    shutil.rmtree(_config_dir(), ignore_errors=True)
