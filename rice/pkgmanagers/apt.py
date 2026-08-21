"""APT implementation (spec §16).

Conservative orchestration, exactly:
    sudo env DEBIAN_FRONTEND=noninteractive apt update
    sudo env DEBIAN_FRONTEND=noninteractive apt upgrade -y
- No apt-get. No dist-upgrade/full-upgrade. No --force-conf* policy flags.
- dpkg lock held by someone else -> report and stop (FR-032); never bypass.
- `env VAR=x` form carries the frontend setting THROUGH sudo without a shell.
"""

from __future__ import annotations

import re

from rice.core.runner import CommandRunner, RunResult
from rice.pkgmanagers.base import PackageManager, UpdateResult, tail

_DPKG_LOCK = "/var/lib/dpkg/lock-frontend"
_SETUP_RE = re.compile(r"^Setting up ([A-Za-z0-9][A-Za-z0-9.+~:-]*)", re.MULTILINE)
_SUDO_HINTS = ("a password is required", "sudo:", "not in the sudoers file")
_ENV = ["env", "DEBIAN_FRONTEND=noninteractive"]


class AptPackageManager(PackageManager):
    name = "apt"

    def __init__(self) -> None:
        self._last: UpdateResult | None = None

    @classmethod
    def detect(cls, runner: CommandRunner) -> bool:
        return runner.capture(["apt", "--version"], timeout=15).ok

    @staticmethod
    def _lock_held(runner: CommandRunner) -> bool:
        """fuser exit 0 == some process holds the lock. fuser missing (127)
        or other failures -> assume not held; apt will fail on its own."""
        probe = runner.capture(["fuser", _DPKG_LOCK], timeout=10)
        return probe.returncode == 0

    def update(self, runner: CommandRunner) -> UpdateResult:
        if self._lock_held(runner):
            result = UpdateResult(
                success=False,
                exit_code=100,
                stderr_tail="another package manager is running "
                f"({_DPKG_LOCK} held); rice will not bypass it",
            )
            self._last = result
            return result

        r1 = runner.privileged([*_ENV, "apt", "update"], timeout=None)
        if not r1.ok:
            result = self._failure(r1)
            self._last = result
            return result

        r2 = runner.privileged([*_ENV, "apt", "upgrade", "-y"], timeout=None)
        result = (
            self._success(r2)
            if r2.ok
            else self._failure(r2, prior_stdout=r1.stdout)
        )
        self._last = result
        return result

    def changed_packages(self) -> list[str]:
        if self._last is None:
            return []
        return sorted(set(_SETUP_RE.findall(self._last.stdout_tail)))

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _success(r: RunResult) -> UpdateResult:
        return UpdateResult(
            success=True,
            exit_code=r.returncode,
            upgraded=sorted(set(_SETUP_RE.findall(r.stdout))),
            stdout_tail=tail(r.stdout),
            stderr_tail=tail(r.stderr),
        )

    @staticmethod
    def _failure(r: RunResult, prior_stdout: str = "") -> UpdateResult:
        return UpdateResult(
            success=False,
            exit_code=r.returncode,
            stdout_tail=tail(prior_stdout + r.stdout),
            stderr_tail=tail(r.stderr),
        )


def looks_like_sudo_failure(result: UpdateResult) -> bool:
    """Single heuristic used by the updater to map exit code 9."""
    blob = (result.stderr_tail or "").lower()
    return any(hint in blob for hint in _SUDO_HINTS)
