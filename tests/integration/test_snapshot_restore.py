"""Snapshot/restore round-trip through the real store + CLI (spec §35)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

import rice.cli as cli_mod
from rice.cli import app
from rice.core.errors import SnapshotError
from rice.core.fs import Filesystem
from rice.core.snapshot import SnapshotStore

runner = CliRunner()


def seed(home: Path) -> Path:
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True, exist_ok=True)
    conf = hypr / "hyprland.conf"
    conf.write_text("monitor=DP-1,1920x1080@144,0x0,1\n")
    os.chmod(conf, 0o644)
    return conf


def test_full_round_trip_via_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(cli_mod, "_HOME_OVERRIDE", home)
    conf = seed(home)

    assert runner.invoke(app, ["init", "--non-interactive"], catch_exceptions=False).exit_code == 0
    assert runner.invoke(app, ["snapshot"], catch_exceptions=False).exit_code == 0

    listing = runner.invoke(app, ["snapshots", "list", "--json"], catch_exceptions=False)
    snap_ids = json.loads(listing.output)
    assert len(snap_ids) == 1
    snap_id = snap_ids[0]["id"]

    # Simulate the update clobbering the user's config.
    conf.write_text("monitor=DP-1,1920x1080@165,0x0,1\n")
    os.chmod(conf, 0o600)

    restore = runner.invoke(app, ["--non-interactive", "restore", snap_id], catch_exceptions=False)
    assert restore.exit_code == 0, restore.output
    assert "@144" in conf.read_text()  # content back
    assert os.stat(conf).st_mode & 0o777 == 0o644  # mode back (FR-026)


def test_insufficient_space_reports_required_and_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = Filesystem()
    home = tmp_path / "h2"
    seed(home)
    store = SnapshotStore(fs, tmp_path / "data", home)

    monkeypatch.setattr(fs, "free_space", lambda _p: 0)
    with pytest.raises(SnapshotError) as excinfo:
        store.create([home / ".config" / "hypr"])
    msg = str(excinfo.value)
    assert "required" in msg and "available" in msg
