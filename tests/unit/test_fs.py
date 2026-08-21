"""Filesystem abstraction contracts: atomicity, hashing, metadata, scope."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from rice.core.errors import ScopeViolation
from rice.core.fs import Filesystem, canonicalize, is_within, require_within


def test_write_atomically_creates_and_overwrites(tmp_path: Path) -> None:
    fs = Filesystem()
    p = tmp_path / "sub" / "file.txt"
    fs.write_atomically(p, b"v1")
    fs.write_atomically(p, b"v2")
    assert p.read_bytes() == b"v2"


def test_atomic_failure_leaves_no_tmp_and_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fs = Filesystem()
    p = tmp_path / "f.txt"
    fs.write_atomically(p, b"original")

    def boom(src: object, dst: object) -> None:
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        fs.write_atomically(p, b"new")
    assert p.read_bytes() == b"original"
    assert list(tmp_path.glob("*.tmp")) == []
    assert not list(tmp_path.glob(".*.tmp"))


def test_sha256_known_vector(tmp_path: Path) -> None:
    fs = Filesystem()
    p = tmp_path / "h.txt"
    fs.write_atomically(p, b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert fs.sha256(p) == expected


def test_metadata_round_trips_mode(tmp_path: Path) -> None:
    fs = Filesystem()
    p = tmp_path / "m.conf"
    fs.write_atomically(p, b"x")
    os.chmod(p, 0o640)
    meta = fs.metadata(p)
    assert meta.type == "file"
    assert meta.mode == 0o640
    assert meta.size == 1
    assert meta.symlink_target is None


def test_symlink_metadata_records_target_without_following(tmp_path: Path) -> None:
    fs = Filesystem()
    real = tmp_path / "real.conf"
    fs.write_atomically(real, b"data")
    link = tmp_path / "link.conf"
    fs.symlink(str(real), link)
    meta = fs.metadata(link)
    assert meta.type == "symlink"
    assert meta.symlink_target == str(real)


def test_walk_yields_dir_symlink_but_never_descends(tmp_path: Path) -> None:
    fs = Filesystem()
    (tmp_path / "plain").mkdir()
    (tmp_path / "plain" / "a.conf").write_text("a")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "b.conf").write_text("b")
    (tmp_path / "plain" / "linked").symlink_to(outside)

    found = {p.name for p in fs.walk_files(tmp_path / "plain")}
    assert found == {"a.conf", "linked"}  # b.conf NOT pulled in through the link


def test_is_within_and_traversal(tmp_path: Path) -> None:
    inner = tmp_path / "a"
    inner.mkdir()
    assert is_within(inner / "f.conf", [inner])
    assert is_within(inner / ".." / "a" / "f.conf", [inner])  # resolves to inside
    assert not is_within(tmp_path / "elsewhere", [inner])


def test_require_within_raises_scope_violation(tmp_path: Path) -> None:
    with pytest.raises(ScopeViolation):
        require_within(Path("/etc/passwd"), [Path.home() / ".config"])


def test_canonicalize_resolves_dotdot(tmp_path: Path) -> None:
    a = tmp_path / "x"
    a.mkdir()
    assert canonicalize(a / ".." / "x") == a.resolve()


def test_copy_preserves_mode_and_mtime(tmp_path: Path) -> None:
    fs = Filesystem()
    src = tmp_path / "s.conf"
    fs.write_atomically(src, b"cfg")
    os.chmod(src, 0o600)
    m0 = fs.metadata(src)
    dst = tmp_path / "d" / "d.conf"
    fs.copy(src, dst)
    m1 = fs.metadata(dst)
    assert m1.mode == 0o600
    assert m1.mtime_ns == m0.mtime_ns
    assert fs.read(dst) == b"cfg"


def test_remove_file_and_tree(tmp_path: Path) -> None:
    fs = Filesystem()
    f = tmp_path / "f"
    fs.write_atomically(f, b"x")
    fs.remove(f)
    assert not fs.exists(f)
    d = tmp_path / "tree"
    (d / "n").mkdir(parents=True)
    fs.write_atomically(d / "n" / "g", b"y")
    fs.remove(d)
    assert not d.exists()


def test_free_space_positive(tmp_path: Path) -> None:
    assert Filesystem().free_space(tmp_path) > 0
