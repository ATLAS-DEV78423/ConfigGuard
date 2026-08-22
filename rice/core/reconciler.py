"""Reconciliation (spec §18/§19).

V1 decision table (locked; no automatic semantic merges):
- UNCHANGED      -> skip.
- CHANGED        -> decide(): keep-mine (default) | use-new | abort.
- MISSING_CURRENT-> auto restore (the file is ours; safe).
- TYPE_CHANGED   -> decide() like a conflict.

The DECIDER is always injected. The CLI supplies an interactive prompt or a
non-interactive keep-mine default; tests inject fakes. Core stays IO-free.
"""

from __future__ import annotations

import difflib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from rice.core.fs import Filesystem
from rice.core.snapshot import ManifestEntry, SnapshotStore

log = logging.getLogger("rice.reconcile")


class Verdict(Enum):
    UNCHANGED = "unchanged"
    CHANGED = "changed"
    MISSING_CURRENT = "missing-current"
    TYPE_CHANGED = "type-changed"


class Action(Enum):
    KEEP_MINE = "keep-mine"
    USE_NEW = "use-new"
    ABORT = "abort"


@dataclass(frozen=True)
class Finding:
    entry: ManifestEntry
    verdict: Verdict
    unified_diff: str | None = None


@dataclass
class Resolution:
    kept_mine: int = 0
    used_new: int = 0
    unchanged: int = 0
    restored_missing: int = 0


Decider = Callable[[Finding], Action]


class ConflictAborted(Exception):
    """Raised when the decider aborts; caller rolls back to the snapshot."""

    def __init__(self, finding: Finding) -> None:
        super().__init__(f"aborted at {finding.entry.rel_path}")
        self.finding = finding


def _text_diff(old: bytes, new: bytes) -> str | None:
    try:
        old_lines = old.decode("utf-8").splitlines(keepends=True)
        new_lines = new.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None  # binary config: no textual diff in V1
    return "".join(
        difflib.unified_diff(old_lines, new_lines, fromfile="snapshot", tofile="current")
    )


class Reconciler:
    def __init__(self, fs: Filesystem, store: SnapshotStore) -> None:
        self._fs = fs
        self._store = store

    # -- analysis -----------------------------------------------------------

    def analyze(self, snap_id: str) -> list[Finding]:
        """Read-only comparison between snapshot and current configs."""
        manifest = self._store.verify(snap_id)
        findings: list[Finding] = []
        for entry in manifest.files:
            live = self._store.home / entry.rel_path
            if not self._fs.exists(live):
                findings.append(Finding(entry, Verdict.MISSING_CURRENT))
                continue
            live_meta = self._fs.metadata(live)
            if live_meta.type != entry.meta.type:
                findings.append(Finding(entry, Verdict.TYPE_CHANGED))
                continue
            if entry.meta.type != "file":
                continue  # symlinks/dirs with same type: nothing to reconcile textually
            live_sha = self._fs.sha256(live)
            if entry.meta.sha256 and live_sha == entry.meta.sha256:
                findings.append(Finding(entry, Verdict.UNCHANGED))
                continue
            diff = _text_diff(
                self._fs.read(self._store.snapshots_root() / snap_id / entry.backup_rel_path),
                self._fs.read(live),
            )
            findings.append(Finding(entry, Verdict.CHANGED, unified_diff=diff))
        return findings

    # -- resolution ---------------------------------------------------------

    def resolve(
        self,
        snap_id: str,
        decide: Decider,
        on_decision: Callable[[dict[str, str]], None] | None = None,
    ) -> Resolution:
        self._store.verify(snap_id)  # integrity gate (SR-005)
        resolution = Resolution()
        for finding in self.analyze(snap_id):
            entry = finding.entry
            record: dict[str, str] = {"path": entry.rel_path, "verdict": finding.verdict.value}

            if finding.verdict is Verdict.UNCHANGED:
                resolution.unchanged += 1
                record["action"] = "skip"

            elif finding.verdict is Verdict.MISSING_CURRENT:
                self._store.restore_entry(snap_id, entry)
                resolution.restored_missing += 1
                record["action"] = "auto-restore"

            else:  # CHANGED or TYPE_CHANGED — a real decision point
                action = decide(finding)
                if action is Action.ABORT:
                    record["action"] = "abort"
                    if on_decision:
                        on_decision(record)
                    raise ConflictAborted(finding)
                if action is Action.USE_NEW:
                    resolution.used_new += 1
                    record["action"] = "use-new"  # leave current file as-is
                else:  # KEEP_MINE
                    self._store.restore_entry(snap_id, entry)
                    record["action"] = "keep-mine"
                    resolution.kept_mine += 1
                log.info(
                    "decision %s: %s (%s)", entry.rel_path, record["action"], finding.verdict.value
                )

            if on_decision:
                on_decision(record)
        return resolution
