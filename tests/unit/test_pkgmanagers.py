"""Unit tests for the APT adapter (FakeCommandRunner only — never real sudo)."""

from __future__ import annotations

import pytest

from rice.core.runner import FakeCommandRunner, RunResult
from rice.pkgmanagers.apt import AptPackageManager, looks_like_sudo_failure
from rice.pkgmanagers.base import UpdateResult

UPGRADE_OK = """
Reading package lists... Done
The following packages will be upgraded:
  hyprland waybar
Setting up hyprland (0.55.1-1)
Setting up waybar (0.14.0-2)
Processing triggers for man-db (2.13.0-1)
"""


def test_detect_true_when_apt_present() -> None:
    fake = FakeCommandRunner()  # default: success
    assert AptPackageManager.detect(fake)


def test_update_success_issues_two_privileged_calls_with_env() -> None:
    fake = FakeCommandRunner(
        results=[
            RunResult(args=[], returncode=0),                      # fuser probe
            RunResult(args=[], returncode=0, stdout="Hit:1"),      # apt update
            RunResult(args=[], returncode=0, stdout=UPGRADE_OK),   # apt upgrade
        ]
    )
    pm = AptPackageManager()
    result = pm.update(fake)

    assert result.success is True
    assert set(result.upgraded) == {"hyprland", "waybar"}

    # Call 1: lock probe (NOT privileged). Calls 2+3: sudo env ... apt ...
    assert fake.calls[0][0] == "fuser"
    for call in fake.calls[1:]:
        assert call[0] == "sudo"
        assert "DEBIAN_FRONTEND=noninteractive" in call
    assert fake.calls[1][-2:] == ["apt", "update"]
    assert fake.calls[2][-3:] == ["apt", "upgrade", "-y"]
    # Never apt-get, never dist-upgrade:
    joined = [" ".join(c) for c in fake.calls]
    assert all("apt-get" not in j for j in joined)
    assert all("dist-upgrade" not in j and "full-upgrade" not in j for j in joined)


def test_dpkg_lock_held_reports_without_running_apt() -> None:
    fake = FakeCommandRunner(
        results=[RunResult(args=[], returncode=0)]  # fuser says lock HELD
    )
    pm = AptPackageManager()
    result = pm.update(fake)

    assert result.success is False
    assert "another package manager is running" in result.stderr_tail
    assert len(fake.calls) == 1  # apt was NEVER invoked


def test_upgrade_failure_is_reported_not_raised() -> None:
    fake = FakeCommandRunner(
        results=[
            RunResult(args=[], returncode=0),
            RunResult(args=[], returncode=0),
            RunResult(args=[], returncode=100, stderr="E: Sub-process failed"),
        ]
    )
    pm = AptPackageManager()
    result = pm.update(fake)
    assert result.success is False
    assert result.exit_code == 100
    assert "Sub-process failed" in result.stderr_tail


def test_changed_packages_empty_before_any_update() -> None:
    assert AptPackageManager().changed_packages() == []


def test_looks_like_sudo_failure() -> None:
    sudo_fail = UpdateResult(success=False, exit_code=1,
                             stderr_tail="sudo: a password is required")
    other_fail = UpdateResult(success=False, exit_code=100,
                              stderr_tail="E: unable to fetch")
    assert looks_like_sudo_failure(sudo_fail) is True
    assert looks_like_sudo_failure(other_fail) is False
