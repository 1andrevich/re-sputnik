# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Phase 1 — first-run setup actions, in a deliberately safe order.

Order matters for lock-out safety:

1. Install the app's SSH public key into ``authorized_keys``.
2. VERIFY key auth works via a fresh connection — if it doesn't, STOP before
   touching the password, so the user can never be locked out.
3. Only then set the root password (key auth already guarantees access).
4. Persist the password to the OS keychain.

This whole phase is a device change and must only run after explicit user
consent — the first-run screen's "Apply" button (with its warning) is that
consent.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from typing import Callable, Optional

import paramiko

from ..router import RouterClient, RouterError, root_has_password
from .. import secrets as app_secrets
from . import key_lease
from ..i18n import _

LogCallback = Callable[[str], None]


@dataclass(slots=True)
class FirstRunPlan:
    install_key: bool = True      # install the app's permanent SSH key ("remember")
    set_password: bool = True
    password: str = ""           # chosen root password (random or user-supplied)
    store_in_keychain: bool = True


@dataclass(slots=True)
class FirstRunResult:
    key_installed: bool = False
    key_verified: bool = False
    password_set: bool = False
    password_stored: bool = False
    steps: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _set_root_password(client: RouterClient, password: str) -> None:
    """Set root's password on OpenWRT.

    busybox ``passwd`` is fed the new password twice on stdin, delivered as a
    single-quoted ``printf`` argument (``shlex.quote``).

    NOT base64: stock busybox has no ``base64`` applet, so the previous
    ``base64 -d`` decode silently produced an EMPTY string — ``passwd`` accepted
    it and exited 0, leaving root effectively password-less while this step
    reported success. The app's password generator already excludes shell-unsafe
    characters, and ``shlex.quote`` makes the rest literal.

    The key is installed and verified before this runs, so a failure here never
    locks the user out — they still have key access.
    """
    if not password:
        raise RouterError("empty password")
    client.run(
        f"printf '%s\\n%s\\n' {shlex.quote(password)} {shlex.quote(password)} | passwd root",
        timeout=20,
    ).check()
    # Verify it actually took: passwd can exit 0 yet leave the hash unset on some
    # busybox builds. Never report success on a still-empty password.
    if not root_has_password(client):
        raise RouterError(_("пароль не сохранился на роутере (passwd не применил его)"))


def apply_firstrun(
    client: RouterClient,
    plan: FirstRunPlan,
    *,
    log: Optional[LogCallback] = None,
) -> FirstRunResult:
    """Run the first-run steps against an already-connected router."""
    result = FirstRunResult()

    def step(msg: str) -> None:
        result.steps.append(msg)
        if log:
            log(msg)

    # 1–2. App SSH key install + verify (only if "remember this device" is on).
    #      When skipped, future logins rely on the (keychain-stored) password,
    #      so we still keep store_in_keychain on regardless — see the screen.
    if plan.install_key:
        try:
            identity = app_secrets.load_or_create_app_identity()
        except app_secrets.SecretsError as exc:
            result.error = f"keychain: {exc}"
            return result

        try:
            step(_("Устанавливаю SSH-ключ приложения…"))
            client.install_public_key(identity.public_line)
            result.key_installed = True
        except RouterError as exc:
            result.error = f"не удалось установить ключ: {exc}"
            return result

        # Verify key auth from a fresh connection BEFORE changing the password.
        step(_("Проверяю вход по ключу…"))
        if not _verify_key_auth(client, identity.pkey):
            result.error = _("ключ установлен, но вход по нему не подтвердился — пароль не меняю")
            return result
        result.key_verified = True
        step(_("Вход по ключу работает."))

        # Arm the renewable 1-year lease: a router-side cron prunes this key if
        # the app stops connecting (dead-man's-switch). Best-effort — a failure
        # here must not abort setup, so we don't touch result.error.
        key_lease.arm(client, identity.public_line)
    else:
        step(_("Постоянный ключ не устанавливается (по выбору). "
             "Для будущих подключений потребуется пароль."))

    # 3. Root password (safe now: key access is guaranteed).
    #    Never overwrite a password the user already set — skip if one exists.
    if plan.set_password and plan.password:
        if root_has_password(client):
            step(_("У роутера уже задан пароль — оставляю без изменений."))
        else:
            try:
                step(_("Устанавливаю root-пароль…"))
                _set_root_password(client, plan.password)
                result.password_set = True
            except RouterError as exc:
                result.error = f"не удалось сменить пароль: {exc}"
                return result

        # 4. Persist to keychain.
        if plan.store_in_keychain:
            try:
                app_secrets.store_router_password(client.host, plan.password)
                result.password_stored = True
                step(_("Пароль сохранён в хранилище Windows."))
            except app_secrets.SecretsError as exc:
                # Non-fatal: password is set on the router, just not persisted.
                step(_("Пароль установлен, но не сохранён в хранилище: {0}").format(exc))

    step(_("Первичная настройка завершена."))
    return result


def _verify_key_auth(client: RouterClient, pkey: paramiko.PKey) -> bool:
    """Open a fresh, key-only connection and run a trivial command."""
    test = RouterClient(
        client.host,
        port=client.port,
        username=client.username,
        pkey=pkey,
    )
    try:
        test.connect()
        ok = test.run("true").ok
    except RouterError:
        return False
    finally:
        test.close()
    return ok
