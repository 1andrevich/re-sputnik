# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Application localization (gettext, source language = Russian).

Russian strings ARE the message ids (like English msgids in the LuCI app), so
the RU locale needs no catalog — it is the identity fallback. Other locales are
compiled .mo catalogs under ``re_sputnik/locale/<lang>/LC_MESSAGES/``.

Runtime depends only on the stdlib ``gettext``; extraction/compilation is done
with Babel (a dev/build tool), so no system gettext is required on Windows.

Usage:  from ..i18n import _      ;  label = _("Включить ByeDPI")
Switch: i18n.install_language("en")  then rebuild the visible screen.
"""

from __future__ import annotations

import gettext
import locale
import os
import sys

DOMAIN = "resputnik"
SOURCE = "ru"                                   # msgids are Russian → identity
AVAILABLE = ("ru", "en", "zh_Hans", "fa")       # offered in the picker
MACHINE = ("zh_Hans", "fa")                     # machine-translated → show disclaimer

# Display names for the language picker (each in its own script).
LANG_NAMES = {"ru": "Русский", "en": "English", "zh_Hans": "中文（简体）", "fa": "فارسی"}


def _locale_dir() -> str:
    # Bundled inside the package; in a PyInstaller onefile build it's under _MEIPASS.
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "re_sputnik", "locale")
    return os.path.join(os.path.dirname(__file__), "locale")


_current = SOURCE
_translation: gettext.NullTranslations = gettext.NullTranslations()


def install_language(lang: str) -> None:
    """Load (or reset to source) the active catalog. Safe to call repeatedly."""
    global _current, _translation
    if lang not in AVAILABLE:
        lang = SOURCE
    _current = lang
    if lang == SOURCE:
        _translation = gettext.NullTranslations()  # Russian source = identity
        return
    try:
        _translation = gettext.translation(DOMAIN, _locale_dir(), languages=[lang])
    except (FileNotFoundError, OSError):
        # Catalog not built yet → fall back to source rather than crash.
        _translation = gettext.NullTranslations()


def gettext_(message: str) -> str:
    # Reads the module-global catalog at CALL time, so already-imported `_`
    # references reflect the current language after install_language().
    return _translation.gettext(message)


def ngettext_(singular: str, plural: str, n: int) -> str:
    return _translation.ngettext(singular, plural, n)


def gettext_noop(message: str) -> str:
    """Mark a string for extraction without translating it now.

    For strings defined at import time (module-level constants like menu labels):
    tag them ``N_("…")`` so the extractor records them, then call ``_(label)`` at
    render time to translate against the *current* language.
    """
    return message


# Public aliases used across the app.
_ = gettext_
N_ = gettext_noop
ngettext = ngettext_


def current_language() -> str:
    return _current


# App UI language code -> LuCI / OpenWrt package language code. They mostly match;
# Simplified Chinese differs (app "zh_Hans" vs feed/LuCI "zh-cn"). English maps to
# itself — no packs are installed and LuCI is natively English.
_LUCI_LANG = {"ru": "ru", "en": "en", "zh_Hans": "zh-cn", "fa": "fa"}


def luci_lang(code: str | None = None) -> str:
    """LuCI/feed package language code for the given (or current) app language.

    Used when driving the router so the installed LuCI language packs and
    ``luci.main.lang`` follow the language the user picked in Re:Sputnik, instead
    of a hardcoded default."""
    code = code or _current
    return _LUCI_LANG.get(code, code)


def is_machine_translated(lang: str | None = None) -> bool:
    return (lang or _current) in MACHINE


def detect_default() -> str:
    """System locale → one of our codes (used when the user hasn't chosen yet)."""
    try:
        loc = (locale.getdefaultlocale()[0] or "").lower()
    except Exception:  # noqa: BLE001 — locale lookup is best-effort
        loc = ""
    if loc.startswith("ru"):
        return "ru"
    if loc.startswith("zh"):
        return "zh_Hans"
    if loc.startswith("fa"):
        return "fa"
    if loc.startswith("en"):
        return "en"
    return SOURCE
