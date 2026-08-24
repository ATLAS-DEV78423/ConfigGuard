"""Validator aggregation contracts."""

from __future__ import annotations

from pathlib import Path

from support import FakeCommandRunner

from rice.core.fs import Filesystem
from rice.core.runner import RunResult
from rice.core.validator import Validator


def make_validator(tmp_path: Path, fake: FakeCommandRunner, apps: list[str]) -> Validator:
    home = tmp_path / "home"
    mapping = {"hyprland": "hypr", "waybar": "waybar", "kitty": "kitty", "wofi": "wofi"}
    for app in apps:
        (home / ".config" / mapping[app]).mkdir(parents=True)
    return Validator(Filesystem(), fake, home)


def test_validate_all_only_detects_present_apps(tmp_path: Path) -> None:
    v = make_validator(tmp_path, FakeCommandRunner(), ["kitty"])
    results = v.validate_all(["hyprland", "waybar", "kitty", "wofi"])
    assert [r.app for r in results] == ["kitty"]
    assert results[0].ok is None  # kitty: manual check needed


def test_waybar_valid_json_ok_invalid_json_is_manual_check(tmp_path: Path) -> None:
    """B3 contract: strict-parse failure is NOT proof of a broken config
    (the stripper is deliberately partial) -> ok=None, never ok=False."""
    home = tmp_path / "home"
    wb = home / ".config" / "waybar"
    wb.mkdir(parents=True)
    (wb / "config").write_text('{"clock": {"format": "%H:%M"}}')
    good = Validator(Filesystem(), FakeCommandRunner(), home).validate_all(["waybar"])
    assert good[0].ok is True

    (wb / "config").write_text("{not json")
    bad = Validator(Filesystem(), FakeCommandRunner(), home).validate_all(["waybar"])
    assert bad[0].ok is None
    assert "manual check needed" in bad[0].message


def test_failures_filters_manual_checks_out(tmp_path: Path) -> None:
    v = make_validator(tmp_path, FakeCommandRunner(), ["hyprland", "kitty"])
    results = v.validate_all(["hyprland", "kitty"])
    # default fake runner: probes succeed -> hyprland ok=True; kitty manual (None)
    assert [r for r in results if r.ok is False] == []
    assert any(r.ok is None for r in results)


def test_hyprland_reload_failure_counts_as_failure(tmp_path: Path) -> None:
    def script(args: list[str]) -> RunResult:
        if args[:2] == ["hyprctl", "--version"]:
            return RunResult(args=args, returncode=0)
        return RunResult(args=["hyprctl", "reload"], returncode=1, stderr="syntax error")

    v = make_validator(tmp_path, FakeCommandRunner(script=script), ["hyprland"])
    failures = [r for r in v.validate_all(["hyprland"]) if r.ok is False]
    assert len(failures) == 1 and failures[0].app == "hyprland"
