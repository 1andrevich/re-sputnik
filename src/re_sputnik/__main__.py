# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Entry point: ``python -m re_sputnik`` / ``re-sputnik``."""

from __future__ import annotations


def main() -> None:
    from .app import run

    run()


if __name__ == "__main__":
    main()
