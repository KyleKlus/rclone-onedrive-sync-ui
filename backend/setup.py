"""
The setup of ONE folder pair (local folder, remote, size limit,
exclusions): what it is and how it is validated.

The file has two parts:

1. ``PairSetup``   an immutable value object (what the setup form edits)
2. ``_clean_*``    validation helpers used by ``PairSetup.from_dict``

Name, on/off switch and the list of all pairs live in ``pairs.py``.

``PairSetup`` is immutable (frozen). To change a setup you create a new
object, which avoids bugs where a running sync sees half-edited values.
"""

import os
import re
from dataclasses import dataclass
from typing import Any

from . import config
from .errors import SetupError

# Examples: 50M, 2G, 500k, 1.5G, or "off" for "no size limit".
_MAX_SIZE_PATTERN = re.compile(r"^(off|\d+(\.\d+)?[bkmgtp]?)$", re.IGNORECASE)


@dataclass(frozen=True)
class PairSetup:
    """Everything rclone needs to know to sync one folder pair."""

    local_path: str = ""
    remote: str = config.DEFAULT_REMOTE
    max_size: str = config.DEFAULT_MAX_SIZE
    exclusions: tuple = config.DEFAULT_EXCLUSIONS

    # ------------------------------------------------------------------
    # Conversion
    # ------------------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict) -> "PairSetup":
        """
        Build a validated setup from a plain dictionary (JSON from the UI
        or from the pairs file). Missing keys fall back to defaults.
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
    path = os.path.expanduser(path)  # allow "~/Cloud"
    if not os.path.isabs(path):
        raise SetupError("Local folder must be a full (absolute) path.")
    return path


def _clean_remote(value: Any) -> str:
    """
    An rclone remote looks like ``name:`` or ``name:some/folder``. The name is one
    of the remotes from ``rclone config``; the UI offers them in a dropdown, but
    any well-formed name is accepted here (the list can be out of date).
    """
    remote = _require_text(value, "Remote")
    if not remote:
        raise SetupError("Choose a remote first.")
    name, separator, _folder = remote.partition(":")
    if not separator:
        raise SetupError("Remote must contain a colon, e.g. 'mycloud:' or 'mycloud:Documents'.")
    # A single letter would be read by rclone as a Windows drive (C:), not a remote.
    if len(name) < 2:
        raise SetupError("Remote name must be at least 2 characters long.")
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
