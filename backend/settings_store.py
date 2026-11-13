"""
Loading and saving the user settings as a JSON file.
"""

import json
import os
import threading
from pathlib import Path

from .errors import SettingsError
from .settings import AppSettings


class SettingsStore:
    """Holds the current settings and keeps the file on disk in sync."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._current = self._load_from_disk()

    def get(self) -> AppSettings:
        """The current settings (an immutable snapshot)."""
        with self._lock:
            return self._current

    def update(self, data: dict) -> AppSettings:
        """
        Validate ``data``, save it and make it the current settings.
        Raises ``SettingsError`` if anything is invalid; nothing is changed then.
        """
        new_settings = AppSettings.from_dict(data)
        with self._lock:
            self._write_to_disk(new_settings)
            self._current = new_settings
        return new_settings

    # ------------------------------------------------------------------
    # Disk access
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> AppSettings:
        """Read the settings file; fall back to defaults if it is missing or broken."""
        if not self._path.exists():
            return AppSettings()
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return AppSettings.from_dict(data)
        except (OSError, ValueError, SettingsError) as error:
            print(f"Warning: could not read {self._path} ({error}). Using defaults.")
            return AppSettings()

    def _write_to_disk(self, settings: AppSettings) -> None:
        """Write atomically so a crash can never leave a half-written file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(settings.to_dict(), indent=2), encoding="utf-8"
        )
        os.replace(temporary_path, self._path)
