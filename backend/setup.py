"""!
@file setup.py
@brief The setup of ONE folder pair (local folder, remote, size limit, exclusions) and its validation.

The file has two parts:

1. ``PairSetup``   an immutable value object (what the setup form edits)
2. ``_clean_*``    validation helpers used by ``PairSetup.from_dict``

Name, on/off switch and the list of all pairs live in pairs.py.

``PairSetup`` is immutable (frozen). To change a setup you create a new
object, which avoids bugs where a running sync sees half-edited values.

_MAX_SIZE_PATTERN accepts sizes like 50M, 2G, 500k, 1.5G, or "off" for "no size limit".
"""

import os
import re
from dataclasses import dataclass
from typing import Any

from . import config
from .errors import SetupError

_MAX_SIZE_PATTERN = re.compile(r"^(off|\d+(\.\d+)?[bkmgtp]?)$", re.IGNORECASE)


@dataclass(frozen=True)
class PairSetup:
    """!
    @brief Everything rclone needs to know to sync one folder pair.

    Attributes: local_path, remote, max_size and exclusions.
    """

    local_path: str = ""
    remote: str = config.DEFAULT_REMOTE
    max_size: str = config.DEFAULT_MAX_SIZE
    exclusions: tuple = config.DEFAULT_EXCLUSIONS

    @classmethod
    def from_dict(cls, data: dict) -> "PairSetup":
        """!
        @brief Build a validated setup from a plain dictionary (JSON from the UI or from the pairs file).
        @param data The dictionary; missing keys fall back to defaults.
        @return The new setup.
        @throws SetupError With a human-readable message if the data is invalid.
        """
        defaults = cls()
        return cls(
            local_path=_clean_local_path(data.get("local_path", defaults.local_path)),
            remote=_clean_remote(data.get("remote", defaults.remote)),
            max_size=_clean_max_size(data.get("max_size", defaults.max_size)),
            exclusions=_clean_exclusions(data.get("exclusions", list(defaults.exclusions))),
        )

    def to_dict(self) -> dict:
        """!
        @brief Convert the setup to a JSON-serialisable dictionary.
        @return Dictionary with local_path, remote, max_size and exclusions (as list).
        """
        return {
            "local_path": self.local_path,
            "remote": self.remote,
            "max_size": self.max_size,
            "exclusions": list(self.exclusions),
        }


def _require_text(value: Any, field_label: str) -> str:
    """!
    @brief Make sure a value is text and trim it.
    @param value The value to check.
    @param field_label Name of the field, used in the error message.
    @return The trimmed text.
    @throws SetupError If the value is not text.
    """
    if not isinstance(value, str):
        raise SetupError(f"{field_label} must be text.")
    return value.strip()


def _clean_local_path(value: Any) -> str:
    """!
    @brief Validate the local folder; "~" is expanded.
    @param value The raw value.
    @return The absolute path, or "" if not configured yet.
    @throws SetupError If the value is not text or the path is relative.
    """
    path = _require_text(value, "Local folder")
    if not path:
        return ""
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        raise SetupError("Local folder must be a full (absolute) path.")
    return path


def _clean_remote(value: Any) -> str:
    """!
    @brief Validate the remote.
    @param value The raw value.
    @return The remote, e.g. ``name:`` or ``name:some/folder``.
    @throws SetupError If the remote is empty or malformed.

    The name is one of the remotes from ``rclone config``; the UI offers them in
    a dropdown, but any well-formed name is accepted here (the list can be out
    of date). A single letter would be read by rclone as a Windows drive (C:),
    not a remote, so names need at least 2 characters.
    """
    remote = _require_text(value, "Remote")
    if not remote:
        raise SetupError("Choose a remote first.")
    name, separator, _folder = remote.partition(":")
    if not separator:
        raise SetupError("Remote must contain a colon, e.g. 'mycloud:' or 'mycloud:Documents'.")
    if len(name) < 2:
        raise SetupError("Remote name must be at least 2 characters long.")
    return remote


def _clean_max_size(value: Any) -> str:
    """!
    @brief Validate the maximum file size.
    @param value The raw value.
    @return The size as text, e.g. "50M" or "off".
    @throws SetupError If the value does not look like a size.
    """
    size = _require_text(value, "Maximum file size")
    if not _MAX_SIZE_PATTERN.match(size):
        raise SetupError(
            "Maximum file size must look like '50M', '2G', '500k' or 'off'."
        )
    return size


def _clean_exclusions(value: Any) -> tuple:
    """!
    @brief Trim patterns, drop blanks and duplicates, reject unusable ones.
    @param value The raw value; must be a list or tuple of text.
    @return The cleaned patterns.
    @throws SetupError If a pattern starts with '#' or ';' (rclone treats those as comments) or spans several lines.
    """
    if not isinstance(value, (list, tuple)):
        raise SetupError("Exclusions must be a list of patterns.")

    cleaned = []
    for item in value:
        pattern = _require_text(item, "Each exclusion")
        if not pattern:
            continue
        if pattern[0] in "#;":
            raise SetupError(
                f"Exclusion '{pattern}' must not start with '#' or ';' (rclone treats those as comments)."
            )
        if "\n" in pattern or "\r" in pattern or "\0" in pattern:
            raise SetupError("Exclusions must be a single line each.")
        if pattern not in cleaned:
            cleaned.append(pattern)
    return tuple(cleaned)
