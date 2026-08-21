"""Command execution abstraction — the ONLY module allowed to call subprocess.

Rules (NFR-003/004/005): argv lists only, never shell mode, never shell
strings. ``privileged()`` prefixes sudo; rice never sees or stores passwords.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

from rice.core.errors import RiceError

_TIMEOUT_RC = 124  # conventional "timed out" exit code


@dataclass(frozen=True)
class RunResult:
    """Outcome of one external command."""

    args: list[str]
    returncode: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = field(default=False)

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner:
    """Runs external commands as argv lists; captures output."""

    def run(
        self,
        args: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> RunResult:
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise TypeError("args must be a list[str] (never a shell string)")
        env: dict[str, str] | None = None
        if env_extra:
            env = {**os.environ, **env_extra}
        try:
            proc = subprocess.run(  # noqa: S603 - argv list, no shell, by design
                args,
                capture_output=True,
                text=True,
                shell=False,
                timeout=timeout,
                env=env,
                check=False,
            )
            result = RunResult(
                args=list(args),
                returncode=proc.returncode,
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
            )
        except subprocess.TimeoutExpired as exc:
            result = RunResult(
                args=list(args),
                returncode=_TIMEOUT_RC,
                stdout=(exc.stdout or b"").decode(errors="replace") if exc.stdout else "",
                stderr=f"timed out after {timeout}s",
                timed_out=True,
            )
        except (OSError, ValueError) as exc:
            # Missing binary, permission denied, etc. — never crash the caller.
            result = RunResult(args=list(args), returncode=127, stderr=str(exc))
        if check and not result.ok:
            raise RiceError(f"command failed ({result.returncode}): {' '.join(result.args)}")
        return result

    def capture(self, args: list[str], *, timeout: float | None = None) -> RunResult:
        """Run and collect output; never raises for non-zero exits."""
        return self.run(args, check=False, timeout=timeout)

    def privileged(
        self,
        args: list[str],
        *,
        timeout: float | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> RunResult:
        """Run under sudo. Used ONLY for the package-manager invocation."""
        return self.run(["sudo", *args], check=False, timeout=timeout, env_extra=env_extra)


class FakeCommandRunner(CommandRunner):
    """Scripted runner for tests: records calls, never executes anything.

    Either pass canned ``results`` (popped in order) or a ``script`` callable
    mapping argv -> RunResult (lets integration tests mutate fixture files
    "when apt runs"). Default response is an empty success.
    """

    def __init__(
        self,
        results: list[RunResult] | None = None,
        script: Callable[[list[str]], RunResult] | None = None,
    ) -> None:
        self._results = list(results or [])
        self._script = script
        self.calls: list[list[str]] = []
        self.envs: list[dict[str, str] | None] = []

    def run(
        self,
        args: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> RunResult:
        self.calls.append(list(args))
        self.envs.append(dict(env_extra) if env_extra else None)
        if self._script is not None:
            result = self._script(args)
        elif self._results:
            result = self._results.pop(0)
        else:
            result = RunResult(args=list(args), returncode=0)
        if check and not result.ok:
            raise RiceError(f"command failed ({result.returncode}): {' '.join(result.args)}")
        return result
