"""
Everything about the folder-sync setup (local folder, OneDrive remote, size limit,
exclusions): what it is, how it is validated and how it is saved.

The file has three parts, from the inside out:

1. ``AppSetup``    an immutable value object (what the UI edits)
2. ``_clean_*``    validation helpers used by ``AppSetup.from_dict``
3. ``SetupStore``  keeps the current ``AppSetup`` and persists it as JSON

``AppSetup`` is immutable (frozen). To change the setup you create a new
object, which avoids bugs where a running sync sees half-edited values.
"""

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from . import config
from .errors import SetupError

# Examples: 50M, 2G, 500k, 1.5G, or "off" for "no size limit".
_MAX_SIZE_PATTERN = re.compile(r"^(off|\d+(\.\d+)?[bkmgtp]?)$", re.IGNORECASE)


@dataclass(frozen=True)
class AppSetup:
    """The complete setup of the folder sync."""

    local_path: str = ""
    remote: str = config.DEFAULT_REMOTE
    max_size: str = config.DEFAULT_MAX_SIZE
    exclusions: tuple = config.DEFAULT_EXCLUSIONS

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "AppSetup":
        """
        Build a validated setup from a plain dictionary (JSON from the UI
        or from the setup file). Missing keys fall back to defaults.
        Raises ``SetupError`` with a human-readable message if invalid.
        """
        defaults = cls()
        return cls(
            local_path=_clean_local_path(data.get("local_path", defaults.local_path)),
            remote=_clean_remote(data.get("remote", defaults.remote)),
            max_size=_clean_max_size(data.get("max_size", defaults.max_size)),
            exclusions=_clean_exclusions(data.get("exclusions", list(defaults.exclusions))),
        )

    def to_dict(self) -> dict:
        return {
            "local_path": self.local_path,
            "remote": self.remote,
            "max_size": self.max_size,
            "exclusions": list(self.exclusions),
        }


# ----------------------------------------------------------------------
# Field cleaning / validation helpers
# ----------------------------------------------------------------------

def _require_text(value: Any, field_label: str) -> str:
    if not isinstance(value, str):
        raise SetupError(f"{field_label} must be text.")
    return value.strip()


def _clean_local_path(value: Any) -> str:
    """The local folder may be empty (not configured yet) but never relative."""
    path = _require_text(value, "Local folder")
    if not path:
        return ""
    path = os.path.expanduser(path)  # allow "~/OneDrive"
    if not os.path.isabs(path):
        raise SetupError("Local folder must be a full (absolute) path.")
    return path


def _clean_remote(value: Any) -> str:
    """An rclone remote looks like ``name:`` or ``name:some/folder``."""
    remote = _require_text(value, "OneDrive remote")
    name, separator, _folder = remote.partition(":")
    if not separator:
        raise SetupError(
            "OneDrive remote must contain a colon, e.g. 'onedrive:' or 'onedrive:Documents'."
        )
    # A single letter would be read by rclone as a Windows drive (C:), not a remote.
    if len(name) < 2:
        raise SetupError("OneDrive remote name must be at least 2 characters long.")
    return remote


def _clean_max_size(value: Any) -> str:
    size = _require_text(value, "Maximum file size")
    if not _MAX_SIZE_PATTERN.match(size):
        raise SetupError(
            "Maximum file size must look like '50M', '2G', '500k' or 'off'."
        )
    return size


def _clean_exclusions(value: Any) -> tuple:
    """Trim patterns, drop blanks and duplicates, reject unusable ones."""
    if not isinstance(value, (list, tuple)):
        raise SetupError("Exclusions must be a list of patterns.")

    cleaned = []
    for item in value:
        pattern = _require_text(item, "Each exclusion")
        if not pattern:
            continue  # ignore blank entries
        if pattern[0] in "#;":
            raise SetupError(
                f"Exclusion '{pattern}' must not start with '#' or ';' (rclone treats those as comments)."
            )
        if "\n" in pattern or "\r" in pattern or "\0" in pattern:
            raise SetupError("Exclusions must be a single line each.")
        if pattern not in cleaned:
            cleaned.append(pattern)
    return tuple(cleaned)


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------

class SetupStore:
    """Holds the current setup and keeps the file on disk in sync."""

    def __init__(self, path: Path, legacy_path: Optional[Path] = None) -> None:
        """
        ``legacy_path`` is the file's old name (``settings.json``). If only that
        exists, it is read once; the next save writes the new file.
        """
        self._path = path
        self._legacy_path = legacy_path
        self._lock = threading.Lock()
        self._current = self._load_from_disk()

    def get(self) -> AppSetup:
        """The current setup (an immutable snapshot)."""
        with self._lock:
            return self._current

    def update(self, data: dict) -> AppSetup:
        """
        Validate ``data``, save it and make it the current setup.
        Raises ``SetupError`` if anything is invalid; nothing is changed then.
        """
        new_setup = AppSetup.from_dict(data)
        with self._lock:
            self._write_to_disk(new_setup)
            self._current = new_setup
        return new_setup

    # ------------------------------------------------------------------
    # Disk access
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> AppSetup:
        """Read the setup file; fall back to defaults if it is missing or broken."""
        source = self._path
        if not source.exists() and self._legacy_path is not None:
            source = self._legacy_path
        if not source.exists():
            return AppSetup()
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            return AppSetup.from_dict(data)
        except (OSError, ValueError, SetupError) as error:
            print(f"Warning: could not read {source} ({error}). Using defaults.")
            return AppSetup()

    def _write_to_disk(self, setup: AppSetup) -> None:
        """Write atomically so a crash can never leave a half-written file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps(setup.to_dict(), indent=2), encoding="utf-8"
        )
        os.replace(temporary_path, self._path)
