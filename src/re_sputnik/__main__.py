# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Entry point: ``python -m re_sputnik`` / ``re-sputnik``."""

from __future__ import annotations


def main() -> None:
    from .app import run

    run()


if __name__ == "__main__":
    main()
