"""CLI contracts for update / diff / doctor (exit codes per spec §6)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rice.cli as cli_mod
import rice.core.updater as updater_mod
from rice.cli import app
from rice.core.runner import FakeCommandRunner, RunResult

runner = CliRunner()


@pytest.fixture()
def rice_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated home with hyprland config + initialized rice config."""
    home = tmp_path / "home"
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (home / ".config" / "waybar").mkdir(parents=True)
    (home / ".config" / "waybar" / "config").write_text('{"clock": {}}')
    conf = hypr / "hyprland.conf"
    conf.write_text("monitor=DP-1@144\n")
    monkeypatch.setattr(cli_mod, "_HOME_OVERRIDE", home)

    def fake_runner_factory() -> FakeCommandRunner:
        script = getattr(updater_mod, "_TEST_SCRIPT", None)
        return FakeCommandRunner(script=script)

    monkeypatch.setattr(cli_mod, "CommandRunner", fake_runner_factory)
    assert runner.invoke(app, ["--non-interactive", "init"], catch_exceptions=False).exit_code == 0
    return home


def apt_script(
    on_upgrade: Callable[[], None] | None = None,
    *,
    upgrade_rc: int = 0,
    upgrade_stderr: str = "",
    reload_rc: int = 0,
) -> Callable[[list[str]], RunResult]:
    def script(args: list[str]) -> RunResult:
        joined = " ".join(args)
        if args[0] == "fuser":
            return RunResult(args=args, returncode=1)
        if "apt upgrade" in joined:
            if upgrade_rc == 0 and on_upgrade is not None:
                on_upgrade()
            return RunResult(args=args, returncode=upgrade_rc, stderr=upgrade_stderr)
        if args[:1] == ["hyprctl"] and "reload" in joined:
            return RunResult(args=args, returncode=reload_rc, stderr="bad line")
        return RunResult(args=args, returncode=0)

    return script


# ---- update --------------------------------------------------------------------


def test_update_success_via_cli(rice_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conf = rice_home / ".config/hypr/hyprland.conf"
    monkeypatch.setattr(
        updater_mod,
        "_TEST_SCRIPT",
        apt_script(on_upgrade=lambda: conf.write_text("monitor=@165\n")),
    )
    # Interactive update; answer the conflict prompt with [1] keep mine.
    result = runner.invoke(app, ["update"], input="1\n", catch_exceptions=False)
    assert result.exit_code == 0
    assert "@144" in conf.read_text()  # reconciled back to user's version


def test_update_dry_run_touches_nothing(rice_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(
        updater_mod,
        "_TEST_SCRIPT",
        apt_script(on_upgrade=lambda: called.append(1)),
    )
    result = runner.invoke(app, ["--dry-run", "update"], catch_exceptions=False)
    assert result.exit_code == 0
    assert called == []  # no package-manager call in dry-run


def test_update_apt_failure_exit_5(rice_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        updater_mod,
        "_TEST_SCRIPT",
        apt_script(upgrade_rc=100, upgrade_stderr="E: broken"),
    )
    result = runner.invoke(app, ["--non-interactive", "update"], catch_exceptions=False)
    assert result.exit_code == 5


def test_update_validation_failure_exit_7(rice_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conf = rice_home / ".config/hypr/hyprland.conf"
    monkeypatch.setattr(
        updater_mod,
        "_TEST_SCRIPT",
        apt_script(
            on_upgrade=lambda: conf.write_text("monitor=@165\n"),
            reload_rc=1,
        ),
    )
    result = runner.invoke(app, ["--non-interactive", "update"], catch_exceptions=False)
    assert result.exit_code == 7
    assert "@144" in conf.read_text()  # rolled back


# ---- diff ------------------------------------------------------------------------


def test_diff_reports_changes_json(rice_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert runner.invoke(app, ["snapshot"], catch_exceptions=False).exit_code == 0
    conf = rice_home / ".config/hypr/hyprland.conf"
    conf.write_text("monitor=DP-1@165\n")

    result = runner.invoke(app, ["--json", "diff"], catch_exceptions=False)
    payload = json.loads(result.output)
    assert payload["findings"] == [{"path": ".config/hypr/hyprland.conf", "verdict": "changed"}]


def test_diff_human_shows_unified_diff(rice_home: Path) -> None:
    assert runner.invoke(app, ["snapshot"], catch_exceptions=False).exit_code == 0
    (rice_home / ".config/hypr/hyprland.conf").write_text("monitor=DP-1@166\n")
    result = runner.invoke(app, ["diff"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "changed" in result.output and "snapshot" in result.output


def test_diff_no_snapshot_exit_4(rice_home: Path) -> None:
    result = runner.invoke(app, ["diff"], catch_exceptions=False)
    assert result.exit_code == 4


# ---- doctor -----------------------------------------------------------------------


def test_doctor_healthy_after_init(rice_home: Path) -> None:
    assert runner.invoke(app, ["snapshot"], catch_exceptions=False).exit_code == 0
    result = runner.invoke(app, ["doctor"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "[ok]" in result.output


def test_doctor_detects_and_fixes_interrupted_transaction(
    rice_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime

    from rice.core.config import load_config
    from rice.core.fs import Filesystem
    from rice.core.state import TransactionJournal, TransactionState

    assert runner.invoke(app, ["snapshot"], catch_exceptions=False).exit_code == 0
    fs = Filesystem()
    cfg = load_config(fs, home=rice_home)
    snap_id = json.loads(
        runner.invoke(app, ["--json", "snapshots", "list"], catch_exceptions=False).output
    )[0]["id"]

    # Craft a crash mid-update (legal transition chain).
    journal = TransactionJournal(fs, cfg.data_dir)
    journal.begin(f"{datetime.now(UTC):%Y%m%d-%H%M%S}")
    journal.record("snapshot_id", snap_id)
    journal.set_state(TransactionState.SNAPSHOTTED)
    journal.set_state(TransactionState.UPDATING)

    # User's config got mangled before the crash.
    conf = rice_home / ".config/hypr/hyprland.conf"
    conf.write_text("garbage\n")

    report = runner.invoke(app, ["--json", "doctor"], catch_exceptions=False)
    # CliRunner mixes stderr into output; doctor exits 7 (unresolved checks)
    # after printing the JSON, so decode only the first JSON document.
    payload, _ = json.JSONDecoder().raw_decode(report.output)
    pending_check = next(c for c in payload["checks"] if c["name"] == "pending-transaction")
    assert pending_check["ok"] is False
    assert report.exit_code == 7  # unresolved problems -> nonzero

    fix = runner.invoke(app, ["doctor", "--fix"], catch_exceptions=False)
    assert fix.exit_code == 0
    assert "@144" in conf.read_text()  # restored from snapshot

    again = runner.invoke(app, ["doctor"], catch_exceptions=False)
    assert again.exit_code == 0  # idempotent: clean now
