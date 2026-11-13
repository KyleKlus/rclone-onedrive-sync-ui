"""
The settings the user can change in the UI, plus their validation.

``AppSettings`` is immutable (frozen). To change a setting you create a new
object, which avoids bugs where a running sync sees half-edited values.
"""

import os
import re
from dataclasses import dataclass
from typing import Any

from . import config
from .errors import SettingsError

# Examples: 50M, 2G, 500k, 1.5G, or "off" for "no size limit".
_MAX_SIZE_PATTERN = re.compile(r"^(off|\d+(\.\d+)?[bkmgtp]?)$", re.IGNORECASE)


@dataclass(frozen=True)
class AppSettings:
    """All user-configurable settings."""

    local_path: str = ""
    remote: str = config.DEFAULT_REMOTE
    max_size: str = config.DEFAULT_MAX_SIZE
    exclusions: tuple = config.DEFAULT_EXCLUSIONS

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        """
        Build validated settings from a plain dictionary (JSON from the UI
        or from the settings file). Missing keys fall back to defaults.
        Raises ``SettingsError`` with a human-readable message if invalid.
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
        raise SettingsError(f"{field_label} must be text.")
    return value.strip()


def _clean_local_path(value: Any) -> str:
    """The local folder may be empty (not configured yet) but never relative."""
    path = _require_text(value, "Local folder")
    if not path:
        return ""
    path = os.path.expanduser(path)  # allow "~/OneDrive"
    if not os.path.isabs(path):
        raise SettingsError("Local folder must be a full (absolute) path.")
    return path


def _clean_remote(value: Any) -> str:
    """An rclone remote looks like ``name:`` or ``name:some/folder``."""
    remote = _require_text(value, "OneDrive remote")
    name, separator, _folder = remote.partition(":")
    if not separator:
        raise SettingsError(
            "OneDrive remote must contain a colon, e.g. 'onedrive:' or 'onedrive:Documents'."
        )
    # A single letter would be read by rclone as a Windows drive (C:), not a remote.
    if len(name) < 2:
        raise SettingsError("OneDrive remote name must be at least 2 characters long.")
    return remote


def _clean_max_size(value: Any) -> str:
    size = _require_text(value, "Maximum file size")
    if not _MAX_SIZE_PATTERN.match(size):
        raise SettingsError(
            "Maximum file size must look like '50M', '2G', '500k' or 'off'."
        )
    return size


def _clean_exclusions(value: Any) -> tuple:
    """Trim patterns, drop blanks and duplicates, reject unusable ones."""
    if not isinstance(value, (list, tuple)):
        raise SettingsError("Exclusions must be a list of patterns.")

    cleaned = []
    for item in value:
        pattern = _require_text(item, "Each exclusion")
        if not pattern:
            continue  # ignore blank entries
        if pattern[0] in "#;":
            raise SettingsError(
                f"Exclusion '{pattern}' must not start with '#' or ';' (rclone treats those as comments)."
            )
        if "\n" in pattern or "\r" in pattern or "\0" in pattern:
            raise SettingsError("Exclusions must be a single line each.")
        if pattern not in cleaned:
            cleaned.append(pattern)
    return tuple(cleaned)
