"""Hyprland integrator: ~/.config/hypr; validate via hyprctl reload if present."""

from __future__ import annotations

from rice.core.fs import Filesystem
from rice.integrators.common import DesktopIntegrator, ValidationResult


class HyprlandIntegrator(DesktopIntegrator):
    name = "hyprland"
    config_name = "hypr"

    def validate(self, fs: Filesystem) -> ValidationResult:
        probe = self.runner.run(["hyprctl", "--version"], timeout=10)
        if not probe.ok:
            return ValidationResult(self.name, None, "manual check needed (no compositor socket)")
        reload_ = self.runner.run(["hyprctl", "reload"], timeout=15)
        if reload_.ok:
            return ValidationResult(self.name, True, "hyprctl reload ok")
        tail = (reload_.stderr or reload_.stdout).strip().splitlines()[-1:] or ["unknown error"]
        return ValidationResult(self.name, False, f"hyprctl reload failed: {tail[0]}")
