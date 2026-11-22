"""!
@file pairs.py
@brief Folder pairs: what one pair is, and where the list of all pairs is kept.

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
from .pair_relations import find_conflict
from .setup import PairSetup

_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class FolderPair:
    """!
    @brief One local folder that is kept in sync with one folder on a remote (a cloud).

    Attributes:
    id - Never changes; ids end up in URLs and file names, so only letters, digits, "_" and "-" are allowed.
    name - Shown to the user; can be changed.
    setup - Local folder, remote, size limit and exclusions.
    enabled - False means temporarily switched off: skipped when a sync starts.
    """

    id: str
    name: str
    setup: PairSetup
    enabled: bool = True

    @classmethod
    def from_dict(cls, data: dict, pair_id: str, enabled: bool = True) -> "FolderPair":
        """!
        @brief Build a validated pair from a plain dictionary (JSON from the UI or from the pairs file).
        @param data The dictionary with the name and the setup fields.
        @param pair_id The id the pair gets.
        @param enabled Whether the pair is switched on. Default: True.
        @return The new pair.
        @throws SetupError With a human-readable message if the data is invalid.
        """
        return cls(
            id=pair_id,
            name=_clean_name(data.get("name")),
            setup=PairSetup.from_dict(data),
            enabled=enabled,
        )

    def to_dict(self) -> dict:
        """!
        @brief Convert the pair to the flat shape used by the API and the pairs file.
        @return A dictionary with id, name, enabled and the setup fields.
        """
        return {"id": self.id, "name": self.name, "enabled": self.enabled, **self.setup.to_dict()}


def _clean_name(value: Any) -> str:
    """!
    @brief Validate a folder pair name: one short line of text.
    @param value The raw name.
    @return The trimmed name.
    @throws SetupError If it is not text, empty, too long or not a single printable line.

    That the name is unique is checked by the store, not here.
    """
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
    """!
    @brief Validate an id read from the pairs file.
    @param value The raw id.
    @return The id, or "" if it is missing or unusable.
    """
    return value if isinstance(value, str) and _ID_PATTERN.match(value) else ""


def _clean_enabled(value: Any) -> bool:
    """!
    @brief Validate the on/off switch of a pair.
    @param value The raw value.
    @return The value as a bool.
    @throws SetupError If it is not a bool.
    """
    if not isinstance(value, bool):
        raise SetupError("'enabled' must be true or false.")
    return value


class FolderPairStore:
    """!
    @brief Holds the list of folder pairs (in the order the user created them) and keeps
    the file on disk in sync. Safe to use from several threads.

    Every change is validated first, then written to disk, and only then made
    visible. If anything fails, nothing has changed.
    """

    def __init__(self, path: Path, legacy_paths: Iterable[Path] = ()) -> None:
        """!
        @brief Load the pairs from disk (or convert an old single setup).
        @param path The pairs file (``pairs.json``).
        @param legacy_paths Files older versions used for their single setup, newest name first. If ``path`` does not exist yet but one of them does, it is converted into one folder pair; from then on ``path`` is the only file used. Default: none.
        """
        self._path = path
        self._legacy_paths = list(legacy_paths)
        self._lock = threading.Lock()
        self._pairs: list = self._load_from_disk()

    def all(self) -> list:
        """!
        @brief Get all pairs, in order.
        @return A copy of the list, so callers cannot change the store with it.
        """
        with self._lock:
            return list(self._pairs)

    def get(self, pair_id: str) -> FolderPair:
        """!
        @brief Get one pair.
        @param pair_id The id of the pair.
        @return The pair.
        @throws PairNotFoundError If there is no such pair.
        """
        with self._lock:
            return self._pairs[self._index_of(pair_id)]

    def create(self, data: dict) -> FolderPair:
        """!
        @brief Add a new, active pair.
        @param data Name and setup fields.
        @return The created pair.
        @throws SetupError If ``data`` is invalid, the name is taken or the folders clash with another pair.
        """
        with self._lock:
            pair = FolderPair.from_dict(data, pair_id=self._new_id())
            self._ensure_name_is_free(pair.name, ignore_id=None)
            self._ensure_no_conflict(pair)
            self._commit(self._pairs + [pair])
            return pair

    def update(self, pair_id: str, data: dict) -> FolderPair:
        """!
        @brief Replace name and setup of a pair.
        @param pair_id The id of the pair.
        @param data New name and setup fields.
        @return The updated pair.
        @throws PairNotFoundError If there is no such pair.
        @throws SetupError If ``data`` is invalid, the name is taken or the folders clash with another pair.

        Its id and on/off switch stay as they are (the switch has its own method, ``set_enabled``).
        """
        with self._lock:
            index = self._index_of(pair_id)
            existing = self._pairs[index]
            updated = FolderPair.from_dict(data, pair_id=existing.id, enabled=existing.enabled)
            self._ensure_name_is_free(updated.name, ignore_id=pair_id)
            self._ensure_no_conflict(updated)
            self._commit(self._pairs[:index] + [updated] + self._pairs[index + 1:])
            return updated

    def set_enabled(self, pair_id: str, enabled: bool) -> FolderPair:
        """!
        @brief Switch a pair on or off.
        @param pair_id The id of the pair.
        @param enabled True for on, False for off.
        @return The updated pair.
        @throws PairNotFoundError If there is no such pair.
        @throws SetupError If ``enabled`` is not a bool.
        """
        enabled = _clean_enabled(enabled)
        with self._lock:
            index = self._index_of(pair_id)
            updated = replace(self._pairs[index], enabled=enabled)
            self._commit(self._pairs[:index] + [updated] + self._pairs[index + 1:])
            return updated

    def delete(self, pair_id: str) -> None:
        """!
        @brief Remove a pair for good. Its files on disk and on the remote are not touched.
        @param pair_id The id of the pair.
        @throws PairNotFoundError If there is no such pair.
        """
        with self._lock:
            index = self._index_of(pair_id)
            self._commit(self._pairs[:index] + self._pairs[index + 1:])

    def _index_of(self, pair_id: str) -> int:
        """!
        @brief Find the position of a pair in the list. The caller already holds the lock.
        @param pair_id The id of the pair.
        @return The index.
        @throws PairNotFoundError If there is no such pair.
        """
        for index, pair in enumerate(self._pairs):
            if pair.id == pair_id:
                return index
        raise PairNotFoundError(f"There is no folder pair with the id '{pair_id}'.")

    def _ensure_name_is_free(self, name: str, ignore_id) -> None:
        """!
        @brief Make sure no other pair has this name. The caller already holds the lock.
        @param name The wanted name.
        @param ignore_id Id of a pair to leave out of the check (the pair being updated), or None.
        @throws SetupError If the name is taken.

        Names tag the log lines, so two pairs must not share one (upper/lower case ignored).
        """
        for pair in self._pairs:
            if pair.id != ignore_id and pair.name.casefold() == name.casefold():
                raise SetupError(f"Another folder pair is already called '{pair.name}'. Pick a different name.")

    def _ensure_no_conflict(self, candidate: FolderPair) -> None:
        """!
        @brief Refuse a pair whose folders clash with another pair's (see pair_relations.py). The caller already holds the lock.
        @param candidate The pair to check.
        @throws SetupError If its folders clash with another pair.

        A pair that merely lies INSIDE another one is fine: the outer pair then
        skips it. Switched-off pairs count too, so switching them on later can
        never cause a clash.
        """
        for other in self._pairs:
            if other.id == candidate.id:
                continue
            reason = find_conflict(candidate.setup, other.setup)
            if reason:
                raise SetupError(f"These folders clash with the folder pair '{other.name}'. {reason}")

    def _new_id(self) -> str:
        """!
        @brief Create an id that no existing pair has.
        @return The new id.
        """
        return self._unused_id({pair.id for pair in self._pairs})

    @staticmethod
    def _unused_id(taken: set) -> str:
        """!
        @brief Create a random short id that no other pair has.
        @param taken The ids that are already used.
        @return The new id.
        """
        while True:
            candidate = secrets.token_hex(4)
            if candidate not in taken:
                return candidate

    def _commit(self, new_pairs: list) -> None:
        """!
        @brief Save the new list, then switch over to it.
        @param new_pairs The complete new list of pairs.

        Save first, then switch over: a failed write leaves the old list intact.
        """
        self._write_to_disk(new_pairs)
        self._pairs = new_pairs

    def _load_from_disk(self) -> list:
        """!
        @brief Read the pairs file. If there is none, convert an old single setup, or start empty.
        @return The list of pairs.

        The conversion of an old setup is a one-time step; the old file stays untouched.
        """
        if self._path.exists():
            return self._read_pairs_file(self._path)

        for legacy_path in self._legacy_paths:
            if legacy_path.exists():
                pairs = self._read_legacy_setup(legacy_path)
                self._write_to_disk(pairs)
                return pairs
        return []

    def _read_pairs_file(self, path: Path) -> list:
        """!
        @brief Read the pairs from a pairs file.
        @param path The pairs file.
        @return The list of pairs.

        Entries that cannot be understood are skipped (with a warning), not fatal.
        """
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
        """!
        @brief Read an old setup file: one flat setup without a name or id, which becomes the first pair.
        @param path The old setup file.
        @return A list with the one pair, or an empty list (with a warning) if it cannot be read.
        """
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
        """!
        @brief Write the pairs file.
        @param pairs The pairs to save.

        Written atomically (temporary file, then replace) so a crash can never leave a half-written file.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(".tmp")
        temporary_path.write_text(
            json.dumps({"pairs": [pair.to_dict() for pair in pairs]}, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, self._path)
