"""!
@file last_mode.py
@brief Remembers which sync mode was used last.

The web page lets the user pick a mode before pressing Start. Places without
such a picker (the tray menu) start the mode the user really used last.
"""

from pathlib import Path

from .models import SyncMode


class LastModeStore:
    """!
    @brief Keeps the last used sync mode in a small text file.
    """

    def __init__(self, path: Path) -> None:
        """!
        @brief Create the store; the file is only written by save().
        @param path The file that holds the mode.
        """
        self._path = path

    def load(self) -> SyncMode:
        """!
        @brief Read the last used mode.
        @return The saved mode, or two-way sync if nothing usable is saved.
        """
        try:
            return SyncMode(self._path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return SyncMode.BISYNC

    def save(self, mode: SyncMode) -> None:
        """!
        @brief Remember a mode.
        @param mode The mode to remember.
        @throws OSError If the file cannot be written.
        """
        self._path.write_text(mode.value, encoding="utf-8")
