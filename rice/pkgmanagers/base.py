"""PackageManager interface (spec §9/§15). ALL package-manager operations go
through this ABC — never call apt/pacman/dnf from anywhere else."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from rice.core.runner import CommandRunner

STDOUT_TAIL_CHARS = 4000


@dataclass(frozen=True)
class UpdateResult:
    """Outcome of a package-manager update (spec §10)."""

    success: bool
    exit_code: int
    upgraded: list[str] = field(default_factory=list)
    stdout_tail: str = ""
    stderr_tail: str = ""


def tail(text: str, limit: int = STDOUT_TAIL_CHARS) -> str:
    return text[-limit:]


class PackageManager(ABC):
    name: str

    @classmethod
    @abstractmethod
    def detect(cls, runner: CommandRunner) -> bool:
        """True if this package manager exists on the system."""

    @abstractmethod
    def update(self, runner: CommandRunner) -> UpdateResult:
        """Run the update. Conservative orchestration; never bypass locks."""
