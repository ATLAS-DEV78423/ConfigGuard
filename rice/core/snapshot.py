"""Snapshot store: create, verify, restore, list, delete, prune (spec §11/§21).

Invariants:
- Disk space preflight before any copy (FR-029).
- Every backup file's sha256 recorded at creation; verify() re-hashes.
- restore() verifies the snapshot FIRST (SR-005), then copies over with full
  metadata; never deletes originals first. Idempotent by construction.
- Symlinks escaping protected scope are refused (FR-028/SR-004).
- delete/prune only ever remove paths under snapshots_root (scope-checked).
"""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rice.core.errors import SnapshotError
from rice.core.fs import FileMeta, Filesystem, canonicalize, is_within, require_within

log = logging.getLogger("rice.snapshot")

RETENTION_KEEP = 10
RETENTION_DAYS = 30
SPACE_MARGIN = 1.1


def snapshot_id_now() -> str:
    """UTC timestamp id, filesystem-safe: 2026-08-21T12-04-33Z."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%SZ")


@dataclass(frozen=True)
class ManifestEntry:
    rel_path: str  # relative to home: ".config/hypr/hyprland.conf"
    meta: FileMeta
    backup_rel_path: str


@dataclass
class SnapshotManifest:
    timestamp: str
    host: str
    desktop: str | None = None
    packages_upgraded: list[str] = field(default_factory=list)
    pinned: bool = False
    files: list[ManifestEntry] = field(default_factory=list)

    def to_json(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "host": self.host,
            "desktop": self.desktop,
            "packages_upgraded": self.packages_upgraded,
            "pinned": self.pinned,
            "files": [
                {
                    "rel_path": e.rel_path,
                    "backup_rel_path": e.backup_rel_path,
                    "meta": asdict(e.meta),
                }
                for e in self.files
            ],
        }

    @classmethod
    def from_json(cls, raw: dict) -> SnapshotManifest:
        files = [
            ManifestEntry(
                rel_path=f["rel_path"],
                meta=FileMeta(**f["meta"]),
                backup_rel_path=f["backup_rel_path"],
            )
            for f in raw.get("files", [])
        ]
        return cls(
            timestamp=raw["timestamp"],
            host=raw.get("host", ""),
            desktop=raw.get("desktop"),
            packages_upgraded=list(raw.get("packages_upgraded", [])),
            pinned=bool(raw.get("pinned", False)),
            files=files,
        )


class SnapshotStore:
    def __init__(self, fs: Filesystem, data_dir: Path, home: Path) -> None:
        self._fs = fs
        self.data_dir = data_dir
        self.home = home

    # -- layout -------------------------------------------------------------

    def snapshots_root(self) -> Path:
        return self.data_dir / "snapshots"

    def _dir_for(self, snap_id: str) -> Path:
        require_within(self.snapshots_root() / snap_id, [self.snapshots_root()])
        return self.snapshots_root() / snap_id

    def exists(self, snap_id: str) -> bool:
        return (self.snapshots_root() / snap_id / "manifest.json").exists()

    # -- create -------------------------------------------------------------

    def create(
        self,
        protected: list[Path],
        *,
        pinned: bool = False,
        packages: list[str] | None = None,
        desktop: str | None = None,
        dry_run: bool = False,
    ) -> SnapshotManifest:
        root = self.snapshots_root()

        sources = self._collect_sources(protected)

        self._fs.ensure_dir(self.data_dir)  # free_space() needs an existing path
        required = int(sum(m.size for m in sources.values()) * SPACE_MARGIN)
        available = self._fs.free_space(root if root.exists() else self.data_dir)
        if required > available:
            raise SnapshotError(
                f"insufficient disk space: required ~{required // (1024 * 1024)}MB, "
                f"available {available // (1024 * 1024)}MB"
            )

        snap_id = snapshot_id_now()
        counter = 0
        while (root / snap_id).exists():  # second-resolution ids can collide
            counter += 1
            snap_id = f"{snapshot_id_now()}-{counter}"

        manifest = SnapshotManifest(
            timestamp=snap_id,
            host=socket.gethostname(),
            desktop=desktop,
            packages_upgraded=list(packages or []),
            pinned=pinned,
        )

        if dry_run:
            # Report exactly what would be captured, without touching disk.
            manifest.files = [
                ManifestEntry(
                    rel_path=src.relative_to(self.home).as_posix(),
                    meta=sources[src],
                    backup_rel_path=f"files/{src.relative_to(self.home).as_posix()}",
                )
                for src in sorted(sources)
            ]
            return manifest

        dest_dir = self._dir_for(snap_id)
        self._fs.ensure_dir(dest_dir / "files")
        for src in sorted(sources):
            meta = sources[src]
            rel = src.relative_to(self.home).as_posix()
            backup_rel = f"files/{rel}"
            target = dest_dir / backup_rel
            if meta.type == "symlink":
                target.parent.mkdir(parents=True, exist_ok=True)
                self._fs.symlink(meta.symlink_target or "", target)
            else:
                self._fs.copy(src, target)
            meta = FileMeta(  # re-hash source AFTER copy for manifest truth
                path=meta.path,
                type=meta.type,
                mode=meta.mode,
                uid=meta.uid,
                gid=meta.gid,
                size=meta.size,
                mtime_ns=meta.mtime_ns,
                sha256=self._fs.sha256(src) if meta.type == "file" else None,
                symlink_target=meta.symlink_target,
            )
            manifest.files.append(
                ManifestEntry(rel_path=rel, meta=meta, backup_rel_path=backup_rel)
            )
        self.write_manifest(dest_dir, manifest)
        self.verify(snap_id)  # FR-001/002: no update proceeds on unverified snapshot
        log.info(
            "snapshot %s created (%d files)%s",
            snap_id,
            len(manifest.files),
            " [pinned]" if pinned else "",
        )
        return manifest

    def write_manifest(self, dir_path: Path, manifest: SnapshotManifest) -> None:
        self._fs.ensure_dir(dir_path)
        self._fs.write_atomically(
            dir_path / "manifest.json", json.dumps(manifest.to_json(), indent=2).encode()
        )
        metadata = {
            "id": manifest.timestamp,
            "created_at": manifest.timestamp,
            "file_count": len(manifest.files),
            "pinned": manifest.pinned,
        }
        self._fs.write_atomically(
            dir_path / "metadata.json", json.dumps(metadata, indent=2).encode()
        )

    def _collect_sources(self, protected: list[Path]) -> dict[Path, FileMeta]:
        """Existing entries under protected roots, scope-checked, symlinks vetted."""
        sources: dict[Path, FileMeta] = {}
        for root in protected:
            canonical_root = canonicalize(root)
            if not self._fs.exists(canonical_root):
                log.warning("protected path missing, skipping: %s", canonical_root)
                continue
            require_within(canonical_root, protected)
            candidates = (
                [canonical_root]
                if canonical_root.is_file() or canonical_root.is_symlink()
                else list(self._fs.walk_files(canonical_root))
            )
            for path in candidates:
                meta = self._fs.metadata(path)
                if meta.type == "symlink":
                    target_real = canonicalize(path.parent / (meta.symlink_target or ""))
                    if not is_within(target_real, protected + [self.home]):
                        log.warning("refusing symlink escaping scope: %s", path)
                        continue
                sources[path] = meta
        return sources

    # -- verify -------------------------------------------------------------

    def verify(self, snap_id: str) -> SnapshotManifest:
        """Re-hash every regular backup file against its manifest entry."""
        d = self._dir_for(snap_id)
        try:
            raw = self._fs.read(d / "manifest.json")
        except OSError as exc:
            raise SnapshotError(f"snapshot {snap_id} unreadable: {exc}") from exc
        manifest = SnapshotManifest.from_json(json.loads(raw))
        for entry in manifest.files:
            backup = d / entry.backup_rel_path
            if not self._fs.exists(backup):
                raise SnapshotError(f"snapshot {snap_id}: missing backup {entry.rel_path}")
            if entry.meta.type == "file":
                actual = self._fs.sha256(backup)
                expected = entry.meta.sha256
                if expected and actual != expected:
                    raise SnapshotError(
                        f"snapshot {snap_id} corrupted: {entry.rel_path} hash mismatch"
                    )
        return manifest

    # -- restore ------------------------------------------------------------

    def restore(self, snap_id: str, *, dry_run: bool = False) -> list[str]:
        """Verify first, then copy every tracked file back with metadata."""
        manifest = self.verify(snap_id)  # SR-005: never restore an unverified snapshot
        if dry_run:
            return [e.rel_path for e in manifest.files]
        for entry in manifest.files:
            self.restore_entry(snap_id, entry)
        return [e.rel_path for e in manifest.files]

    def restore_entry(self, snap_id: str, entry: ManifestEntry) -> None:
        """Copy ONE tracked file back from a verified snapshot. Idempotent."""
        d = self._dir_for(snap_id)
        backup = d / entry.backup_rel_path
        live = self.home / entry.rel_path
        require_within(live.resolve(), [self.home])
        if entry.meta.type == "symlink":
            target = entry.meta.symlink_target or ""
            resolved = canonicalize(live.parent / target)
            if not is_within(resolved, [self.home]):
                log.warning("skip unsafe symlink %s -> %s", live, target)
                return
            if live.exists() and not live.is_symlink():
                self._fs.remove(live)
            self._fs.symlink(target, live)
        elif entry.meta.type == "file":
            self._fs.copy(backup, live)
            self._apply_meta(live, entry.meta)

    def _apply_meta(self, path: Path, meta: FileMeta) -> None:
        try:
            self._fs.chmod(path, meta.mode)
            self._fs.chown(path, meta.uid, meta.gid)
        except (PermissionError, LookupError) as exc:
            log.warning("could not fully apply owner/mode to %s: %s", path, exc)
        self._fs.utime(path, meta.mtime_ns)

    # -- listing / lifecycle --------------------------------------------------

    def list_all(self) -> list[SnapshotManifest]:
        root = self.snapshots_root()
        if not root.is_dir():
            return []
        out = []
        for d in sorted(root.iterdir()):
            mf = d / "manifest.json"
            if mf.exists():
                out.append(SnapshotManifest.from_json(json.loads(self._fs.read(mf))))
        out.sort(key=lambda m: m.timestamp)
        return out

    def get(self, snap_id: str) -> SnapshotManifest:
        for m in self.list_all():
            if m.timestamp == snap_id:
                return m
        raise SnapshotError(f"unknown snapshot: {snap_id}")

    def latest(self) -> SnapshotManifest | None:
        snaps = self.list_all()
        return snaps[-1] if snaps else None

    def resolve_id(self, snap_id: str | None) -> str:
        if snap_id is not None:
            return snap_id
        latest = self.latest()
        if latest is None:
            raise SnapshotError("no snapshots available")
        return latest.timestamp

    def delete(self, snap_id: str) -> None:
        d = self._dir_for(snap_id)  # scope check happens inside
        if not d.exists():
            raise SnapshotError(f"unknown snapshot: {snap_id}")
        self._fs.remove(d)
        log.info("deleted snapshot %s", snap_id)

    def prune(self, *, dry_run: bool = False) -> list[str]:
        """Keep: all pinned + newest RETENTION_KEEP unpinned + anything within
        RETENTION_DAYS. Delete the rest. Returns removed ids."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(days=RETENTION_DAYS)
        unpinned_newest_first = [m for m in reversed(self.list_all()) if not m.pinned]
        keep_ids: set[str] = set()
        for i, m in enumerate(unpinned_newest_first):
            created = _parse_ts(m.timestamp)
            if i < RETENTION_KEEP or created >= cutoff:
                keep_ids.add(m.timestamp)
        doomed = [
            m.timestamp for m in self.list_all() if not m.pinned and m.timestamp not in keep_ids
        ]
        if not dry_run:
            for sid in doomed:
                self.delete(sid)
        return doomed


def _parse_ts(sid: str) -> datetime:
    """Parse an id like 2026-08-21T12-04-33Z, tolerating collision suffixes (-N)."""
    for candidate in (sid, sid.rsplit("-", 1)[0]):
        try:
            return datetime.strptime(candidate, "%Y-%m-%dT%H-%M-%SZ").replace(tzinfo=UTC)
        except ValueError:
            continue
    return datetime.min.replace(tzinfo=UTC)
