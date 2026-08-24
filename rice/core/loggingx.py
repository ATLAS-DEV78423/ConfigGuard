"""Safe logging: redaction + file/stderr handlers.

Rules (spec §25, SR-002): logs never contain config contents or secrets —
hashes/metadata only.
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

_SECRET_RE = re.compile(
    r"(?i)(?<![A-Za-z])(password|passwd|token|secret|api[_-]?key|auth|credential)s?"
    r"(\s*[=:]\s*)(\S+)"
)

_configured = False


def redact(text: str) -> str:
    """Mask values assigned to secret-looking keys. Keeps keys for debuggability.

    The lookbehind (not \\b) lets MY_TOKEN= match while keeping 'author=' safe.
    """
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}<redacted>", text)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Interpolate BEFORE redacting: redacting a "%s" format string would
        # swallow placeholders and break msg % args downstream.
        if record.args:
            try:
                record.msg = record.getMessage()
            except Exception:
                pass
            record.args = None
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def setup_logging(data_dir: Path, *, verbose: bool = False, quiet: bool = False) -> None:
    """Configure the "rice" logger: stderr stream + daily file under data_dir/logs.

    Levels: --verbose DEBUG, --quiet WARNING, default INFO. Idempotent: safe to
    call twice without duplicating handlers.

    The redaction filter lives on each HANDLER (SR-002): logger-level filters
    do NOT apply to records propagated from child loggers like rice.snapshot,
    handler-level filters apply to everything that reaches output.
    """
    global _configured
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    root = logging.getLogger("rice")
    root.setLevel(level)
    if _configured:
        return
    _configured = True

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    stream = logging.StreamHandler(sys.stderr)
    stream.addFilter(_RedactFilter())
    stream.setFormatter(fmt)
    root.addHandler(stream)

    log_dir = data_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        name = f"rice-{datetime.now(UTC).strftime('%Y%m%d')}.log"
        fh = logging.FileHandler(log_dir / name, encoding="utf-8")
        fh.addFilter(_RedactFilter())
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        root.warning("could not open log file under %s; stderr only", log_dir)

    # Third-party/typer noise stays quiet unless verbose.
    logging.getLogger("").setLevel(level if verbose else logging.WARNING)
