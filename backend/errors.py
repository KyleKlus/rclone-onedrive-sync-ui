"""!
@file errors.py
@brief Custom exception types shared by all modules.

Having our own exception classes lets the API layer translate each problem
into the right HTTP status code without guessing from error messages.
"""


class SetupError(ValueError):
    """!
    @brief The setup sent by the user is invalid (HTTP 400).
    """


class PairNotFoundError(Exception):
    """!
    @brief There is no folder pair with the requested id (HTTP 404).
    """


class SyncConfigError(Exception):
    """!
    @brief A sync cannot be started because the setup is incomplete (HTTP 400).
    """


class SyncBusyError(Exception):
    """!
    @brief An action is not possible because a sync is already running (HTTP 409).
    """


class RcloneNotFoundError(Exception):
    """!
    @brief The rclone executable could not be found on this computer.
    """
