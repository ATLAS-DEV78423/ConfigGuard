"""Rice error hierarchy. One class per exit code (spec §6).

Every user-facing failure is raised as one of these; rice.cli maps
``exit_code`` onto the process exit code.
"""


class RiceError(Exception):
    """Base class for all expected rice failures."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code


class UsageError(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=2)


class ConfigError(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=3)


class SnapshotError(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=4)


class UpdateFailedError(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=5)


class ConflictError(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=6)


class ValidationError_(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=7)


class RecoveryError(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=8)


class SudoError(RiceError):
    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=9)


class ScopeViolation(RiceError):
    """Security refusal: path outside approved scope."""

    def __init__(self, message: str) -> None:
        super().__init__(message, exit_code=1)
