"""Rice error hierarchy. One subclass per exit code (spec §6).

Every user-facing failure is raised as one of these; rice.cli maps
``exit_code`` onto the process exit code.
"""


class RiceError(Exception):
    """Base class for all expected rice failures."""

    exit_code = 1

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UsageError(RiceError):
    exit_code = 2


class ConfigError(RiceError):
    exit_code = 3


class SnapshotError(RiceError):
    exit_code = 4


class UpdateFailedError(RiceError):
    exit_code = 5


class ConflictError(RiceError):
    exit_code = 6


class ValidationError_(RiceError):
    exit_code = 7


class RecoveryError(RiceError):
    exit_code = 8


class SudoError(RiceError):
    exit_code = 9


class ScopeViolation(RiceError):
    """Security refusal: path outside approved scope."""
