"""Reconciler contracts (spec §18/§19 decision table)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from rice.core.fs import Filesystem
from rice.core.reconciler import Action, ConflictAborted, Reconciler, Verdict
from rice.core.snapshot import SnapshotStore


@pytest.fixture()
def env(tmp_path: Path) -> tuple[Reconciler, SnapshotStore, Filesystem, Path]:
    fs = Filesystem()
    home = tmp_path / "home"
    data = tmp_path / "data"
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (hypr / "hyprland.conf").write_text("monitor=DP-1@144\n")
    store = SnapshotStore(fs, data, home)
    snap = store.create([home / ".config/hypr"])
    rec = Reconciler(fs, store)
    return rec, store, fs, home, snap.timestamp  # type: ignore[return-value]


def test_unchanged_and_changed_verdicts(env: tuple) -> None:
    rec, store, fs, home, sid = env
    findings = {f.entry.rel_path: f.verdict for f in rec.analyze(sid)}
    assert findings[".config/hypr/hyprland.conf"] is Verdict.UNCHANGED

    (home / ".config/hypr/hyprland.conf").write_text("monitor=DP-1@165\n")
    findings = {f.entry.rel_path: f for f in rec.analyze(sid)}
    assert findings[".config/hypr/hyprland.conf"].verdict is Verdict.CHANGED
    diff = findings[".config/hypr/hyprland.conf"].unified_diff
    assert diff is not None and "@144" in diff and "@165" in diff


def test_missing_current_verdict(env: tuple) -> None:
    rec, store, fs, home, sid = env
    os.remove(home / ".config/hypr/hyprland.conf")
    verdicts = [f.verdict for f in rec.analyze(sid)]
    assert Verdict.MISSING_CURRENT in verdicts


def test_type_changed_when_file_becomes_symlink(env: tuple) -> None:
    rec, store, fs, home, sid = env
    target = home / ".config/hypr/real.conf"
    target.write_text("monitor=DP-1@999\n")
    conf = home / ".config/hypr/hyprland.conf"
    conf.unlink()
    conf.symlink_to(target)
    verdicts = [f.verdict for f in rec.analyze(sid)]
    assert Verdict.TYPE_CHANGED in verdicts


def test_resolve_keep_mine_restores_snapshot_bytes(env: tuple) -> None:
    rec, store, fs, home, sid = env
    (home / ".config/hypr/hyprland.conf").write_text("monitor=DP-1@165\n")
    resolution = rec.resolve(sid, lambda _f: Action.KEEP_MINE)
    assert resolution.kept_mine == 1
    assert "144" in (home / ".config/hypr/hyprland.conf").read_text()


def test_resolve_use_new_leaves_current(env: tuple) -> None:
    rec, store, fs, home, sid = env
    (home / ".config/hypr/hyprland.conf").write_text("monitor=DP-1@165\n")
    resolution = rec.resolve(sid, lambda _f: Action.USE_NEW)
    assert resolution.used_new == 1
    assert "165" in (home / ".config/hypr/hyprland.conf").read_text()


def test_resolve_missing_current_auto_restores_without_decider(
    env: tuple,
) -> None:
    rec, store, fs, home, sid = env
    called = []
    os.remove(home / ".config/hypr/hyprland.conf")
    resolution = rec.resolve(sid, lambda f: called.append(f) or Action.KEEP_MINE)
    assert resolution.restored_missing == 1
    assert called == []  # no human decision needed for our own file
    assert "144" in (home / ".config/hypr/hyprland.conf").read_text()


def test_resolve_abort_raises_conflict_aborted_and_records(env: tuple) -> None:
    rec, store, fs, home, sid = env
    (home / ".config/hypr/hyprland.conf").write_text("monitor=DP-1@165\n")
    seen: list[dict] = []
    with pytest.raises(ConflictAborted):
        rec.resolve(sid, lambda _f: Action.ABORT, on_decision=seen.append)
    # abort decision was journaled before raising
    assert any(a.get("action") == "abort" for a in seen)


def test_decision_records_metadata_only(env: tuple) -> None:
    """Decision records carry paths/actions — never config contents (SR-002)."""
    rec, store, fs, home, sid = env
    (home / ".config/hypr/hyprland.conf").write_text("SECRET-LIKE CONTENT monitor=@165\n")
    seen: list[dict] = []
    rec.resolve(sid, lambda _f: Action.KEEP_MINE, on_decision=seen.append)
    blob = str(seen)
    assert "SECRET-LIKE" not in blob
