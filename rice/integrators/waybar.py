"""Waybar integrator: ~/.config/waybar; jsonc sanity parse for the bar config."""

from __future__ import annotations

import json
import re

from rice.core.fs import Filesystem
from rice.integrators.common import DesktopIntegrator, ValidationResult

_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)


def strip_jsonc_comments(text: str) -> str:
    """Remove full-line // comments. Not a full jsonc parser — deliberately."""
    return _COMMENT.sub("", text)


class WaybarIntegrator(DesktopIntegrator):
    name = "waybar"
    config_name = "waybar"

    def validate(self, fs: Filesystem) -> ValidationResult:
        conf = self.home / ".config" / "waybar" / "config"
        if not fs.exists(conf):
            return ValidationResult(self.name, None, "no waybar config file")
        try:
            text = fs.read(conf).decode("utf-8")
            json.loads(strip_jsonc_comments(text))
        except (OSError, UnicodeDecodeError) as exc:
            return ValidationResult(self.name, None, f"cannot read config: {exc}")
        except ValueError as exc:
            # The stripper is deliberately partial (inline //, trailing commas
            # unhandled): a parse failure here is NOT proof of a broken config.
            return ValidationResult(
                self.name, None, f"not strict JSON ({exc}); manual check needed"
            )
        probe = self.runner.run(["waybar", "--version"], timeout=10)
        note = "" if probe.ok else " (binary not found for runtime check)"
        return ValidationResult(self.name, True, f"jsonc parse ok{note}")
