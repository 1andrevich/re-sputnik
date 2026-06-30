# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 1andrevich. Licensed under the GNU GPLv3 — see LICENSE.
"""SecurityGate — the single, un-bypassable consent checkpoint.

Every executor, of every type, passes through here before it touches the
router. The gate lives ABOVE the executor in the orchestrator, so a new payload
type cannot accidentally skip consent. It also records what happened, feeding
the UI's read-only log panel (transparency = trust).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from ..router import RouterClient
from .executor import ExecResult, Executor, Origin


class ConsentDenied(RuntimeError):
    """Raised when the user declines to run a payload."""


@dataclass(slots=True)
class ConsentRequest:
    """What the UI shows the user before anything runs."""

    title: str
    description: str
    preview: str
    origin: Origin
    source: str
    runs_as_root: bool
    unmet_requirements: list[str]

    @property
    def needs_loud_warning(self) -> bool:
        """Non-builtin payloads that run as root deserve a prominent warning."""
        return self.origin is not Origin.BUILTIN and self.runs_as_root


# The UI supplies this: show the request, return True to proceed.
ConsentHandler = Callable[[ConsentRequest], bool]
LogCallback = Callable[[str], None]


class SecurityGate:
    """Wraps execution with consent + logging. There is no path around it."""

    def __init__(
        self,
        consent_handler: ConsentHandler,
        *,
        log: Optional[LogCallback] = None,
        # Builtin recipes are pre-trusted; only require consent for the rest.
        # The UI can pass require_consent_for_builtin=True to confirm everything.
        require_consent_for_builtin: bool = False,
    ) -> None:
        self._consent = consent_handler
        self._log = log
        self._require_consent_for_builtin = require_consent_for_builtin

    def _build_request(self, executor: Executor, client: RouterClient) -> ConsentRequest:
        reqs = executor.requirements(client)
        unmet = [f"{r.name}: {r.hint}" for r in reqs if not r.satisfied]
        return ConsentRequest(
            title=executor.describe(),
            description=executor.describe(),
            preview=executor.preview(),
            origin=executor.origin,
            source=executor.source,
            runs_as_root=executor.runs_as_root,
            unmet_requirements=unmet,
        )

    def execute(self, executor: Executor, client: RouterClient) -> ExecResult:
        """Gate, then run. Raises ConsentDenied if the user says no."""
        request = self._build_request(executor, client)

        needs_consent = (
            executor.origin is not Origin.BUILTIN or self._require_consent_for_builtin
        )
        if needs_consent:
            if self._log:
                self._log(f"asking consent: {request.title} (source: {request.source or 'n/a'})")
            if not self._consent(request):
                if self._log:
                    self._log(f"declined: {request.title}")
                raise ConsentDenied(request.title)

        if self._log:
            self._log(f"begin: {request.title}")
        result = executor.run(client, self._log)
        if self._log:
            verb = "ok" if result.success else "failed"
            self._log(f"{verb}: {request.title} — {result.message}")
        return result
