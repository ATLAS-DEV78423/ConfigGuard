"""CLI command contracts via Typer CliRunner. Exit codes per spec §6."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rice.cli as cli_mod
from rice.cli import app

runner = CliRunner()


def run(*args: str) -> object:
    return runner.invoke(app, list(args), catch_exceptions=False)


# ---- version -----------------------------------------------------------------


def test_version_flag_prints_semver() -> None:
    result = run("--version")
    assert result.exit_code == 0
    assert result.output.startswith("rice ")
    assert result.output.split()[1].count(".") == 2


def test_completion_bash_zsh_fish() -> None:
    for shell in ("bash", "zsh", "fish"):
        result = run("completion", shell)
        assert result.exit_code == 0
        assert "_RICE_COMPLETE=" in result.output


def test_completion_unknown_shell_exit_2(fake_home: Path) -> None:
    result = runner.invoke(app, ["completion", "tcsh"], catch_exceptions=False)
    assert result.exit_code == 2


# ---- init / config gate --------------------------------------------------------


def test_commands_before_init_exit_3(fake_home: Path) -> None:
    for cmd in (["status"], ["snapshot"], ["restore"], ["snapshots", "list"]):
        result = runner.invoke(app, cmd, catch_exceptions=False)
        assert result.exit_code == 3, f"{cmd} should exit 3 before init"
        assert "rice init" in result.output


def test_init_non_interactive_persists_config(fake_home: Path) -> None:
    result = run("--non-interactive", "init")
    assert result.exit_code == 0, result.output
    cfg = fake_home / ".config" / "rice" / "config.toml"
    assert cfg.exists()
    text = cfg.read_text()
    assert "[protected]" in text
    for app_name in ("hyprland", "waybar"):
        assert app_name in text


def test_status_after_init(fake_home: Path) -> None:
    assert run("--non-interactive", "init").exit_code == 0
    result = run("status")
    assert result.exit_code == 0
    assert "Protected apps:" in result.output


def test_status_json_parses(fake_home: Path) -> None:
    assert run("--non-interactive", "init").exit_code == 0
    result = run("--json", "status")
    payload = json.loads(result.output)
    assert payload["distro"]["id"] is None or isinstance(payload["distro"]["id"], str)
    assert "hyprland" in payload["protected"]
    assert payload["last_snapshot"] is None


# ---- snapshot lifecycle ----------------------------------------------------------


@pytest.fixture()
def initialized(fake_home: Path) -> Path:
    assert run("--non-interactive", "init").exit_code == 0
    return fake_home


def test_snapshot_creates_and_lists(initialized: Path) -> None:
    result = run("snapshot")
    assert result.exit_code == 0
    assert "files" in result.output
    listing = run("snapshots", "list")
    assert listing.exit_code == 0
    assert "files=" in listing.output


def test_snapshot_pin_marks_manifest(initialized: Path) -> None:
    run("snapshot", "--pin")
    listing = run("--json", "snapshots", "list")
    snaps = json.loads(listing.output)
    assert len(snaps) == 1 and snaps[0]["pinned"] is True


def test_snapshots_show_defaults_latest_json(initialized: Path) -> None:
    run("snapshot")
    result = run("--json", "snapshots", "show")
    manifest = json.loads(result.output)
    assert manifest["files"][0]["rel_path"].startswith(".config/")


def test_snapshots_delete_requires_force_non_interactive(initialized: Path) -> None:
    run("snapshot")
    snap_id = json.loads(run("--json", "snapshots", "list").output)[0]["id"]
    denied = runner.invoke(
        app, ["--non-interactive", "snapshots", "delete", snap_id], catch_exceptions=False
    )
    assert denied.exit_code == 2
    ok = runner.invoke(
        app,
        ["--non-interactive", "snapshots", "delete", snap_id, "--force"],
        catch_exceptions=False,
    )
    assert ok.exit_code == 0


def test_restore_requires_id_non_interactive(initialized: Path) -> None:
    run("snapshot")
    denied = runner.invoke(app, ["--non-interactive", "restore"], catch_exceptions=False)
    assert denied.exit_code == 2
    snap_id = json.loads(run("--json", "snapshots", "list").output)[0]["id"]
    ok = runner.invoke(app, ["--non-interactive", "restore", snap_id], catch_exceptions=False)
    assert ok.exit_code == 0
    assert "Restored" in ok.output


def test_prune_nothing_to_do(initialized: Path) -> None:
    run("snapshot")
    result = run("snapshots", "prune")
    assert result.exit_code == 0
    assert "Nothing to prune." in result.output or "Deleted" not in result.output


def test_no_real_home_touches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Paranoia check: with override unset the CLI would hit real $HOME — ensure
    the fixture mechanism is what tests rely on (override set => tmp paths)."""
    monkeypatch.setattr(cli_mod, "_HOME_OVERRIDE", tmp_path / "home")
    (tmp_path / "home").mkdir()
    assert cli_mod._home() == tmp_path / "home"
