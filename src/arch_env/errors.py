from __future__ import annotations


class ArchEnvError(Exception):
    """Base class for expected user-facing errors."""


class ConfigError(ArchEnvError):
    """Raised when arch-env.toml is invalid."""


class PathSafetyError(ArchEnvError):
    """Raised when a path could escape arch-env ownership boundaries."""


class PrerequisiteError(ArchEnvError):
    """Raised when required host commands or host properties are missing."""


class CommandExecutionError(ArchEnvError):
    """Raised when an external command exits unsuccessfully."""

    def __init__(self, message: str, *, command: list[str], returncode: int, log_path: str):
        super().__init__(message)
        self.command = command
        self.returncode = returncode
        self.log_path = log_path
