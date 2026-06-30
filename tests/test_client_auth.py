# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Auth-dispatch smoke tests for RouterClient._authenticate.

The fresh-router 'none' path needs a factory-state device to exercise live, so
it's a blind spot in manual testing. These mock the transport and pin the
dispatch order (password → app key → 'none') and that 'none' stays reachable —
so a future refactor can't silently break passwordless onboarding.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import paramiko
import pytest

sys.path.insert(0, "src")
from re_sputnik.router.client import RouterClient  # noqa: E402


def _client(**kw) -> RouterClient:
    return RouterClient("192.0.2.1", **kw)


def _transport(*, authed: bool = True, key_ok: bool = True) -> MagicMock:
    t = MagicMock()
    t.is_authenticated.return_value = authed
    if not key_ok:
        t.auth_publickey.side_effect = paramiko.AuthenticationException("no key")
    return t


def test_password_takes_precedence():
    t = _transport()
    _client(password="pw", pkey=MagicMock())._authenticate(t)
    t.auth_password.assert_called_once_with("root", "pw")
    t.auth_publickey.assert_not_called()
    t.auth_none.assert_not_called()


def test_key_used_when_no_password():
    t = _transport()
    pkey = MagicMock()
    _client(pkey=pkey)._authenticate(t)
    t.auth_publickey.assert_called_once_with("root", pkey)
    t.auth_none.assert_not_called()


def test_falls_back_to_none_when_key_rejected():
    # A returning-app key fails on a freshly-reset router → must try 'none'.
    t = _transport(key_ok=False)
    _client(pkey=MagicMock())._authenticate(t)
    t.auth_publickey.assert_called_once()
    t.auth_none.assert_called_once_with("root")


def test_none_when_no_credentials():
    t = _transport()
    _client()._authenticate(t)
    t.auth_none.assert_called_once_with("root")


def test_raises_when_none_not_sufficient():
    t = _transport(authed=False)
    with pytest.raises(paramiko.AuthenticationException):
        _client()._authenticate(t)
