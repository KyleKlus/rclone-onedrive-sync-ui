"""
How two folder pairs relate to each other, so that nothing is synced twice.

Every pair maps a local folder to a OneDrive folder. Looking at two pairs there
are exactly three cases:

SEPARATE   Neither the local nor the OneDrive folders touch. Nothing to do.

NESTED     One pair (the INNER one) lies inside the other (the OUTER one) on BOTH
           sides, at the SAME position:

               outer   /home/me/Docs          <->  onedrive:Docs
               inner   /home/me/Docs/Photos   <->  onedrive:Docs/Photos

           The outer pair would sync the inner folder too. That is the "synced
           twice" case, and it is solved automatically: the outer pair EXCLUDES
           the inner folder (``/Photos/``), the inner pair syncs it.

CONFLICT   Anything else that touches. For example the same OneDrive folder
           reached from two local folders, or an inner folder that sits at a
           different position on each side. There is no correct way to sync
           that, so such pairs cannot be saved (and cannot be run together).

Everything here is a pure function of the setups, which keeps it easy to test.
"""

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Optional

from .setup import PairSetup

# Characters that mean something in an rclone filter pattern.
_FILTER_SPECIAL_CHARACTERS = re.compile(r"([*?\[\]{}\\])")


class RelationKind(str, Enum):
    SEPARATE = "separate"
    NESTED = "nested"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class PairRelation:
    """The result of ``relate``."""

    kind: RelationKind
    reason: str = ""                 # CONFLICT: why, in plain words
    first_is_inner: bool = False     # NESTED: which of the two lies inside the other
    inner_folder: tuple = ()         # NESTED: the inner folder's path below the outer one, as parts


_SEPARATE = PairRelation(RelationKind.SEPARATE)


def relate(first: PairSetup, second: PairSetup) -> PairRelation:
    """Classify two pairs (see the module description)."""
    if not first.local_path or not second.local_path:
        return _SEPARATE  # "not configured yet" must not be mistaken for the current directory

    local_how, local_below = _compare_local(first.local_path, second.local_path)
    remote_how, remote_below = _compare_remote(first.remote, second.remote)

    if local_how == "separate" and remote_how == "separate":
        return _SEPARATE
    if local_how == "same" and remote_how == "same":
        return _conflict("They use the same local folder and the same OneDrive folder.")
    if local_how == "separate":
        return _conflict("Their OneDrive folders overlap, but their local folders do not.")
    if remote_how == "separate":
        return _conflict("Their local folders overlap, but their OneDrive folders do not.")
    if local_how == "same" or remote_how == "same":
        return _conflict("One side uses the same folder, but on the other side one folder lies inside the other.")
    if local_how != remote_how:
        return _conflict("Their local folders and their OneDrive folders are nested in opposite directions.")

    # Both sides nested the same way. The inner folder must be at the same spot on both sides.
    if [part.casefold() for part in local_below] != remote_below:
        return _conflict(
            f"The inner local folder is at '{'/'.join(local_below)}' inside the outer one, "
            f"but the inner OneDrive folder is at '{'/'.join(remote_below)}'. Both must match."
        )
    return PairRelation(
        RelationKind.NESTED,
        first_is_inner=(local_how == "first_inside"),
        inner_folder=tuple(local_below),
    )


def find_conflict(setup: PairSetup, other: PairSetup) -> Optional[str]:
    """The reason why two pairs cannot exist together, or None if they can."""
    relation = relate(setup, other)
    return relation.reason if relation.kind is RelationKind.CONFLICT else None


def lies_inside(candidate: PairSetup, container: PairSetup) -> bool:
    """True if ``candidate`` is nested inside ``container`` (and so is skipped by it)."""
    relation = relate(container, candidate)
    return relation.kind is RelationKind.NESTED and not relation.first_is_inner


def inner_folders(setup: PairSetup, others: Iterable[PairSetup]) -> list:
    """
    The inner folders of every other pair that lies inside ``setup``, as lists of
    path parts, in a fixed order. These are the folders ``setup`` must not sync.
    """
    return sorted(
        relate(setup, other).inner_folder for other in others if lies_inside(other, setup)
    )


def automatic_exclusions(setup: PairSetup, others: Iterable[PairSetup]) -> tuple:
    """
    The filter patterns that keep ``setup`` out of the folders of the pairs inside it.
    ``/Photos/`` means: the top-level folder Photos (relative to the synced folder).
    """
    return tuple("/" + "/".join(_escape_for_filter(part) for part in folder) + "/"
                 for folder in inner_folders(setup, others))


# ----------------------------------------------------------------------

def _conflict(reason: str) -> PairRelation:
    return PairRelation(RelationKind.CONFLICT, reason=reason)


def _compare_local(first: str, second: str) -> tuple:
    """
    How two local folders relate: ("separate" | "same" | "first_inside" | "second_inside", parts),
    where ``parts`` is the path of the inside folder below the outside one.
    """
    first, second = _normalise_local(first), _normalise_local(second)
    try:
        common = os.path.commonpath([first, second])
    except ValueError:
        return "separate", []  # Windows: different drives (C: and D:) have nothing in common

    if first == second:
        return "same", []
    if common == first:
        return "second_inside", _parts(os.path.relpath(second, first))
    if common == second:
        return "first_inside", _parts(os.path.relpath(first, second))
    return "separate", []


def _compare_remote(first: str, second: str) -> tuple:
    """
    Like ``_compare_local`` for ``onedrive:Docs/Work`` style remotes. Different remotes
    are different clouds. OneDrive ignores case in folder names, so the parts are lower-cased.
    A remote without a folder (``onedrive:``) is the whole drive and contains every folder.
    """
    first_name, first_folders = _split_remote(first)
    second_name, second_folders = _split_remote(second)
    if first_name != second_name:
        return "separate", []

    if first_folders == second_folders:
        return "same", []
    if second_folders[:len(first_folders)] == first_folders:
        return "second_inside", second_folders[len(first_folders):]
    if first_folders[:len(second_folders)] == second_folders:
        return "first_inside", first_folders[len(second_folders):]
    return "separate", []


def _normalise_local(path: str) -> str:
    """Resolve symlinks and '..' and, on Windows, ignore upper/lower case."""
    return os.path.normcase(os.path.realpath(path))


def _split_remote(remote: str) -> tuple:
    """'onedrive:Docs/Work' -> ('onedrive', ['docs', 'work'])."""
    name, _separator, folder = remote.partition(":")
    return name, [part for part in folder.casefold().split("/") if part]


def _parts(relative_path: str) -> list:
    return [part for part in relative_path.split(os.sep) if part]


def _escape_for_filter(name: str) -> str:
    """Folder names with * ? [ ] { } \\ in them must match literally, not as a pattern."""
    return _FILTER_SPECIAL_CHARACTERS.sub(r"\\\1", name)
