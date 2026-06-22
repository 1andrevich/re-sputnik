# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""The engine: deterministic orchestration over executors, behind one gate."""

from .executor import Executor, ExecResult, Requirement, ShellExecutor
from .security import SecurityGate, ConsentRequest, ConsentDenied
from .orchestrator import Orchestrator, Phase, PhaseStatus
from .firstrun import FirstRunPlan, FirstRunResult, apply_firstrun
from . import nodes

__all__ = [
    "FirstRunPlan",
    "FirstRunResult",
    "apply_firstrun",
    "nodes",
    "Executor",
    "ExecResult",
    "Requirement",
    "ShellExecutor",
    "SecurityGate",
    "ConsentRequest",
    "ConsentDenied",
    "Orchestrator",
    "Phase",
    "PhaseStatus",
]
