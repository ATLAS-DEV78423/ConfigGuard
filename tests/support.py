"""Shared test doubles. Lives under tests/ deliberately: never ships to users."""

from __future__ import annotations

from collections.abc import Callable

from rice.core.errors import RiceError
from rice.core.runner import RunResult


class FakeCommandRunner:
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

    def run(
        self,
        args: list[str],
        *,
        check: bool = False,
        timeout: float | None = None,
    ) -> RunResult:
        self.calls.append(list(args))
        if self._script is not None:
            result = self._script(args)
        elif self._results:
            result = self._results.pop(0)
        else:
            result = RunResult(args=list(args), returncode=0)
        if check and not result.ok:
            raise RiceError(f"command failed ({result.returncode}): {' '.join(result.args)}")
        return result

    def capture(self, args: list[str], *, timeout: float | None = None) -> RunResult:
        return self.run(args, check=False, timeout=timeout)

    def privileged(self, args: list[str], *, timeout: float | None = None) -> RunResult:
        return self.run(["sudo", *args], check=False, timeout=timeout)
