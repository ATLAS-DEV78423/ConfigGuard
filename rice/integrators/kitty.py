"""Kitty integrator: ~/.config/kitty; V1 does a presence check only.

Kitty has no stable offline config-check flag, so rice refuses to pretend
(spec §20: unsupported -> manual check needed).
"""

from __future__ import annotations

from pathlib import Path

from rice.core.fs import Filesystem
from rice.integrators.common import DesktopIntegrator, ValidationResult


class KittyIntegrator(DesktopIntegrator):
    name = "kitty"

    def detect(self) -> bool:
        return (self.home / ".config" / "kitty").is_dir()

    def config_dirs(self) -> list[Path]:
        root = self.home / ".config" / "kitty"
        return [root] if root.is_dir() else []

    def validate(self, fs: Filesystem) -> ValidationResult:
        conf = self.home / ".config" / "kitty" / "kitty.conf"
        if fs.exists(conf):
            return ValidationResult(self.name, None, "manual check needed")
        return ValidationResult(self.name, None, "no kitty.conf found")
