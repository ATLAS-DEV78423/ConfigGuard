"""Snapshot store contracts: round-trip, verification, scope, retention."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rice.core import snapshot as snapshot_mod
from rice.core.errors import ScopeViolation, SnapshotError
from rice.core.fs import Filesystem
from rice.core.snapshot import RETENTION_KEEP, SnapshotStore


@pytest.fixture()
def env(tmp_path: Path) -> tuple[SnapshotStore, Path, Path]:
    fs = Filesystem()
    home = tmp_path / "home"
    data_dir = tmp_path / "data"
    (home / ".config/hypr").mkdir(parents=True)
    (home / ".config/hypr/hyprland.conf").write_text("monitor=DP-1,1920x1080@144,0x0,1\n")
    os.chmod(home / ".config/hypr/hyprland.conf", 0o600)
    return SnapshotStore(fs, data_dir, home), fs, home


def protected(home: Path) -> list[Path]:
    return [home / ".config" / "hypr"]


def test_create_then_restore_round_trip(env: tuple[SnapshotStore, Path, Path]) -> None:
    store, fs, home = env
    conf = home / ".config/hypr/hyprland.conf"
    m0_mode = os.stat(conf).st_mode & 0o777
    snap = store.create(protected(home))
    assert len(snap.files) == 1

    conf.write_text("monitor=DP-1,1920x1080@165,0x0,1\n")  # "update" clobbers it
    restored = store.restore(snap.timestamp)
    assert restored == [".config/hypr/hyprland.conf"]
    assert "@144" in conf.read_text()
    assert os.stat(conf).st_mode & 0o777 == m0_mode  # FR-026 metadata preserved


def test_create_verifies_immediately_and_detects_tamper(
    env: tuple[SnapshotStore, Path, Path],
) -> None:
    store, fs, home = env
    snap = store.create(protected(home))
    backup = store.snapshots_root() / snap.timestamp / "files/.config/hypr/hyprland.conf"
    backup.write_text("tampered\n")
    with pytest.raises(SnapshotError, match="hash mismatch"):
        store.verify(snap.timestamp)


def test_restore_refuses_corrupted_snapshot(env: tuple[SnapshotStore, Path, Path]) -> None:
    store, fs, home = env
    snap = store.create(protected(home))
    backup = store.snapshots_root() / snap.timestamp / "files/.config/hypr/hyprland.conf"
    backup.write_text("evil\n")
    with pytest.raises(SnapshotError):
        store.restore(snap.timestamp)
    # live config untouched by the failed restore attempt
    assert "@144" in (home / ".config/hypr/hyprland.conf").read_text()


def test_insufficient_disk_space_aborts_before_copying(
    env: tuple[SnapshotStore, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, fs, home = env
    monkeypatch.setattr(fs, "free_space", lambda _p: 0)
    before = (
        sorted(str(p) for p in (store.snapshots_root()).glob("*"))
        if store.snapshots_root().exists()
        else []
    )
    with pytest.raises(SnapshotError, match="insufficient disk space"):
        store.create(protected(home))
    after = (
        sorted(str(p) for p in (store.snapshots_root()).glob("*"))
        if store.snapshots_root().exists()
        else []
    )
    assert before == after  # nothing written (FR-002 spirit: no partial snapshot)


def test_symlink_escape_is_skipped(env: tuple[SnapshotStore, Path, Path]) -> None:
    store, fs, home = env
    evil_target = Path("/etc/passwd")
    link = home / ".config/hypr/escape.conf"
    link.symlink_to(evil_target)
    snap = store.create(protected(home))
    rels = {e.rel_path for e in snap.files}
    assert ".config/hypr/escape.conf" not in rels  # refused, not followed
    assert ".config/hypr/hyprland.conf" in rels


def test_in_scope_symlink_recorded_and_restored(env: tuple[SnapshotStore, Path, Path]) -> None:
    store, fs, home = env
    real = home / ".config/hypr/theme.include"
    real.write_text("col.active_border=0xff89b4fa\n")
    link = home / ".config/hypr/current.conf"
    link.symlink_to(real)
    snap = store.create(protected(home))
    entry = next(e for e in snap.files if e.rel_path.endswith("current.conf"))
    assert entry.meta.type == "symlink"

    link.unlink()
    real.unlink()
    store.restore(snap.timestamp)
    assert link.is_symlink()
    assert real.exists()


def test_delete_only_inside_snapshots_root(env: tuple[SnapshotStore, Path, Path]) -> None:
    store, fs, home = env
    with pytest.raises(ScopeViolation):
        # path traversal via id: resolved dir must stay under snapshots root
        store.delete("../../home/.config")


def test_list_get_latest_ordering(env: tuple[SnapshotStore, Path, Path]) -> None:
    store, fs, home = env
    s1 = store.create(protected(home))
    s2 = store.create(protected(home))
    ids = [m.timestamp for m in store.list_all()]
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)  # collision suffixes keep ids unique
    assert store.get(s1.timestamp).timestamp == s1.timestamp
    assert store.get(s2.timestamp).timestamp == s2.timestamp
    with pytest.raises(SnapshotError):
        store.get("nope")


def test_prune_keeps_pinned_recent_and_last_ten(
    env: tuple[SnapshotStore, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, fs, home = env
    # Shrink the retention window so "old" is reachable in a fast test.
    monkeypatch.setattr(snapshot_mod, "RETENTION_DAYS", 0)
    pinned = store.create(protected(home), pinned=True)
    for _ in range(RETENTION_KEEP + 3):
        store.create(protected(home))
    doomed = store.prune()
    remaining = {m.timestamp for m in store.list_all()}
    assert pinned.timestamp in remaining  # pins survive forever
    assert len(doomed) == 3  # exactly the overflow beyond last-10
    for sid in doomed:
        assert sid not in remaining


def test_prune_keeps_everything_within_retention_window(
    env: tuple[SnapshotStore, Path, Path],
) -> None:
    """Spec policy is a UNION: last-10 OR last-30-days OR pinned. Fresh
    snapshots are all inside the 30-day window, so nothing gets deleted."""
    store, fs, home = env
    for _ in range(RETENTION_KEEP + 5):
        store.create(protected(home))
    assert store.prune() == []


def test_manifest_json_shape(env: tuple[SnapshotStore, Path, Path]) -> None:
    store, fs, home = env
    snap = store.create(protected(home), packages=["hyprland"])
    raw = json.loads(fs.read(store.snapshots_root() / snap.timestamp / "manifest.json"))
    assert raw["packages_upgraded"] == ["hyprland"]
    f0 = raw["files"][0]
    assert f0["rel_path"] == ".config/hypr/hyprland.conf"
    assert set(f0["meta"]) >= {"mode", "uid", "gid", "size", "mtime_ns", "sha256"}
