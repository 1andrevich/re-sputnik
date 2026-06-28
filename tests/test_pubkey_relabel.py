# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Public-key comment normalization + blob matching.

Locks in the relabel behaviour: an old key's comment is rewritten to the current
per-machine label (``re-sputnik@<host>``), the key blob (the identity used for
matching in authorized_keys) is comment-independent, and the fingerprint-relevant
material is untouched.
"""
from __future__ import annotations

import sys

sys.path.insert(0, "src")
from re_sputnik.secrets import (  # noqa: E402
    _KEY_COMMENT,
    _key_comment,
    _normalize_pub_comment,
    pubkey_blob,
)

_BLOB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIabcdef0123456789EXAMPLEexample00="


def test_comment_carries_prefix_and_is_single_token() -> None:
    c = _key_comment()
    assert c.startswith(_KEY_COMMENT)         # always recognizable as the app's key
    assert " " not in c                       # single token → never breaks the line


def test_relabel_rewrites_old_comment() -> None:
    # An old 're-companion' label is replaced by the current per-machine label.
    assert _normalize_pub_comment(f"{_BLOB} re-companion") == f"{_BLOB} {_key_comment()}"


def test_relabel_is_idempotent_on_current_label() -> None:
    line = f"{_BLOB} {_key_comment()}"
    assert _normalize_pub_comment(line) == line


def test_relabel_adds_label_when_missing() -> None:
    assert _normalize_pub_comment(_BLOB) == f"{_BLOB} {_key_comment()}"


def test_blob_is_comment_independent() -> None:
    # Same key material, different labels → identical blob (so matching ignores label).
    assert pubkey_blob(f"{_BLOB} re-companion") == pubkey_blob(f"{_BLOB} re-sputnik@PC") == _BLOB


def test_blob_survives_malformed_line() -> None:
    assert pubkey_blob("garbage") == "garbage"
