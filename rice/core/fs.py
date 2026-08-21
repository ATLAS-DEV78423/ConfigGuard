"""Filesystem abstraction — the ONLY module allowed to touch files directly.

Safety properties (spec §22, FR-025..028, SR-003/004):
- ``write_atomically``: temp file -> fsync -> atomic rename -> dir fsync.
- ``metadata`` is lstat-based: symlinks are described, never followed.
- ``canonicalize``/``is_within``/``require_within`` enforce protected scope.
- ``walk_files`` never descends through symlinked directories.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from rice.core.errors import ScopeViolation


@dataclass(frozen=True)
class FileMeta:
    """Everything rice records about one path (spec §10)."""

    path: str
    type: str  # "file" | "symlink" | "dir"
    mode: int
    uid: int
    gid: int
    size: int
    mtime_ns: int
    sha256: str | None = None
    symlink_target: str | None = None

    @classmethod
    def from_stat(cls, st: os.stat_result, path: Path) -> FileMeta:
        if stat.S_ISLNK(st.st_mode):
            kind = "symlink"
        elif stat.S_ISDIR(st.st_mode):
            kind = "dir"
        else:
            kind = "file"
        return cls(
            path=str(path),
            type=kind,
            mode=stat.S_IMODE(st.st_mode),
            uid=st.st_uid,
            gid=st.st_gid,
            size=st.st_size,
            mtime_ns=st.st_mtime_ns,
            symlink_target=os.readlink(path) if kind == "symlink" else None,
        )


def canonicalize(path: Path) -> Path:
    """Fully resolve a path (symlinks, .., ~ already expanded by caller)."""
    return Path(os.path.realpath(path))


def is_within(path: Path, roots: Sequence[Path]) -> bool:
    """True if the canonicalized path equals or lives under any root."""
    rp = canonicalize(path)
    for root in roots:
        rr = canonicalize(root)
        if rp == rr or rp.is_relative_to(rr):
            return True
    return False


def require_within(path: Path, roots: Sequence[Path]) -> None:
    """Raise ScopeViolation unless path is inside one of roots."""
    if not is_within(path, roots):
        raise ScopeViolation(
            f"refusing to touch {path}: outside approved scope ({', '.join(str(r) for r in roots)})"
        )


class Filesystem:
    """All filesystem mutations in rice go through this class."""

    # ---- reads ------------------------------------------------------------

    def read(self, path: Path) -> bytes:
        with open(path, "rb") as fh:
            return fh.read()

    def exists(self, path: Path) -> bool:
        return os.path.lexists(path)

    def is_symlink(self, path: Path) -> bool:
        return os.path.islink(path)

    def readlink(self, path: Path) -> str:
        return os.readlink(path)

    def metadata(self, path: Path) -> FileMeta:
        """lstat-based metadata; describes symlinks without following them."""
        return FileMeta.from_stat(os.lstat(path), path)

    def sha256(self, path: Path) -> str:
        with open(path, "rb") as fh:
            return hashlib.file_digest(fh, "sha256").hexdigest()

    def walk_files(self, root: Path) -> Iterator[Path]:
        """Yield every entry under root recursively. Symlinked dirs are yielded
        as entries themselves and never descended into."""
        if root.is_symlink():
            yield root
            return
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            base = Path(dirpath)
            keep: list[str] = []
            for name in dirnames:
                candidate = base / name
                if candidate.is_symlink():
                    yield candidate  # record it; do NOT traverse
                else:
                    keep.append(name)
            dirnames[:] = keep
            for name in filenames:
                yield base / name

    def free_space(self, path: Path) -> int:
        return shutil.disk_usage(path).free

    # ---- writes -----------------------------------------------------------

    def ensure_dir(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    def write_atomically(self, path: Path, data: bytes) -> None:
        """temp -> fsync -> rename -> parent fsync. Never leaves temp files."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
        self._fsync_dir(path.parent)

    def copy(self, src: Path, dst: Path) -> None:
        """Copy content + mode + mtime. A symlink src copies the LINK itself."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst, follow_symlinks=False)

    def remove(self, path: Path) -> None:
        """Remove a file, symlink, or directory tree. Caller scope-checks FIRST."""
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode):
            shutil.rmtree(path)
        else:
            os.remove(path)

    def symlink(self, target: str, link: Path) -> None:
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link)

    def chmod(self, path: Path, mode: int) -> None:
        os.chmod(path, mode)

    def chown(self, path: Path, uid: int, gid: int) -> None:
        shutil.chown(path, user=uid, group=gid)

    def utime(self, path: Path, mtime_ns: int) -> None:
        atime = int(mtime_ns // 1_000_000_000)
        ns = mtime_ns % 1_000_000_000
        os.utime(path, ns=(atime * 1_000_000_000 + ns,) * 2)

    # ---- internals --------------------------------------------------------

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)
