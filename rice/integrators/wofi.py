"""Wofi/Rofi integrator (CR-006): protects whichever of the two exists."""

from __future__ import annotations

from pathlib import Path

from rice.core.fs import Filesystem
from rice.integrators.common import DesktopIntegrator, ValidationResult


class WofiIntegrator(DesktopIntegrator):
    name = "wofi"

    def _existing(self) -> list[Path]:
        out = []
        for app in ("wofi", "rofi"):
            p = self.home / ".config" / app
            if p.is_dir():
                out.append(p)
        return out

    def detect(self) -> bool:
        return bool(self._existing())

    def config_dirs(self) -> list[Path]:
        return self._existing()

    def validate(self, fs: Filesystem) -> ValidationResult:
        for binary in ("wofi", "rofi"):
            probe = self.runner.run([binary, "--version"], timeout=10)
            if probe.ok:
                return ValidationResult(self.name, True, f"{binary} present; config not executed")
        return ValidationResult(self.name, None, "manual check needed (launcher not installed)")
