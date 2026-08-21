"""Protected update orchestration (spec §17/§21) + locking + recovery.

The state machine lives in core.state; this module drives it:
PREPARE -> SNAPSHOT -> VERIFY -> UPDATE -> ANALYZE/RECONCILE -> VALIDATE ->
COMMIT, with every failure routed to a known state. Nothing mutates user
configs before a verified snapshot exists (FR-001/002).
"""

from __future__ import annotations

import fcntl
import logging
import os
import signal
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from rice.core.config import RiceConfig, protected_paths
from rice.core.detector import Detector
from rice.core.errors import (
    ConfigError,
    ConflictError,
    RiceError,
    SudoError,
    UpdateFailedError,
    ValidationError_,
)
from rice.core.fs import Filesystem
from rice.core.reconciler import Action, ConflictAborted, Finding, Reconciler
from rice.core.runner import CommandRunner
from rice.core.snapshot import SnapshotStore
from rice.core.state import TransactionJournal, TransactionState
from rice.core.validator import Validator
from rice.pkgmanagers.apt import AptPackageManager, looks_like_sudo_failure

log = logging.getLogger("rice.update")


class _Interrupted(SystemExit):
    """Raised by signal handlers to unwind cleanly."""


# ---- locking (FR-030) ---------------------------------------------------------


class TransactionLock:
    """flock-based exclusive lock. Auto-releases if the process dies."""

    def __init__(self, data_dir: Path) -> None:
        self.path = data_dir / "transaction.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise RiceError(
                "another rice transaction appears to be running; "
                "if you are sure none is, remove the stale lock"
            ) from None
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self) -> TransactionLock:
        self.acquire()
        return self

    def __exit__(self, *exc: object) -> None:
        self.release()


