# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Small persisted app settings (JSON next to the router profiles).

Currently just the chosen UI language; kept separate from ``profiles`` (router
list) so unrelated concerns don't share a file. Reuses the same config dir
(%APPDATA%/re-sputnik on Windows).
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional

from .profiles import _config_dir

_SETTINGS_FILE = "settings.json"


def _path() -> str:
    return os.path.join(_config_dir(), _SETTINGS_FILE)


def load() -> dict[str, Any]:
    try:
        with open(_path(), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save(data: dict[str, Any]) -> None:
    os.makedirs(_config_dir(), exist_ok=True)
    with open(_path(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_language() -> Optional[str]:
    return load().get("language")


def set_language(lang: str) -> None:
    data = load()
    data["language"] = lang
    save(data)
