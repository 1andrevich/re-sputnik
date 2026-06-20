# SPDX-License-Identifier: GPL-2.0-only
"""The Executor abstraction.

The engine does not know *what* a payload is — only this contract. Concrete
executors (shell, ansible, declarative recipe, …) plug in over time; v1 needs
the contract to exist, not every implementation. Crucially, the SecurityGate
sits ABOVE this in the orchestrator, so every executor type passes the same
un-bypassable consent/log gate — no executor can sneak past it.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Optional

from ..router import RouterClient

LogCallback = Callable[[str], None]


class Origin(enum.Enum):
    """Where a payload came from — shown to the user before running."""

    BUILTIN = "builtin"        # shipped, trusted recipe
    LOCAL_FILE = "local_file"  # user's own file from disk
    DOWNLOADED = "downloaded"  # fetched from a URL (show url + hash)


@dataclass(slots=True)
class Requirement:
    """Something that must be present on the router for an executor to run."""

    name: str
    satisfied: bool
    hint: str = ""  # what to do if not satisfied (e.g. "install ansible")


@dataclass(slots=True)
class ExecResult:
    success: bool
    message: str = ""
    detail: str = ""


class Executor(ABC):
    """A unit of work that runs on the router through a RouterClient.

    Subclasses must not perform any device action in ``describe``/``preview``/
    ``requirements`` — those are read-only and safe to call before consent.
    """

    origin: Origin = Origin.BUILTIN
    source: str = ""  # url / file path / "" for builtin, shown at consent time

    @abstractmethod
    def describe(self) -> str:
        """One-line, human-readable summary of what running this will do."""

    @abstractmethod
    def preview(self) -> str:
        """Raw payload content (script text / playbook / recipe) for review."""

    def requirements(self, client: RouterClient) -> list[Requirement]:
        """Read-only check of what the router needs. Default: nothing."""
        return []

    @property
    def runs_as_root(self) -> bool:
        """Most OpenWRT actions run as root; surfaced in the consent screen."""
        return True

    @abstractmethod
    def run(self, client: RouterClient, log: Optional[LogCallback] = None) -> ExecResult:
        """Perform the work, streaming progress to ``log``."""


class ShellExecutor(Executor):
    """Runs a shell script on the router. The riskiest executor — arbitrary
    code as root — so it leans hardest on the SecurityGate above it.

    Stub-complete: functional, but custom/advanced shell payloads are an
    Advanced-mode, explicit-consent feature, not part of the default flow.
    """

    def __init__(
        self,
        script: str,
        *,
        title: str,
        origin: Origin = Origin.LOCAL_FILE,
        source: str = "",
        requires: Optional[list[str]] = None,
    ) -> None:
        self._script = script
        self._title = title
        self.origin = origin
        self.source = source
        self._requires = requires or []

    def describe(self) -> str:
        return self._title

    def preview(self) -> str:
        return self._script

    def requirements(self, client: RouterClient) -> list[Requirement]:
        reqs: list[Requirement] = []
        for tool in self._requires:
            ok = client.run(f"command -v {tool} >/dev/null 2>&1").ok
            reqs.append(
                Requirement(
                    name=tool,
                    satisfied=ok,
                    hint="" if ok else f"{tool} is not installed on the router",
                )
            )
        return reqs

    def run(self, client: RouterClient, log: Optional[LogCallback] = None) -> ExecResult:
        # Push the script and execute it, streaming output. We pipe via stdin so
        # nothing is written to persistent storage unless the script itself does.
        import shlex

        if log:
            log(f"running: {self._title}")
        # `sh -s` reads the script from stdin; exec_command can't feed stdin here,
        # so we heredoc it in a single command for simplicity and atomicity.
        encoded = self._script.replace("'", "'\\''")
        result = client.run(f"sh -c '{encoded}'", timeout=600)
        if log and result.stdout.strip():
            log(result.stdout.rstrip())
        if result.ok:
            return ExecResult(success=True, message="completed")
        return ExecResult(
            success=False,
            message=f"failed (exit {result.exit_code})",
            detail=result.stderr.strip() or result.stdout.strip(),
        )
