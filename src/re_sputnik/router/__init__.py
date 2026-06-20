# SPDX-License-Identifier: GPL-2.0-only
"""Everything that touches the router. The ONLY door to the device."""

from .client import RouterClient, CommandResult, RouterError
from .state import RouterState, PackageManager, Readiness, detect_state, root_has_password

__all__ = [
    "RouterClient",
    "CommandResult",
    "RouterError",
    "RouterState",
    "PackageManager",
    "Readiness",
    "detect_state",
    "root_has_password",
]
