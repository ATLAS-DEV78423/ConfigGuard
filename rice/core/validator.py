"""Per-app config validation (spec §20).

Thin aggregation over integrator validators. Validation NEVER mutates
configs; unavailable binaries yield ok=None ("manual check needed").
"""

from __future__ import annotations

from pathlib import Path

from rice.core.fs import Filesystem
from rice.core.runner import CommandRunner
from rice.integrators import INTEGRATOR_CLASSES
from rice.integrators.common import ValidationResult


class Validator:
    def __init__(self, fs: Filesystem, runner: CommandRunner, home: Path) -> None:
        self._fs = fs
        self._integrators = [cls(home, runner) for cls in INTEGRATOR_CLASSES]

    def validate_all(self, apps: list[str]) -> list[ValidationResult]:
        results: list[ValidationResult] = []
        for integ in self._integrators:
            if integ.name in apps and integ.detect():
                results.append(integ.validate(self._fs))
        return results
