# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
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
