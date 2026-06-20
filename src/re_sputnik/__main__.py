# SPDX-License-Identifier: GPL-2.0-only
"""Entry point: ``python -m re_sputnik`` / ``re-sputnik``."""

from __future__ import annotations


def main() -> None:
    from .app import run

    run()


if __name__ == "__main__":
    main()
