"""
Small data types shared by several modules.
"""

from dataclasses import dataclass
from enum import Enum


class SyncMode(str, Enum):
    """The two ways the app can synchronise. The mode applies to ALL folder pairs."""

    BISYNC = "bisync"      # Two-way: changes on both sides are merged.
    DOWNLOAD = "download"  # One-way: this PC is made to match OneDrive.


class SyncState(str, Enum):
    """
    What the system as a whole, or one single folder pair, is doing right now.

    The UI shows this value prominently, so every state has to be
    understandable on its own.
    """

    IDLE = "idle"              # Nothing has been started yet.
    QUEUED = "queued"          # One folder pair only: waiting for a pair with overlapping folders.
    RUNNING = "running"        # rclone is working.
    STOPPING = "stopping"      # Stop was requested, rclone is shutting down.
    SUCCEEDED = "succeeded"    # The last run finished without errors.
    FAILED = "failed"          # The last run ended with an error.
    CANCELLED = "cancelled"    # The last run was stopped by the user.

    @property
    def is_finished(self) -> bool:
        """True for the three states in which nothing is going to happen any more."""
        return self in (SyncState.SUCCEEDED, SyncState.FAILED, SyncState.CANCELLED)


@dataclass(frozen=True)
class RunOptions:
    """What the user asked for when pressing Start. The same for every folder pair of the run."""

    mode: SyncMode
    resync: bool = False    # First-time setup for two-way sync.
    dry_run: bool = False   # Only show what would happen.


@dataclass(frozen=True)
class LogEntry:
    """One line in the live log."""

    id: int          # Increasing number; lets the UI ask "give me what's new".
    timestamp: str   # Local time, formatted HH:MM:SS.
    level: str       # app | error | warning | notice | info | debug
    text: str
    source: str = ""  # Name of the folder pair that wrote the line ("" = the app itself).

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level,
            "text": self.text,
            "source": self.source,
        }