@contextmanager
def signal_safety():  # type: ignore[no-untyped-def]
    """SIGINT/SIGTERM/SIGHUP -> clean unwind. Atomic writes + persisted journal
    mean an interrupt at ANY point leaves recoverable state (FR-031)."""

    def handler(signum: int, _frame: object) -> None:
        log.warning("received signal %d; unwinding cleanly", signum)
        raise _Interrupted(130)

    installed: list[tuple[int, object]] = []
    for sig_name in ("SIGINT", "SIGTERM", "SIGHUP"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            prev = signal.signal(sig, handler)
            installed.append((sig, prev))
        except (ValueError, OSError):
            continue  # non-main thread or unsupported platform
    try:
        yield
    finally:
        for sig, prev in installed:
            try:
                signal.signal(sig, prev)  # type: ignore[arg-type]
            except (ValueError, OSError):
                pass


# ---- preflight -----------------------------------------------------------------


@dataclass(frozen=True)
class PreflightReport:
    ok: bool
    problems: list[str]


def preflight(
    det: Detector,
    cfg: RiceConfig | None,
    pm_present: bool,
    *,
    need_pm: bool = True,
) -> PreflightReport:
    problems: list[str] = []
    detection = det.system()
    if not detection.supported:
        problems.append(
            f"unsupported distro '{detection.distro_id}': V1 targets Ubuntu 24.04+/Debian 13+"
        )
    if cfg is None:
        problems.append("no rice configuration; run 'rice init'")
    else:
        roots = protected_paths(cfg)
        missing = [p for p in roots if not p.exists()]
        if roots and len(missing) == len(roots):
            problems.append("none of the protected paths exist")
        elif missing:
            log.warning("%d protected path(s) missing and will be skipped", len(missing))
    if need_pm and not pm_present:
        problems.append("apt not found on this system")
    return PreflightReport(ok=not problems, problems=problems)


# ---- recovery (FR-004, idempotent) ----------------------------------------------


def recover_pending(
    journal: TransactionJournal,
    store: SnapshotStore,
    *,
    apply: bool = False,
) -> tuple[str, bool]:
    """Report (and optionally resolve) an interrupted transaction.

    Returns (state_name, recovered). apply=True restores the referenced
    snapshot and walks the journal to KNOWN_STATE. Safe to run repeatedly.
    """
    rec = journal.load()
    if rec is None:
        return ("IDLE", False)

    if rec.state is TransactionState.PREPARING:
        # Crash before any snapshot existed: nothing to restore.
        if apply:
            journal.clear()
        return (rec.state.value, apply)

    if rec.snapshot_id is None:
        if apply:
            journal.clear()
        return (rec.state.value, apply)

    if apply:
        store.restore(rec.snapshot_id)  # verifies integrity first (SR-005)
        journal.mark_recovered()
        journal.clear()
    return (rec.state.value, apply)


# ---- the main flow ---------------------------------------------------------------


def run_protected_update(
    *,
    fs: Filesystem,
    cfg: RiceConfig,
    runner: CommandRunner,
    home: Path,
    interactive: bool,
    dry_run: bool = False,
    decide: Callable[[Finding], Action] | None = None,
    on_decision: Callable[[dict], None] | None = None,
    ask_rollback: Callable[[list], bool] | None = None,
) -> int:
    """Full PREPARE->...->COMMITTED transaction. Returns process exit code."""
    store = SnapshotStore(fs, cfg.data_dir, home)
    journal = TransactionJournal(fs, cfg.data_dir)
    det = Detector(fs, home, runner)
    txn_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")

    if dry_run:
        report = preflight(det, cfg, AptPackageManager.detect(runner))
        if not report.ok:
            for p in report.problems:
                log.error("preflight: %s", p)
            return 3
        manifest = store.create(protected_paths(cfg), desktop=det.system().desktop, dry_run=True)
        log.info("dry run: would snapshot %d files, then update via apt", len(manifest.files))
        return 0

    with signal_safety(), TransactionLock(cfg.data_dir):
        journal.begin(txn_id)  # PREPARING

        report = preflight(det, cfg, AptPackageManager.detect(runner))
        if not report.ok:
            journal.clear()
            raise ConfigError("; ".join(report.problems))

        manifest = store.create(protected_paths(cfg), desktop=det.system().desktop)
        journal.set_state(TransactionState.SNAPSHOTTED)
        journal.record("snapshot_id", manifest.timestamp)

        # ---- UPDATE -----------------------------------------------------
        journal.set_state(TransactionState.UPDATING)
        result = AptPackageManager().update(runner)
        if not result.success:
            message = result.stderr_tail.strip() or f"apt exited {result.exit_code}"
            journal.record("error", message[:500])
            journal.set_state(TransactionState.UPDATE_FAILED)
            journal.set_state(TransactionState.KNOWN_STATE)
            journal.clear()
            if looks_like_sudo_failure(result):
                raise SudoError(f"update failed (permissions): {message}")
            hint = f"snapshot {manifest.timestamp} is available for 'rice restore'"
            raise UpdateFailedError(f"{message}; {hint}")

        journal.set_state(TransactionState.UPDATED)

        # ---- RECONCILE ---------------------------------------------------
        journal.set_state(TransactionState.RECONCILING)
        reconciler = Reconciler(fs, store)

        def decider(finding: Finding) -> Action:
            if decide is not None:
                return decide(finding)
            return Action.KEEP_MINE  # conservative default (spec §18)

        try:
            resolution = reconciler.resolve(manifest.timestamp, decider, on_decision)
        except ConflictAborted as aborted:
            journal.record("decisions", {"path": aborted.finding.entry.rel_path, "action": "abort"})
            journal.set_state(TransactionState.CONFLICT)
            store.restore(manifest.timestamp)  # rollback (§19 option 4)
            journal.set_state(TransactionState.RECOVERY)
            journal.set_state(TransactionState.KNOWN_STATE)
            journal.clear()
            raise ConflictError(
                f"aborted by user at {aborted.finding.entry.rel_path}; "
                f"rolled back to snapshot {manifest.timestamp}"
            ) from aborted

        journal.record("packages", result.upgraded)

        # ---- VALIDATE ------------------------------------------------------
        journal.set_state(TransactionState.VALIDATING)
        validator = Validator(fs, runner, home)
        validation = validator.validate_all(list(cfg.protected.keys()))
        failures = Validator.failures(validation)
        if failures:
            names = ", ".join(r.app for r in failures)
            do_rollback = True
            if interactive and ask_rollback is not None:
                do_rollback = ask_rollback(failures)
            if do_rollback:
                journal.set_state(TransactionState.RECOVERY)
                store.restore(manifest.timestamp)
                journal.set_state(TransactionState.KNOWN_STATE)
                journal.clear()
                raise ValidationError_(
                    f"validation failed for {names}; restored snapshot {manifest.timestamp}"
                )
            journal.set_state(TransactionState.KNOWN_STATE)
            journal.clear()
            raise ValidationError_(f"validation failed for {names}; kept current configs")

        journal.mark_finished_ok()
        log.info(
            "committed: %s upgraded, %d unchanged, %d kept-mine, %d use-new",
            len(result.upgraded),
            resolution.unchanged,
            resolution.kept_mine,
            resolution.used_new,
        )
        return 0
