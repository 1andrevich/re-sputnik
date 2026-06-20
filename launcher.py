# SPDX-License-Identifier: GPL-2.0-only
"""Frozen-build entry point.

PyInstaller analyzes this instead of ``re_sputnik/__main__.py`` because a
package's ``__main__`` is run as top-level ``__main__`` (its ``from .app``
relative import would fail). Here the import is absolute, so the package
resolves normally.
"""

from re_sputnik.app import run

if __name__ == "__main__":
    run()
