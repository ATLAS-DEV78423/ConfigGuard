"""Transaction state machine + persisted journal (spec §17).

Invariant: every transition is validated against ALLOWED and persisted to
``<data_dir>/transactions/<txn_id>.json`` (atomic write) BEFORE any action is
taken in the new state. A crash at any point leaves a readable journal that
``status``/``doctor`` use to report and recover.
"""

from __future__ import annotations

import json
from collections.abc import Any
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from rice.core.errors import RiceError
from rice.core.fs import Filesystem


class TransactionState(str, Enum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    SNAPSHOTTED = "SNAPSHOTTED"
    UPDATING = "UPDATING"
    UPDATED = "UPDATED"
    RECONCILING = "RECONCILING"
    CONFLICT = "CONFLICT"
    VALIDATING = "VALIDATING"
    COMMITTED = "COMMITTED"
    UPDATE_FAILED = "UPDATE_FAILED"
    RECOVERY = "RECOVERY"
    KNOWN_STATE = "KNOWN_STATE"


# Exactly the edges of the spec §17 diagram. Terminal states have no outgoing
# edges; failure states route through RECOVERY -> KNOWN_STATE.
ALLOWED: dict[TransactionState, frozenset[TransactionState]] = {
    TransactionState.IDLE: frozenset({TransactionState.PREPARING}),
    TransactionState.PREPARING: frozenset({TransactionState.SNAPSHOTTED}),
    TransactionState.SNAPSHOTTED: frozenset({TransactionState.UPDATING}),
    TransactionState.UPDATING: frozenset(
        {TransactionState.UPDATED, TransactionState.UPDATE_FAILED}
    ),
    TransactionState.UPDATED: frozenset({TransactionState.RECONCILING}),
    TransactionState.RECONCILING: frozenset(
        {TransactionState.VALIDATING, TransactionState.CONFLICT}
    ),
    TransactionState.CONFLICT: frozenset({TransactionState.RECOVERY, TransactionState.KNOWN_STATE}),
    TransactionState.VALIDATING: frozenset(
        {TransactionState.COMMITTED, TransactionState.RECOVERY}
    ),
    TransactionState.COMMITTED: frozenset(),
    TransactionState.UPDATE_FAILED: frozenset({TransactionState.KNOWN_STATE}),
    TransactionState.RECOVERY: frozenset({TransactionState.KNOWN_STATE}),
    TransactionState.KNOWN_STATE: frozenset(),
}

TERMINAL_STATES = frozenset({TransactionState.COMMITTED, TransactionState.KNOWN_STATE})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class TransactionRecord:
    """Persisted per-transaction record (spec §10)."""

    txn_id: str
    state: TransactionState = TransactionState.IDLE
    started_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    snapshot_id: str | None = None
    packages: list[str] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)  # metadata only, never contents
    error: str | None = None

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> TransactionRecord:
        raw = dict(raw)
        raw["state"] = TransactionState(raw.get("state", "IDLE"))
        return cls(**raw)


class TransactionJournal:
    """Reads/writes one JSON file per transaction under <data_dir>/transactions."""

    def __init__(self, fs: Filesystem, data_dir: Path) -> None:
        self._fs = fs
        self._dir = data_dir / "transactions"

    # -- paths --------------------------------------------------------------

    def _path_for(self, txn_id: str) -> Path:
        return self._dir / f"{txn_id}.json"

    # -- lifecycle ----------------------------------------------------------

    def begin(self, txn_id: str) -> TransactionRecord:
        if self.load() is not None:
            raise RiceError("a transaction is already in flight; run 'rice doctor'")
        rec = TransactionRecord(txn_id=txn_id, state=TransactionState.PREPARING)
        self._write(rec)
        return rec

    def set_state(self, state: TransactionState) -> None:
        rec = self._require()
        if state not in ALLOWED[rec.state]:
            raise RiceError(f"illegal transaction transition {rec.state.value} -> {state.value}")
        rec.state = state
        rec.updated_at = _now()
        self._write(rec)

    def record(self, key: str, value: Any) -> None:
        rec = self._require()
        if key == "decisions" and isinstance(value, dict):
            rec.decisions.append(value)
        elif hasattr(rec, key):
            setattr(rec, key, value)
        else:
            raise RiceError(f"unknown transaction field: {key}")
        rec.updated_at = _now()
        self._write(rec)

    def load(self) -> TransactionRecord | None:
        """Most recent non-terminal in-flight transaction, else None."""
        if not self._dir.is_dir():
            return None
        candidates: list[tuple[float, TransactionRecord]] = []
        for p in sorted(self._dir.glob("*.json")):
            try:
                rec = TransactionRecord.from_json(json.loads(self._fs.read(p)))
            except (ValueError, KeyError, TypeError):
                continue  # corrupt journal entry: skip, never crash status
            if rec.state not in TERMINAL_STATES:
                candidates.append((p.stat().st_mtime, rec))
        if not candidates:
            return None
        return max(candidates, key=lambda pair: pair[0])[1]

    def clear(self) -> None:
        rec = self.load()
        if rec is not None and self._path_for(rec.txn_id).exists():
            self._fs.remove(self._path_for(rec.txn_id))

    def mark_finished_ok(self) -> None:
        """COMMITTED then delete the journal (spec §11: deleted on COMMITTED)."""
        rec = self._require()
        if TransactionState.COMMITTED not in ALLOWED[rec.state]:
            raise RiceError(f"cannot commit from {rec.state.value}")
        rec.state = TransactionState.COMMITTED
        rec.updated_at = _now()
        self._write(rec)
        self.clear()

    # -- internals ----------------------------------------------------------

    def _require(self) -> TransactionRecord:
        rec = self.load()
        if rec is None:
            raise RiceError("no transaction in flight")
        return rec

    def _write(self, rec: TransactionRecord) -> None:
        self._fs.ensure_dir(self._dir)
        payload = json.dumps(rec.to_json(), indent=2).encode()
        self._fs.write_atomically(self._path_for(rec.txn_id), payload)
