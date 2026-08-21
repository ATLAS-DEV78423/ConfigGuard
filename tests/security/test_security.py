"""Security requirement tests (SR-001..SR-007) + static safety sweeps."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rice.core.errors import ScopeViolation, SnapshotError
from rice.core.fs import Filesystem
from rice.core.snapshot import FileMeta, ManifestEntry, SnapshotStore

# Anchored to this file: tests/security/test_security.py -> tests -> repo root.
REPO_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = REPO_ROOT / "rice"

# Matches a BARE builtin open( — not os.open(, fs.open(, fdopen(, etc.
_RAW_OPEN_RE = re.compile(r"(?<![.\w])open\(")


@pytest.fixture()
def store_env(tmp_path: Path) -> tuple[SnapshotStore, Filesystem, Path]:
    fs = Filesystem()
    home = tmp_path / "home"
    data = tmp_path / "data"
    (home / ".config/hypr").mkdir(parents=True)
    return SnapshotStore(fs, data, home), fs, home


def test_sr005_tampered_backup_refused_on_restore(store_env: tuple) -> None:
    store, fs, home = store_env
    conf = home / ".config/hypr/hyprland.conf"
    conf.write_text("monitor=DP-1@144\n")
    snap = store.create([home / ".config/hypr"])

    backup = store.snapshots_root() / snap.timestamp / "files/.config/hypr/hyprland.conf"
    backup.write_text("monitor=EVIL\n")

    with pytest.raises(SnapshotError):
        store.restore(snap.timestamp)
    assert "@144" in conf.read_text()  # live file untouched by refused restore


def test_sr003_restore_entry_refuses_paths_outside_home(store_env: tuple) -> None:
    store, fs, home = store_env
    evil_meta = FileMeta(
        path="/etc/passwd",
        type="file",
        mode=0o644,
        uid=0,
        gid=0,
        size=0,
        mtime_ns=0,
        sha256=None,
        symlink_target=None,
    )
    entry = ManifestEntry(rel_path="../../etc/passwd", meta=evil_meta, backup_rel_path="files/x")
    with pytest.raises(ScopeViolation):
        store.restore_entry("any-snap", entry)


def test_sr004_symlink_target_escape_refused_at_restore(store_env: tuple) -> None:
    """A manifest entry whose symlink target escapes home is skipped, not followed."""
    store, fs, home = store_env
    link_meta = FileMeta(
        path="x",
        type="symlink",
        mode=0o777,
        uid=0,
        gid=0,
        size=0,
        mtime_ns=0,
        sha256=None,
        symlink_target="/etc/shadow",
    )
    entry = ManifestEntry(
        rel_path=".config/hypr/evil.conf", meta=link_meta, backup_rel_path="files/y"
    )
    store.restore_entry("any-snap", entry)
    assert not (home / ".config/hypr/evil.conf").exists()


# ---- static sweeps over package source (NFR-003/004) -------------------------


def _package_sources() -> list[tuple[Path, str]]:
    return [(p, p.read_text(encoding="utf-8")) for p in sorted(PACKAGE_DIR.rglob("*.py"))]


def test_nfr004_no_shell_true_anywhere() -> None:
    for path, text in _package_sources():
        assert "shell=True" not in text, f"{path} uses shell=True"


def test_nfr003_subprocess_only_in_runner() -> None:
    offenders = [
        str(path)
        for path, text in _package_sources()
        if "subprocess" in text and path.name != "runner.py"
    ]
    assert offenders == []


def test_nfr003_raw_open_only_in_fs() -> None:
    offenders: list[str] = []
    for path, text in _package_sources():
        if path.name == "fs.py":
            continue  # the abstraction itself may use open()
        for lineno, raw_line in enumerate(text.splitlines(), 1):
            code = raw_line.split("#", 1)[0]  # ignore comments
            if _RAW_OPEN_RE.search(code):
                offenders.append(f"{path}:{lineno}: {raw_line.strip()}")
    assert offenders == []


def test_no_os_system_or_popen() -> None:
    for path, text in _package_sources():
        assert "os.system" not in text, str(path)
        assert "os.popen" not in text, str(path)
        assert "Popen" not in text, str(path)


def test_sr002_reconcile_records_never_carry_config_contents(tmp_path: Path) -> None:
    """Decision records carry paths+actions only — never file bytes (SR-002)."""
    fs = Filesystem()
    home = tmp_path / "home2"
    data = tmp_path / "data2"
    (home / ".config/hypr").mkdir(parents=True)
    secret_line = "password=hunter2 monitor=@144\n"
    (home / ".config/hypr/hyprland.conf").write_text(secret_line)
    store = SnapshotStore(fs, data, home)
    snap = store.create([home / ".config/hypr"])
    (home / ".config/hypr/hyprland.conf").write_text("changed\n")

    from rice.core.reconciler import Action, Reconciler

    seen: list[dict] = []
    Reconciler(fs, store).resolve(
        snap.timestamp, lambda _f: Action.KEEP_MINE, on_decision=seen.append
    )
    blob = repr(seen)
    assert "hunter2" not in blob and "monitor" not in blob
