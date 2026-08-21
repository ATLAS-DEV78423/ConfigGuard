"""Full update-transaction scenarios with a scripted FakeCommandRunner.

No sudo, no apt — every external effect is simulated. The "update clobbers a
config" scenario is modeled by mutating the fixture file when the upgrade
call runs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from rice.core.config import RiceConfig
from rice.core.errors import (
    ConflictError,
    RiceError,
    SudoError,
    UpdateFailedError,
    ValidationError_,
)
from rice.core.fs import Filesystem
from rice.core.reconciler import Action
from rice.core.updater import TransactionLock, recover_pending, run_protected_update
from rice.core.state import TransactionJournal

OK = 0


def make_env(tmp_path: Path) -> tuple[Filesystem, RiceConfig, Path]:
    fs = Filesystem()
    home = tmp_path / "home"
    data = tmp_path / "data"
    hypr = home / ".config" / "hypr"
    hypr.mkdir(parents=True)
    (home / ".config" / "waybar").mkdir(parents=True)
    (home / ".config" / "waybar" / "config").write_text('{"clock": {}}')
    (hypr / "hyprland.conf").write_text("monitor=DP-1@144\n")
    cfg = RiceConfig(
        data_dir=data,
        protected={"hyprland": [home / ".config/hypr"], "waybar": [home / ".config/waybar"]},
    )
    return fs, cfg, home


def script_apt(
    on_upgrade: Callable[[], None] | None = None,
    *,
    update_rc: int = OK,
    upgrade_rc: int = OK,
    upgrade_stderr: str = "",
) -> Callable[[list[str]], object]:
    """Builds a runner script that answers lock probe/update/upgrade/validation."""

    from rice.core.runner import RunResult

    def script(args: list[str]) -> RunResult:
        joined = " ".join(args)
        if args[0] == "fuser":
            return RunResult(args=args, returncode=1)  # no dpkg lock held
        if "apt update" in joined and "sudo" in joined:
            return RunResult(args=args, returncode=update_rc)
        if "apt upgrade" in joined:
            if upgrade_rc == OK and on_upgrade is not None:
                on_upgrade()  # simulate the package touching user config
            return RunResult(args=args, returncode=upgrade_rc, stderr=upgrade_stderr)
        # validation probes: hyprctl/waybar/wofi all healthy unless overridden
        return RunResult(args=args, returncode=0)

    return script


def test_success_path_restores_clobbered_config(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)
    conf = home / ".config/hypr/hyprland.conf"

    def clobber() -> None:
        conf.write_text("monitor=DP-1@165\n")  # the "update" overwrites the rice

    runner = FakeCommandRunner(script=script_apt(on_upgrade=clobber))
    code = run_protected_update(
        fs=fs, cfg=cfg, runner=runner, home=home, interactive=False,
        decide=lambda _f: Action.KEEP_MINE,
    )
    assert code == 0
    assert "@144" in conf.read_text()  # user config survived (FR-020)
    assert TransactionJournal(fs, cfg.data_dir).load() is None  # committed + cleared


def test_apt_failure_exits_5_without_reconciling(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)
    conf = home / ".config/hypr/hyprland.conf"

    runner = FakeCommandRunner(script=script_apt(upgrade_rc=100, upgrade_stderr="E: broke"))
    with pytest.raises(UpdateFailedError) as excinfo:
        run_protected_update(fs=fs, cfg=cfg, runner=runner, home=home, interactive=False)

    assert excinfo.value.exit_code == 5
    assert "@144" in conf.read_text()          # untouched (FR-018)
    assert "rice restore" in str(excinfo.value)  # recovery hint present
    assert TransactionJournal(fs, cfg.data_dir).load() is None  # known state


def test_sudo_failure_maps_to_exit_9(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)
    runner = FakeCommandRunner(
        script=script_apt(upgrade_rc=1, upgrade_stderr="sudo: a password is required")
    )
    with pytest.raises(SudoError) as excinfo:
        run_protected_update(fs=fs, cfg=cfg, runner=runner, home=home, interactive=False)
    assert excinfo.value.exit_code == 9


def test_dpkg_lock_blocks_update_before_any_apt_call(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)

    from rice.core.runner import RunResult

    calls: list[list[str]] = []

    def script(args: list[str]) -> RunResult:
        calls.append(args)
        joined = " ".join(args)
        if args[0] == "fuser":
            return RunResult(args=args, returncode=0)  # LOCK HELD
        if args[0] == "apt" and "--version" in args:
            return RunResult(args=args, returncode=0)  # preflight detect
        if "sudo" in joined and "apt" in joined:
            raise AssertionError("apt must not be invoked while lock is held")
        return RunResult(args=args, returncode=0)

    with pytest.raises(UpdateFailedError):
        run_protected_update(fs=fs, cfg=cfg, runner=FakeCommandRunner(script=script), home=home,
                             interactive=False)
    apt_calls = [c for c in calls if "sudo" in c]
    assert apt_calls == []  # only probes ran, never privileged apt (FR-032)


def test_validation_failure_auto_rollbacks_exit_7(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)
    conf = home / ".config/hypr/hyprland.conf"

    from rice.core.runner import RunResult

    def script(args: list[str]) -> RunResult:
        joined = " ".join(args)
        if args[0] == "fuser":
            return RunResult(args=args, returncode=1)
        if "apt update" in joined:
            return RunResult(args=args, returncode=0)
        if "apt upgrade" in joined:
            conf.write_text("monitor=DP-1@165\n")
            return RunResult(args=args, returncode=0)
        if args[:1] == ["hyprctl"] and "reload" in joined:
            return RunResult(args=args, returncode=1, stderr="invalid config")  # FAIL validation
        return RunResult(args=args, returncode=0)

    with pytest.raises(ValidationError_) as excinfo:
        run_protected_update(fs=fs, cfg=cfg, runner=FakeCommandRunner(script=script), home=home,
                             interactive=False)

    assert excinfo.value.exit_code == 7
    assert "@144" in conf.read_text()  # rolled back to snapshot (FR-024)


def test_conflict_abort_rolls_back_exit_6(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)
    conf = home / ".config/hypr/hyprland.conf"

    def clobber() -> None:
        conf.write_text("monitor=DP-1@165\n")

    runner = FakeCommandRunner(script=script_apt(on_upgrade=clobber))
    with pytest.raises(ConflictError) as excinfo:
        run_protected_update(
            fs=fs, cfg=cfg, runner=runner, home=home, interactive=False,
            decide=lambda _f: Action.ABORT,
        )

    assert excinfo.value.exit_code == 6
    assert "@144" in conf.read_text()  # rolled back (§19 option 4)


def test_concurrent_transaction_rejected(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)
    with TransactionLock(cfg.data_dir):  # simulate another rice running
        runner = FakeCommandRunner(script=script_apt())
        with pytest.raises(RiceError, match="another rice transaction"):
            run_protected_update(fs=fs, cfg=cfg, runner=runner, home=home, interactive=False)


def test_pending_recovery_applied_and_idempotent(tmp_path: Path) -> None:
    fs, cfg, home = make_env(tmp_path)
    store_journal_setup(fs, cfg, home)
    journal = TransactionJournal(fs, cfg.data_dir)
    pending = journal.load()
    assert pending is not None and pending.state.value == "UPDATING"

    state, recovered = recover_pending(journal, _store_for(cfg, home), apply=True)
    assert state == "UPDATING" and recovered is True
    conf = home / ".config/hypr/hyprland.conf"
    assert "@144" in conf.read_text()

    # Idempotent: second pass finds nothing left to do.
    state2, recovered2 = recover_pending(journal, _store_for(cfg, home), apply=True)
    assert state2 == "IDLE" and recovered2 is False


def store_journal_setup(fs: Filesystem, cfg: RiceConfig, home: Path) -> None:
    """Craft an interrupted UPDATING transaction referencing a real snapshot."""
    from datetime import datetime, timezone

    from rice.core.snapshot import SnapshotStore
    from rice.core.state import TransactionState

    store = SnapshotStore(fs, cfg.data_dir, home)
    snap = store.create([home / ".config/hypr"])
    (home / ".config/hypr/hyprland.conf").write_text("monitor=BROKEN\n")

    journal = TransactionJournal(fs, cfg.data_dir)
    rec = journal.begin(f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}")
    journal.record("snapshot_id", snap.timestamp)
    journal.set_state(TransactionState.UPDATING)
    del rec


def _store_for(cfg: RiceConfig, home: Path) -> object:
    from rice.core.snapshot import SnapshotStore

    return SnapshotStore(Filesystem(), cfg.data_dir, home)
