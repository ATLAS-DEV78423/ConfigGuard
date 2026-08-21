"""Crash-recovery scenarios (spec §26 recovery/, FR-004, REQ-IDEMP).

Simulated crashes = hand-crafted journal files in various states; no real
process killing needed because the journal IS the crash surface.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rice.cli as cli_mod
from rice.cli import app
from rice.core.config import load_config
from rice.core.fs import Filesystem
from rice.core.snapshot import SnapshotStore
from rice.core.state import TransactionJournal

runner = CliRunner()


def seed_rice_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Filesystem]:
    home = tmp_path / "home"
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "hyprland.conf").write_text("monitor=DP-1@144\n")
    monkeypatch.setattr(cli_mod, "_HOME_OVERRIDE", home)
    assert runner.invoke(app, ["--non-interactive", "init"], catch_exceptions=False).exit_code == 0
    assert runner.invoke(app, ["snapshot"], catch_exceptions=False).exit_code == 0
    return home, Filesystem()


def craft_crash(home: Path, state: str) -> None:
    """Hand-write a crashed journal, walking only LEGAL transitions."""
    fs = Filesystem()
    cfg = load_config(fs, home=home)
    snap_id = json.loads(
        runner.invoke(app, ["--json", "snapshots", "list"], catch_exceptions=False).output
    )[0]["id"]
    journal = TransactionJournal(fs, cfg.data_dir)
    journal.begin(f"crash-{state.lower()}")
    journal.record("snapshot_id", snap_id)
    chains: dict[str, list] = {
        "PREPARING": [],
        "UPDATING": ["SNAPSHOTTED", "UPDATING"],
        "RECONCILING": ["SNAPSHOTTED", "UPDATING", "UPDATED", "RECONCILING"],
    }
    from rice.core.state import TransactionState

    for step in chains[state]:
        journal.set_state(TransactionState(step))


def test_status_reports_interrupted_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, fs = seed_rice_home(tmp_path, monkeypatch)
    craft_crash(home, "UPDATING")

    result = runner.invoke(app, ["status"], catch_exceptions=False)
    assert result.exit_code == 0
    assert "Interrupted transaction" in result.output
    assert "UPDATING" in result.output


def test_doctor_fix_recovers_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home, fs = seed_rice_home(tmp_path, monkeypatch)
    conf = home / ".config/hypr/hyprland.conf"
    craft_crash(home, "UPDATING")

    # Config got mangled by the "update" before the crash.
    conf.write_text("garbage from a half-finished update\n")

    first = runner.invoke(app, ["doctor", "--fix"], catch_exceptions=False)
    assert first.exit_code == 0, first.output
    assert "@144" in conf.read_text()  # restored to snapshot state

    # Idempotent: second pass is a no-op and stays healthy.
    second = runner.invoke(app, ["doctor"], catch_exceptions=False)
    assert second.exit_code == 0
    assert "@144" in conf.read_text()
    assert TransactionJournal(fs, load_config(fs, home=home).data_dir).load() is None


def test_recover_preparing_crash_clears_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Crash BEFORE any snapshot existed: nothing to restore, just clean up."""
    home, fs = seed_rice_home(tmp_path, monkeypatch)
    journal = TransactionJournal(fs, load_config(fs, home=home).data_dir)
    journal.begin(f"crash-prep-{datetime.now(UTC):%H%M%S}")

    conf = home / ".config/hypr/hyprland.conf"
    before = conf.read_text()

    fixed = runner.invoke(app, ["doctor", "--fix"], catch_exceptions=False)
    assert fixed.exit_code == 0
    assert conf.read_text() == before  # untouched: there was nothing to restore


def test_journal_survives_simulated_hard_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Journal written atomically at each step => readable after 'power loss'."""
    home, fs = seed_rice_home(tmp_path, monkeypatch)
    cfg = load_config(fs, home=home)

    store = SnapshotStore(fs, cfg.data_dir, home)
    snap = store.create([home / ".config" / "hypr"])

    journal = TransactionJournal(fs, cfg.data_dir)
    rec = journal.begin(f"hard-exit-{datetime.now(UTC):%H%M%S}")
    journal.record("snapshot_id", snap.timestamp)
    del rec  # simulate process death right here; file must already be on disk

    fresh_journal = TransactionJournal(Filesystem(), cfg.data_dir)
    loaded = fresh_journal.load()
    assert loaded is not None
    assert loaded.state.value == "PREPARING"
    assert loaded.snapshot_id == snap.timestamp
