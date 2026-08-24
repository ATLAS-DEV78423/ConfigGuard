"""Exit-code table + redaction + logging setup contracts."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from rice.core.errors import (
    ConfigError,
    ConflictError,
    RecoveryError,
    RiceError,
    ScopeViolation,
    SnapshotError,
    SudoError,
    UpdateFailedError,
    UsageError,
    ValidationError_,
)
from rice.core.loggingx import redact, setup_logging


@pytest.mark.parametrize(
    ("cls", "code"),
    [
        (RiceError, 1),
        (UsageError, 2),
        (ConfigError, 3),
        (SnapshotError, 4),
        (UpdateFailedError, 5),
        (ConflictError, 6),
        (ValidationError_, 7),
        (RecoveryError, 8),
        (SudoError, 9),
        (ScopeViolation, 1),
    ],
)
def test_exit_codes(cls: type[RiceError], code: int) -> None:
    assert cls("boom").exit_code == code


def test_redact_masks_secret_values() -> None:
    assert redact("password=hunter2") == "password=<redacted>"
    assert redact("api_key: sk-123") == "api_key: <redacted>"
    assert redact("MY_TOKEN=abc") == "MY_TOKEN=<redacted>"


def test_redact_leaves_normal_text() -> None:
    text = "snapshot 2026-08-21T12-04-33Z verified ok"
    assert redact(text) == text


def _reset_rice_logging() -> None:
    """Fresh slate so setup_logging runs fully (guards + handlers cleared)."""
    import rice.core.loggingx as loggingx

    loggingx._configured = False
    logger = logging.getLogger("rice")
    for h in list(logger.handlers):
        logger.removeHandler(h)


@pytest.fixture()
def clean_logging() -> Iterator[None]:
    _reset_rice_logging()
    yield
    _reset_rice_logging()


def test_setup_logging_levels(tmp_path: Path, clean_logging: None) -> None:
    logger = logging.getLogger("rice")
    for verbose, quiet, expected in [
        (True, False, logging.DEBUG),
        (False, True, logging.WARNING),
        (False, False, logging.INFO),
    ]:
        _reset_rice_logging()
        setup_logging(tmp_path, verbose=verbose, quiet=quiet)
        assert logger.level == expected


def test_setup_logging_idempotent(tmp_path: Path, clean_logging: None) -> None:
    logger = logging.getLogger("rice")
    setup_logging(tmp_path)
    n = len(logger.handlers)
    setup_logging(tmp_path)
    assert len(logger.handlers) == n


def test_redaction_applies_to_child_logger_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_logging: None
) -> None:
    """SR-002 mechanism check: records from CHILD loggers (rice.snapshot etc.)
    must be redacted too — the filter lives on handlers (B2 regression)."""
    import io

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stderr", buf)
    setup_logging(tmp_path)
    logging.getLogger("rice.snapshot").info("token=%s leaked", "supersecret")
    for h in logging.getLogger("rice").handlers:
        h.flush()
    assert "supersecret" not in buf.getvalue()
    assert "<redacted>" in buf.getvalue()
