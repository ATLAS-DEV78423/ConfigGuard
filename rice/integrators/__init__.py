"""Integrator registry. Fixed order = deterministic init/status output."""

from __future__ import annotations

from rice.integrators.common import DesktopIntegrator, ValidationResult
from rice.integrators.hyprland import HyprlandIntegrator
from rice.integrators.kitty import KittyIntegrator
from rice.integrators.waybar import WaybarIntegrator
from rice.integrators.wofi import WofiIntegrator

INTEGRATOR_CLASSES: list[type[DesktopIntegrator]] = [
    HyprlandIntegrator,
    WaybarIntegrator,
    KittyIntegrator,
    WofiIntegrator,
]

__all__ = [
    "DesktopIntegrator",
    "HyprlandIntegrator",
    "KittyIntegrator",
    "ValidationResult",
    "WaybarIntegrator",
    "WofiIntegrator",
    "INTEGRATOR_CLASSES",
]
