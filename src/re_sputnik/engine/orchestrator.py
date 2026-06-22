# SPDX-License-Identifier: LicenseRef-Proprietary
# Copyright (c) 2026 1andrevich. All rights reserved. Licensed under EULA.txt.
"""Orchestrator — the deterministic state machine over setup phases.

Quick Setup walks these phases 0->5 in order; Advanced mode lets the UI jump to
any phase's settings directly. Router state decides which phases are already
satisfied and can be skipped (working with a configured router is first-class).

This is a skeleton: phases declare their identity, gating, and a hook to run.
The concrete per-phase recipes (YAML) and their executors land incrementally.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..router import RouterClient, RouterState, Readiness
from ..i18n import _


class PhaseStatus(enum.Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


# A phase's gate decides, from router state, whether it still needs doing.
# Return True if the phase should run, False if it is already satisfied.
PhaseGate = Callable[[RouterState], bool]


@dataclass(slots=True)
class Phase:
    key: str
    title: str
    # If gate(state) is False the phase is auto-marked SKIPPED (already done).
    gate: Optional[PhaseGate] = None
    status: PhaseStatus = PhaseStatus.PENDING

    def evaluate(self, state: RouterState) -> None:
        if self.gate is not None and not self.gate(state):
            self.status = PhaseStatus.SKIPPED


def _needs_software(state: RouterState) -> bool:
    return not state.homeproxy_installed


def _needs_nodes(state: RouterState) -> bool:
    return not state.has_config


# The canonical Quick-Setup phase list (mirrors SETUP_AGENT's flow).
def default_phases() -> list[Phase]:
    return [
        Phase("connect", _("Подключение")),
        Phase("firstrun", _("Первичная настройка")),
        Phase("software", _("Установка ПО"), gate=_needs_software),
        Phase("nodes", "VPN / ByeDPI", gate=_needs_nodes),
        Phase("wifi", "Wi-Fi"),
        Phase("verify", _("Проверка")),
    ]


class Orchestrator:
    """Drives phases against a connected router + its detected state."""

    def __init__(self, client: RouterClient, state: RouterState) -> None:
        self.client = client
        self.state = state
        self.phases: list[Phase] = default_phases()
        self._evaluate_gates()

    def _evaluate_gates(self) -> None:
        for phase in self.phases:
            phase.evaluate(self.state)

    @property
    def pending(self) -> list[Phase]:
        return [p for p in self.phases if p.status is PhaseStatus.PENDING]

    def phase(self, key: str) -> Phase:
        for p in self.phases:
            if p.key == key:
                return p
        raise KeyError(key)

    def next_phase(self) -> Optional[Phase]:
        """First phase still needing work, or None when setup is complete."""
        for p in self.phases:
            if p.status is PhaseStatus.PENDING:
                return p
        return None

    def summary(self) -> str:
        readiness = {
            Readiness.CLEAN: _("чистый роутер — полная настройка"),
            Readiness.PARTIAL: _("ПО есть, нужна настройка серверов"),
            Readiness.CONFIGURED: _("уже настроен — режим управления"),
        }[self.state.readiness]
        lines = [_("Состояние: {0}").format(readiness)]
        for p in self.phases:
            mark = {
                PhaseStatus.PENDING: "○",
                PhaseStatus.ACTIVE: "▶",
                PhaseStatus.DONE: "✓",
                PhaseStatus.SKIPPED: "—",
                PhaseStatus.FAILED: "✗",
            }[p.status]
            lines.append(f"  {mark} {p.title}")
        return "\n".join(lines)
