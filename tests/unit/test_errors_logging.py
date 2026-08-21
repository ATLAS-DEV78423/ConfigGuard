"""Exit-code table + redaction + logging setup contracts."""

from __future__ import annotations

import logging
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


def test_setup_logging_levels(tmp_path: Path) -> None:
    logger = logging.getLogger("rice")
    for verbose, quiet, expected in [
        (True, False, logging.DEBUG),
        (False, True, logging.WARNING),
        (False, False, logging.INFO),
    ]:
        logger._rice_configured = False  # type: ignore[attr-defined]
        for h in list(logger.handlers):
            logger.removeHandler(h)
        setup_logging(tmp_path, verbose=verbose, quiet=quiet)
        assert logger.level == expected
        assert getattr(logger, "_rice_configured", False)


def test_setup_logging_idempotent(tmp_path: Path) -> None:
    logger = logging.getLogger("rice")
    logger._rice_configured = False  # type: ignore[attr-defined]
    for h in list(logger.handlers):
        logger.removeHandler(h)
    setup_logging(tmp_path)
    n = len(logger.handlers)
    setup_logging(tmp_path)
    assert len(logger.handlers) == n


def test_redaction_filter_applies_to_logged_records(caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("rice")
    old = log.filters[:]
    try:
        from rice.core.loggingx import _RedactFilter

        log.addFilter(_RedactFilter())
        with caplog.at_level(logging.INFO, logger="rice"):
            log.info("token=%s failed", "supersecret")
        assert "supersecret" not in caplog.text
        assert "<redacted>" in caplog.text
    finally:
        log.filters[:] = old
