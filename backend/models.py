"""
Small data types shared by several modules.
"""

from dataclasses import dataclass
from enum import Enum


class SyncMode(str, Enum):
    """The two ways the app can synchronise."""

    BISYNC = "bisync"      # Two-way: changes on both sides are merged.
    DOWNLOAD = "download"  # One-way: this PC is made to match OneDrive.


class SyncState(str, Enum):
    """
    What the system is doing right now.

    The UI shows this value prominently, so every state has to be
    understandable on its own.
    """

    IDLE = "idle"              # Nothing has been started yet.
    RUNNING = "running"        # rclone is working.
    STOPPING = "stopping"      # Stop was requested, rclone is shutting down.
    SUCCEEDED = "succeeded"    # The last run finished without errors.
    FAILED = "failed"          # The last run ended with an error.
    CANCELLED = "cancelled"    # The last run was stopped by the user.


@dataclass(frozen=True)
class LogEntry:
    """One line in the live log."""

    id: int          # Increasing number; lets the UI ask "give me what's new".
    timestamp: str   # Local time, formatted HH:MM:SS.
    level: str       # app | error | warning | notice | info | debug
    text: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level,
            "text": self.text,
        }
