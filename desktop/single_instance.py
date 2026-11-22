"""!
@file single_instance.py
@brief Prevents two copies of the app from running at once.

Two copies would be dangerous here: they could start two rclone syncs on the
same folder. The lock is an OS file lock, so it is released automatically even
if the app crashes (no stale lock files to clean up).
"""

import fcntl
from pathlib import Path
from typing import Optional


class InstanceLock:
    """!
    @brief Holds an exclusive lock on a file for as long as the app runs.
    """

    def __init__(self, lock_path: Path) -> None:
        """!
        @brief Create the lock object without taking the lock yet.
        @param lock_path The file that is locked; its folder is created on demand.
        """
        self._path = lock_path
        self._file: Optional[object] = None

    def acquire(self) -> bool:
        """!
        @brief Try to take the lock.
        @return True if the lock was taken, False if another copy already has it.

        The file handle is kept open on purpose: closing it would release the lock.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self._path, "w")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._file = handle
        return True

    def release(self) -> None:
        """!
        @brief Give the lock back by closing the file; does nothing if it is not held.
        """
        if self._file is not None:
            self._file.close()
            self._file = None
