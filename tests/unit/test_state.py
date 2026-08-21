"""State machine transitions + journal persistence/recovery contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rice.core.errors import RiceError
from rice.core.fs import Filesystem
from rice.core.state import TransactionJournal
from rice.core.state import TransactionState as TS


@pytest.fixture()
def journal(tmp_path: Path) -> TransactionJournal:
    return TransactionJournal(Filesystem(), tmp_path / "data")


def read_journal(data_dir: Path, txn_id: str) -> dict:
    return json.loads((data_dir / "transactions" / f"{txn_id}.json").read_text())


def test_happy_chain_persists_every_step(tmp_path: Path, journal: TransactionJournal) -> None:
    data = tmp_path / "data"
    rec = journal.begin("txn-1")
    assert rec.state == TS.PREPARING
    chain = [
        TS.SNAPSHOTTED,
        TS.UPDATING,
        TS.UPDATED,
        TS.RECONCILING,
        TS.VALIDATING,
        TS.COMMITTED,
    ]
    for state in chain:
        journal.set_state(state)
        on_disk = read_journal(data, "txn-1")
        assert on_disk["state"] == state.value
    # COMMITTED journals are deleted (spec §11).
    assert journal.load() is None
    assert not (data / "transactions" / "txn-1.json").exists()


def test_failure_paths_allowed(tmp_path: Path, journal: TransactionJournal) -> None:
    journal.begin("t")
    journal.set_state(TS.SNAPSHOTTED)
    journal.set_state(TS.UPDATING)
    journal.set_state(TS.UPDATE_FAILED)
    journal.set_state(TS.KNOWN_STATE)
    assert journal.load() is None  # terminal + cleared by caller normally


def test_illegal_transition_rejected(journal: TransactionJournal) -> None:
    journal.begin("t")
    with pytest.raises(RiceError, match="illegal"):
        journal.set_state(TS.COMMITTED)


def test_record_snapshot_and_decisions(tmp_path: Path, journal: TransactionJournal) -> None:
    journal.begin("t")
    journal.record("snapshot_id", "2026-08-21T12-04-33Z")
    journal.record("decisions", {"path": ".config/hypr/hyprland.conf", "action": "keep-mine"})
    raw = read_journal(tmp_path / "data", "t")
    assert raw["snapshot_id"] == "2026-08-21T12-04-33Z"
    assert raw["decisions"] == [{"path": ".config/hypr/hyprland.conf", "action": "keep-mine"}]


def test_load_reconstructs_crashed_transaction(tmp_path: Path, journal: TransactionJournal) -> None:
    data = tmp_path / "data"
    (data / "transactions").mkdir(parents=True)
    crash = {
        "txn_id": "crash-9",
        "state": "UPDATING",
        "started_at": "2026-08-21T10:00:00+00:00",
        "updated_at": "2026-08-21T10:01:00+00:00",
        "snapshot_id": "2026-08-21T09-59-00Z",
        "packages": [],
        "decisions": [],
        "error": None,
    }
    (data / "transactions" / "crash-9.json").write_text(json.dumps(crash))
    rec = journal.load()
    assert rec is not None
    assert rec.txn_id == "crash-9"
    assert rec.state == TS.UPDATING
    assert rec.snapshot_id == "2026-08-21T09-59-00Z"


def test_begin_refuses_when_in_flight(journal: TransactionJournal) -> None:
    journal.begin("t")
    with pytest.raises(RiceError, match="already in flight"):
        journal.begin("t2")


def test_clear_is_idempotent(journal: TransactionJournal) -> None:
    journal.begin("t")
    journal.clear()
    journal.clear()  # no error
    assert journal.load() is None


def test_corrupt_journal_entries_skipped(tmp_path: Path, journal: TransactionJournal) -> None:
    d = tmp_path / "data" / "transactions"
    d.mkdir(parents=True)
    (d / "bad.json").write_text("{not json")
    good = {
        "txn_id": "ok",
        "state": "RECONCILING",
        "started_at": "x",
        "updated_at": "y",
        "snapshot_id": None,
        "packages": [],
        "decisions": [],
        "error": None,
    }
    (d / "ok.json").write_text(json.dumps(good))
    rec = journal.load()
    assert rec is not None and rec.txn_id == "ok"


def test_mark_finished_ok_requires_committable_state(journal: TransactionJournal) -> None:
    journal.begin("t")
    with pytest.raises(RiceError):
        journal.mark_finished_ok()
