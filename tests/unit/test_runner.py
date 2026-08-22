"""CommandRunner contracts: argv-only, sudo prefix, env merge, no shell."""

from __future__ import annotations

import subprocess
from typing import Any

import pytest
from support import FakeCommandRunner

from rice.core.errors import RiceError
from rice.core.runner import RunResult


def test_fake_records_calls_and_defaults_ok() -> None:
    fake = FakeCommandRunner()
    result = fake.run(["echo", "hi"])
    assert result.ok
    assert fake.calls == [["echo", "hi"]]


def test_canned_results_pop_in_order() -> None:
    fake = FakeCommandRunner(
        results=[
            RunResult(args=["a"], returncode=0),
            RunResult(args=["b"], returncode=3, stderr="nope"),
        ]
    )
    assert fake.run(["a"]).ok
    second = fake.run(["b"])
    assert not second.ok and second.stderr == "nope"


def test_privileged_prepends_sudo() -> None:
    fake = FakeCommandRunner()
    fake.privileged(["apt", "update"])
    assert fake.calls[0][0] == "sudo"
    assert fake.calls[0][-2:] == ["apt", "update"]


def test_check_raises_rice_error() -> None:
    fake = FakeCommandRunner(results=[RunResult(args=["x"], returncode=1)])
    with pytest.raises(RiceError):
        fake.run(["x"], check=True)


def test_timeout_produces_synthetic_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_timeout(*a: Any, **k: Any) -> None:
        raise subprocess.TimeoutExpired(cmd=a[0] if a else "cmd", timeout=1)

    monkeypatch.setattr(subprocess, "run", raise_timeout)
    from rice.core.runner import CommandRunner

    result = CommandRunner().run(["slow"], timeout=1)
    assert result.timed_out
    assert result.returncode == 124


def test_rejects_non_list_args() -> None:
    from rice.core.runner import CommandRunner

    with pytest.raises(TypeError):
        CommandRunner().run("apt update")  # type: ignore[arg-type]
