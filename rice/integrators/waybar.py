"""Waybar integrator: ~/.config/waybar; jsonc sanity parse for the bar config."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rice.core.fs import Filesystem
from rice.integrators.common import DesktopIntegrator, ValidationResult

_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def strip_jsonc_comments(text: str) -> str:
    """Remove full-line // comments. Not a full jsonc parser — deliberately."""
    return _COMMENT.sub("", text)


class WaybarIntegrator(DesktopIntegrator):
    name = "waybar"

    def detect(self) -> bool:
        return (self.home / ".config" / "waybar").is_dir()

    def config_dirs(self) -> list[Path]:
        root = self.home / ".config" / "waybar"
        return [root] if root.is_dir() else []

    def validate(self, fs: Filesystem) -> ValidationResult:
        conf = self.home / ".config" / "waybar" / "config"
        if not fs.exists(conf):
            return ValidationResult(self.name, None, "no waybar config file")
        try:
            text = fs.read(conf).decode("utf-8")
            json.loads(strip_jsonc_comments(text))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            return ValidationResult(self.name, False, f"config parse error: {exc}")
        probe = self.runner.capture(["waybar", "--version"], timeout=10)
        note = "" if probe.ok else " (binary not found for runtime check)"
        return ValidationResult(self.name, True, f"jsonc parse ok{note}")
