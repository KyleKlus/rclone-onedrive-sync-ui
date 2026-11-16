"""
Folder pairs: what one pair is, and where the list of all pairs is kept.

The file has two parts, from the inside out:

1. ``FolderPair``       an immutable value object: id, name, on/off switch and the
                        ``PairSetup`` (local folder, remote, size limit, exclusions)
2. ``FolderPairStore``  keeps the list of pairs and saves it as JSON (``pairs.json``)

Why an id? The name can be changed at any time, so the rest of the app (URLs,
filter files, running jobs) refers to a pair by its id, which never changes.
"""

import json
import os
import re
import secrets
import threading
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from . import config
from .errors import PairNotFoundError, SetupError
from .setup import PairSetup

# Ids end up in URLs and file names, so only harmless characters are allowed.
_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class FolderPair:
    """One local folder that is kept in sync with one OneDrive folder."""

    id: str
    name: str
    setup: PairSetup
    enabled: bool = True   # False = temporarily switched off: skipped when a sync starts.

    @classmethod
    def from_dict(cls, data: dict, pair_id: str, enabled: bool = True) -> "FolderPair":
        """
        Build a validated pair from a plain dictionary (JSON from the UI or from
        the pairs file). Raises ``SetupError`` with a human-readable message if invalid.
        """
        return cls(
            id=pair_id,
            name=_clean_name(data.get("name")),
            setup=PairSetup.from_dict(data),
            enabled=enabled,
        )

    def to_dict(self) -> dict:
        """The flat shape used by the API and the pairs file."""
        return {"id": self.id, "name": self.name, "enabled": self.enabled, **self.setup.to_dict()}


# ----------------------------------------------------------------------
# Field cleaning / validation helpers
# ----------------------------------------------------------------------

def _clean_name(value: Any) -> str:
    """A name is one short line of text. (That it is unique is checked by the store.)"""
    if not isinstance(value, str):
        raise SetupError("The folder pair name must be text.")
    name = value.strip()
    if not name:
        raise SetupError("Give the folder pair a name.")
    if len(name) > config.PAIR_NAME_MAX_LENGTH:
        raise SetupError(f"The folder pair name can have at most {config.PAIR_NAME_MAX_LENGTH} characters.")
    if not name.isprintable():
        raise SetupError("The folder pair name must be a single line of normal characters.")
    return name


def _clean_id(value: Any) -> str:
    """The id from the pairs file, or "" if it is missing or unusable."""
    return value if isinstance(value, str) and _ID_PATTERN.match(value) else ""


def _clean_enabled(value: Any) -> bool:
    if not isinstance(value, bool):
        raise SetupError("'enabled' must be true or false.")
    return value


# ----------------------------------------------------------------------
# Persistence
# ----------------------------------------------------------------------

