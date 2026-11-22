"""!
@file models.py
@brief Small data types shared by several modules.
"""

from dataclasses import dataclass
from enum import Enum


class SyncMode(str, Enum):
    """!
    @brief The two ways the app can synchronise. The mode applies to ALL folder pairs.

    BISYNC: Two-way, changes on both sides are merged.
    DOWNLOAD: One-way, this PC is made to match the remote.
    """

    BISYNC = "bisync"
    DOWNLOAD = "download"


class SyncState(str, Enum):
    """!
    @brief What the system as a whole, or one single folder pair, is doing right now.

    The UI shows this value prominently, so every state has to be
    understandable on its own.

    IDLE: Nothing has been started yet.
    RUNNING: rclone is working.
    STOPPING: Stop was requested, rclone is shutting down.
    SUCCEEDED: The last run finished without errors.
    FAILED: The last run ended with an error.
    CANCELLED: The last run was stopped by the user.
    """

    IDLE = "idle"
    RUNNING = "running"
    STOPPING = "stopping"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_finished(self) -> bool:
        """!
        @brief Tell whether nothing is going to happen any more in this state.
        @return True for SUCCEEDED, FAILED and CANCELLED.
        """
        return self in (SyncState.SUCCEEDED, SyncState.FAILED, SyncState.CANCELLED)


@dataclass(frozen=True)
class RunOptions:
    """!
    @brief What the user asked for when pressing Start. The same for every folder pair of the run.

    Attributes:
    mode - The sync mode.
    resync - First-time setup for two-way sync.
    dry_run - Only show what would happen.
    """

    mode: SyncMode
    resync: bool = False
    dry_run: bool = False


@dataclass(frozen=True)
class LogEntry:
    """!
    @brief One line in the live log.

    Attributes:
    id - Increasing number; lets the UI ask "give me what's new".
    timestamp - Local time, formatted HH:MM:SS.
    level - One of app, error, warning, notice, info, debug.
    text - The log line itself.
    source - Name of the folder pair that wrote the line ("" = the app itself).
    """

    id: int
    timestamp: str
    level: str
    text: str
    source: str = ""

    def to_dict(self) -> dict:
        """!
        @brief Convert the entry to a JSON-serialisable dictionary.
        @return Dictionary with id, timestamp, level, text and source.
        """
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level,
            "text": self.text,
            "source": self.source,
        }
