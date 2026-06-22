# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Loaders for the bundled legal texts (EULA + third-party NOTICE).

The first-run acceptance gate and the About screen both read these. Keeping the
lookup in one place means the same resolution logic (repo root in dev, _MEIPASS
in the frozen build) serves every caller.

The EULA ships in two languages: ``EULA.txt`` (English) and ``EULA.ru.txt``
(Russian). ``load_eula(lang)`` returns the Russian text for ``ru`` and English
otherwise (zh/fa fall back to English — they are machine-translated UI locales
and the authoritative legal text is EN/RU).
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
    spec copies NOTICE/EULA there). Dev checkout: the repo root, three levels up
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


def load_eula(lang: str | None = None) -> str:
    """EULA text for the given UI language (Russian for 'ru', else English)."""
    if (lang or "").startswith("ru"):
        text = _read_first("EULA.ru.txt")
        if text:
            return text
    return _read_first("EULA.txt") or (
        "END-USER LICENSE AGREEMENT — Re:Sputnik\n\n"
        "The full agreement file (EULA.txt) could not be located. Re:Sputnik is "
        "closed-source freeware provided \"as is\", without warranty of any kind; "
        "you use it entirely at your own risk and remain responsible for "
        "complying with the laws of your country. See the project repository for "
        "the complete text."
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
