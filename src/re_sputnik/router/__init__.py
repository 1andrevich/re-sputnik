# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""Everything that touches the router. The ONLY door to the device."""

from .client import RouterClient, CommandResult, RouterError, CommandTimeout
from .state import RouterState, PackageManager, Readiness, detect_state, root_has_password

__all__ = [
    "RouterClient",
    "CommandResult",
    "RouterError",
    "CommandTimeout",
    "RouterState",
    "PackageManager",
    "Readiness",
    "detect_state",
    "root_has_password",
]