class FolderPairStore:
    """
    Holds the list of folder pairs (in the order the user created them) and keeps
    the file on disk in sync. Safe to use from several threads.

    Every change is validated first, then written to disk, and only then made
    visible. If anything fails, nothing has changed.
    """

    def __init__(self, path: Path, legacy_paths: Iterable[Path] = ()) -> None:
        """
        ``legacy_paths`` are the files older versions used for their single setup
        (newest name first). If ``path`` does not exist yet but one of them does, it
        is converted into one folder pair; from then on ``path`` is the only file used.
        """
        self._path = path
        self._legacy_paths = list(legacy_paths)
        self._lock = threading.Lock()
        self._pairs: list = self._load_from_disk()

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def all(self) -> list:
        """All pairs, in order. The list is a copy, so callers cannot change the store with it."""
        with self._lock:
            return list(self._pairs)

    def get(self, pair_id: str) -> FolderPair:
        """Raises ``PairNotFoundError`` if there is no such pair."""
        with self._lock:
            return self._pairs[self._index_of(pair_id)]

    # ------------------------------------------------------------------
    # Changing
    # ------------------------------------------------------------------

    def create(self, data: dict) -> FolderPair:
        """Add a new, active pair. Raises ``SetupError`` if ``data`` is invalid."""
        with self._lock:
            pair = FolderPair.from_dict(data, pair_id=self._new_id())
            self._ensure_name_is_free(pair.name, ignore_id=None)
            self._commit(self._pairs + [pair])
            return pair

    def update(self, pair_id: str, data: dict) -> FolderPair:
        """
        Replace name and setup of a pair. Its id and on/off switch stay as they
        are (the switch has its own method, ``set_enabled``).
        """
        with self._lock:
            index = self._index_of(pair_id)
            existing = self._pairs[index]
            updated = FolderPair.from_dict(data, pair_id=existing.id, enabled=existing.enabled)
            self._ensure_name_is_free(updated.name, ignore_id=pair_id)
            self._commit(self._pairs[:index] + [updated] + self._pairs[index + 1:])
            return updated

    def set_enabled(self, pair_id: str, enabled: bool) -> FolderPair:
        """Switch a pair on or off."""
        enabled = _clean_enabled(enabled)
        with self._lock:
            index = self._index_of(pair_id)
            updated = replace(self._pairs[index], enabled=enabled)
            self._commit(self._pairs[:index] + [updated] + self._pairs[index + 1:])
            return updated

    def delete(self, pair_id: str) -> None:
        """Remove a pair for good. Its files on disk and on OneDrive are not touched."""
        with self._lock:
            index = self._index_of(pair_id)
            self._commit(self._pairs[:index] + self._pairs[index + 1:])

    # ------------------------------------------------------------------
    # Helpers (the caller already holds the lock)
    # ------------------------------------------------------------------

    def _index_of(self, pair_id: str) -> int:
        for index, pair in enumerate(self._pairs):
            if pair.id == pair_id:
                return index
        raise PairNotFoundError(f"There is no folder pair with the id '{pair_id}'.")

    def _ensure_name_is_free(self, name: str, ignore_id) -> None:
        """Names tag the log lines, so two pairs must not share one (upper/lower case ignored)."""
        for pair in self._pairs:
            if pair.id != ignore_id and pair.name.casefold() == name.casefold():
                raise SetupError(f"Another folder pair is already called '{pair.name}'. Pick a different name.")

    def _new_id(self) -> str:
        return self._unused_id({pair.id for pair in self._pairs})

    @staticmethod
    def _unused_id(taken: set) -> str:
        """A random short id that no other pair has."""
        while True:
            candidate = secrets.token_hex(4)
            if candidate not in taken:
                return candidate

    def _commit(self, new_pairs: list) -> None:
        """Save first, then switch over: a failed write leaves the old list intact."""
        self._write_to_disk(new_pairs)
        self._pairs = new_pairs

    # ------------------------------------------------------------------
    # Disk access
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> list:
        """Read the pairs file. If there is none, convert an old single setup, or start empty."""
        if self._path.exists():
            return self._read_pairs_file(self._path)

        for legacy_path in self._legacy_paths:
            if legacy_path.exists():
                pairs = self._read_legacy_setup(legacy_path)
                self._write_to_disk(pairs)  # one-time conversion; the old file stays untouched
                return pairs
        return []

    def _read_pairs_file(self, path: Path) -> list:
        """Entries that cannot be understood are skipped (with a warning), not fatal."""
        try:
            entries = json.loads(path.read_text(encoding="utf-8"))["pairs"]
            if not isinstance(entries, list):
                raise TypeError("'pairs' must be a list")
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f"Warning: could not read {path} ({error}). Starting without folder pairs.")
            return []

        pairs: list = []
        for entry in entries:
            try:
                if not isinstance(entry, dict):
                    raise SetupError("an entry is not an object")
                taken = {pair.id for pair in pairs}
                pair_id = _clean_id(entry.get("id"))
                if not pair_id or pair_id in taken:
                    pair_id = self._unused_id(taken)
                pairs.append(FolderPair.from_dict(entry, pair_id, _clean_enabled(entry.get("enabled", True))))
            except SetupError as error:
                print(f"Warning: skipped a folder pair in {path} ({error}).")
        return pairs

    def _read_legacy_setup(self, path: Path) -> list:
        """An old setup file is one flat setup without a name or id: it becomes the first pair."""
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise SetupError("the file is not an object")
            data = {**data, "name": config.MIGRATED_PAIR_NAME}
            return [FolderPair.from_dict(data, pair_id=self._unused_id(set()))]
        except (OSError, ValueError, SetupError) as error:
            print(f"Warning: could not read {path} ({error}). Starting without folder pairs.")
            return []

    def _write_to_disk(self, pairs: list) -> None:
        """Write atomically so a crash can never leave a half-written file."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps({"pairs": [pair.to_dict() for pair in pairs]}, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self._path)
