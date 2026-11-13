"""
Custom exception types.

Having our own exception classes lets the API layer translate each problem
into the right HTTP status code without guessing from error messages.
"""


class SettingsError(ValueError):
    """The settings sent by the user are invalid (HTTP 400)."""


class SyncConfigError(Exception):
    """A sync cannot be started because the setup is incomplete (HTTP 400)."""


class SyncBusyError(Exception):
    """An action is not possible because a sync is already running (HTTP 409)."""


class RcloneNotFoundError(Exception):
    """The rclone executable could not be found on this computer."""
