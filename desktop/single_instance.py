"""
Prevents two copies of the app from running at once.

Two copies would be dangerous here: they could start two rclone syncs on the
same folder. The lock is an OS file lock, so it is released automatically even
if the app crashes (no stale lock files to clean up).
"""

import fcntl
from pathlib import Path
from typing import Optional


class InstanceLock:
    """Holds an exclusive lock on a file for as long as the app runs."""

    def __init__(self, lock_path: Path) -> None:
        self._path = lock_path
        self._file: Optional[object] = None

    def acquire(self) -> bool:
        """Try to take the lock. Returns False if another copy already has it."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle  # keep it open: closing it would release the lock
        return True

    def release(self) -> None:
        if self._file is not None:
            self._file.close()  # type: ignore[attr-defined]
            self._file = None
