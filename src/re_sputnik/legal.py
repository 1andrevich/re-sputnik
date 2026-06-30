# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Loaders for the bundled legal texts (the GPLv3 LICENSE + third-party NOTICE).

The first-run disclaimer gate and the About screen both read these. Keeping the
lookup in one place means the same resolution logic (repo root in dev, _MEIPASS
in the frozen build) serves every caller.

``load_license()`` returns the project's license — the GNU GPLv3 ``LICENSE`` text,
the same for every UI language.
"""

from __future__ import annotations

import os
import sys

_FALLBACK_NOTICE = (
    "Сторонние компоненты:\n"
    "  • paramiko (LGPL-2.1), customtkinter (MIT), Pillow (HPND), keyring (MIT),\n"
    "    PyYAML (MIT), qrcode (BSD), certifi (MPL-2.0)\n"
    "  • Иконки сервисов — Simple Icons (CC0-1.0); товарные знаки принадлежат "
    "их владельцам и используются только для обозначения сервисов.\n\n"
    "Полный текст — в файле NOTICE в каталоге программы."
)


def _candidates(filename: str) -> list[str]:
    """Possible on-disk locations for a bundled legal file, best first.

    Frozen (PyInstaller) build: under ``sys._MEIPASS/re_sputnik/resources`` (the
    spec copies NOTICE/LICENSE there). Dev checkout: the repo root, three levels up
    from this module (``re_sputnik`` -> ``src`` -> repo).
    """
    here = os.path.dirname(os.path.abspath(__file__))
    out: list[str] = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        out += [
            os.path.join(base, "re_sputnik", "resources", filename),
            os.path.join(base, filename),
        ]
    out += [
        os.path.join(here, "resources", filename),          # packaged copy beside resources
        os.path.join(here, os.pardir, os.pardir, filename),  # repo root (src/re_sputnik -> root)
    ]
    return out


def _read_first(filename: str) -> str | None:
    for path in _candidates(filename):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read().strip()
        except OSError:
            pass
    return None


def load_notice() -> str:
    """Full third-party NOTICE text, or a short inline fallback if not found."""
    return _read_first("NOTICE") or _FALLBACK_NOTICE


def load_license() -> str:
    """The project's GNU GPLv3 license text (``LICENSE``), or a short fallback."""
    return _read_first("LICENSE") or (
        "Re:Sputnik is free software licensed under the GNU General Public "
        "License v3.0. The full LICENSE file could not be located here; see the "
        "project repository for the complete text: "
        "https://www.gnu.org/licenses/gpl-3.0.txt"
    )


def _license_dir() -> str | None:
    """Locate the bundled THIRD_PARTY_LICENSES directory (frozen or dev)."""
    for path in _candidates("THIRD_PARTY_LICENSES"):
        if os.path.isdir(path):
            return path
    return None


def list_license_docs() -> list[tuple[str, str]]:
    """(title, text) pairs for the in-app license browser: the NOTICE overview
    first, then every bundled third-party license text file.

    The full texts must reach the recipient (LGPL/MPL etc. require it); surfacing
    them in-app guarantees that regardless of how the binary was obtained.
    """
    docs: list[tuple[str, str]] = [("NOTICE — overview / attributions", load_notice())]
    directory = _license_dir()
    if directory:
        for name in sorted(os.listdir(directory)):
            if not name.lower().endswith(".txt") or name.lower() == "readme.txt":
                continue
            try:
                with open(os.path.join(directory, name), "r", encoding="utf-8") as fh:
                    docs.append((name, fh.read().strip()))
            except OSError:
                pass
    return docs
