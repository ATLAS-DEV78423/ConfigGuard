"""DesktopIntegrator ABC: what rice needs to know about one protected app.

Integrators are read-only advisors: they report config roots and validate.
They NEVER mutate configs (spec §20).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from rice.core.fs import Filesystem
from rice.core.runner import CommandRunner


@dataclass(frozen=True)
class ValidationResult:
    """ok=None means 'cannot check here — manual verification needed'."""

    app: str
    ok: bool | None
    message: str


class DesktopIntegrator(ABC):
    name: str

    def __init__(self, home: Path, runner: CommandRunner) -> None:
        self.home = home
        self.runner = runner

    @abstractmethod
    def detect(self) -> bool:
        """True if this app's config exists under home."""

    @abstractmethod
    def config_dirs(self) -> list[Path]:
        """Absolute protected roots (existing ones only)."""

    def validate(self, fs: Filesystem) -> ValidationResult:
        return ValidationResult(app=self.name, ok=None, message="manual check needed")
