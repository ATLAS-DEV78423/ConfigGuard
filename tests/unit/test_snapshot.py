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


def test_restore_replaces_broken_symlink(env: tuple[SnapshotStore, Path, Path]) -> None:
    """B1 regression: live path is a DANGLING symlink. lexists must see it,
    or os.symlink raises FileExistsError mid-restore."""
    store, fs, home = env
    real = home / ".config/hypr/theme.include"
    real.write_text("col.active_border=0xff89b4fa\n")
    link = home / ".config/hypr/current.conf"
    link.symlink_to(real)
    snap = store.create(protected(home))

    # Now make the live entry a BROKEN symlink where the entry belongs.
    link.unlink()
    link.symlink_to(home / ".config/hypr/nowhere")
    assert not link.exists() and link.is_symlink()

    store.restore(snap.timestamp)  # used to crash with FileExistsError
    assert link.is_symlink()
    assert os.readlink(link) == str(real)


def test_restore_refuses_directory_where_symlink_belongs(
    env: tuple[SnapshotStore, Path, Path],
) -> None:
    """B5: a type flip to a real dir at a symlink entry's path is refused,
    never rmtree'd."""
    store, fs, home = env
    real = home / ".config/hypr/theme.include"
    real.write_text("x\n")
    link = home / ".config/hypr/current.conf"
    link.symlink_to(real)
    snap = store.create(protected(home))

    link.unlink()
    link.mkdir()
    (link / "precious").write_text("do-not-delete\n")

    with pytest.raises(SnapshotError, match="directory"):
        store.restore(snap.timestamp)
    assert (link / "precious").exists()  # untouched


def test_restore_file_entry_refuses_directory_too(env: tuple[SnapshotStore, Path, Path]) -> None:
    """N1: dir guard applies to FILE entries as well — copy2 would otherwise
    plant the backup INSIDE the user's folder and chmod the directory."""
    store, fs, home = env
    conf = home / ".config/hypr/hyprland.conf"
    snap = store.create(protected(home))

    conf.unlink()
    conf.mkdir()
    (conf / "precious").write_text("do-not-delete\n")

    with pytest.raises(SnapshotError, match="directory"):
        store.restore(snap.timestamp)
    assert (conf / "precious").exists()  # untouched


def test_restore_file_entry_replaces_symlink_not_target(
    env: tuple[SnapshotStore, Path, Path],
) -> None:
    """N2: a live symlink at a file entry's path must be replaced by a real
    file — copy2 through it would clobber whatever the link points at."""
    store, fs, home = env
    conf = home / ".config/hypr/hyprland.conf"
    snap = store.create(protected(home))

    decoy = home / ".config/hypr/decoy.txt"
    decoy.write_text("keep-me\n")
    conf.unlink()
    conf.symlink_to(decoy)

    store.restore(snap.timestamp)
    assert not conf.is_symlink()  # link became a real file...
    assert "@144" in conf.read_text()  # ...with snapshot content
    assert decoy.read_text() == "keep-me\n"  # target untouched


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
