"""!
@file pair_relations.py
@brief Decide how two folder pairs relate to each other, so that nothing is synced twice.

Every pair maps a local folder to a folder on a remote (a cloud). Looking at two
pairs there are exactly three cases:

SEPARATE   Neither the local nor the remote folders touch. Nothing to do.

NESTED     One pair (the INNER one) lies inside the other (the OUTER one) on BOTH
           sides, at the SAME position:

               outer   /home/me/Docs          <->  cloud:Docs
               inner   /home/me/Docs/Photos   <->  cloud:Docs/Photos

           The outer pair would sync the inner folder too. That is the "synced
           twice" case, and it is solved automatically: the outer pair EXCLUDES
           the inner folder (``/Photos/``), the inner pair syncs it.

CONFLICT   Anything else that touches. For example the same remote folder
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

_FILTER_SPECIAL_CHARACTERS = re.compile(r"([*?\[\]{}\\])")


class RelationKind(str, Enum):
    """!
    @brief The three ways two folder pairs can relate: SEPARATE, NESTED or CONFLICT.
    """

    SEPARATE = "separate"
    NESTED = "nested"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class PairRelation:
    """!
    @brief The result of ``relate``.

    Attributes:
    kind - Which relation it is.
    reason - CONFLICT only: why, in plain words.
    first_is_inner - NESTED only: True if the first pair is the one lying inside the other.
    inner_folder - NESTED only: the inner folder's path below the outer one, as parts.
    """

    kind: RelationKind
    reason: str = ""
    first_is_inner: bool = False
    inner_folder: tuple = ()


_SEPARATE = PairRelation(RelationKind.SEPARATE)


def relate(first: PairSetup, second: PairSetup) -> PairRelation:
    """!
    @brief Classify two pairs (see the module description).
    @param first Setup of the first pair.
    @param second Setup of the second pair.
    @return The relation between them.

    A pair without a local folder counts as SEPARATE, because "not configured
    yet" must not be mistaken for the current directory. Both sides nested the
    same way is only NESTED if the inner folder is at the same spot on both sides.
    """
    if not first.local_path or not second.local_path:
        return _SEPARATE

    local_how, local_below = _compare_local(first.local_path, second.local_path)
    remote_how, remote_below = _compare_remote(first.remote, second.remote)

    if local_how == "separate" and remote_how == "separate":
        return _SEPARATE
    if local_how == "same" and remote_how == "same":
        return _conflict("They use the same local folder and the same remote folder.")
    if local_how == "separate":
        return _conflict("Their remote folders overlap, but their local folders do not.")
    if remote_how == "separate":
        return _conflict("Their local folders overlap, but their remote folders do not.")
    if local_how == "same" or remote_how == "same":
        return _conflict("One side uses the same folder, but on the other side one folder lies inside the other.")
    if local_how != remote_how:
        return _conflict("Their local folders and their remote folders are nested in opposite directions.")

    if [part.casefold() for part in local_below] != remote_below:
        return _conflict(
            f"The inner local folder is at '{'/'.join(local_below)}' inside the outer one, "
            f"but the inner remote folder is at '{'/'.join(remote_below)}'. Both must match."
        )
    return PairRelation(
        RelationKind.NESTED,
        first_is_inner=(local_how == "first_inside"),
        inner_folder=tuple(local_below),
    )


def find_conflict(setup: PairSetup, other: PairSetup) -> Optional[str]:
    """!
    @brief Find the reason why two pairs cannot exist together.
    @param setup Setup of one pair.
    @param other Setup of the other pair.
    @return The reason in plain words, or None if they can exist together.
    """
    relation = relate(setup, other)
    return relation.reason if relation.kind is RelationKind.CONFLICT else None


def lies_inside(candidate: PairSetup, container: PairSetup) -> bool:
    """!
    @brief Tell whether a pair is nested inside another (and so is skipped by it).
    @param candidate Setup of the possible inner pair.
    @param container Setup of the possible outer pair.
    @return True if ``candidate`` is nested inside ``container``.
    """
    relation = relate(container, candidate)
    return relation.kind is RelationKind.NESTED and not relation.first_is_inner


def inner_folders(setup: PairSetup, others: Iterable[PairSetup]) -> list:
    """!
    @brief Collect the inner folders of every other pair that lies inside ``setup``.
    @param setup Setup of the outer pair.
    @param others Setups of the other pairs.
    @return Sorted lists of path parts. These are the folders ``setup`` must not sync.
    """
    return sorted(
        relate(setup, other).inner_folder for other in others if lies_inside(other, setup)
    )


def automatic_exclusions(setup: PairSetup, others: Iterable[PairSetup]) -> tuple:
    """!
    @brief Build the filter patterns that keep ``setup`` out of the folders of the pairs inside it.
    @param setup Setup of the outer pair.
    @param others Setups of the other pairs.
    @return A tuple of patterns. ``/Photos/`` means: the top-level folder Photos (relative to the synced folder).
    """
    return tuple("/" + "/".join(_escape_for_filter(part) for part in folder) + "/"
                 for folder in inner_folders(setup, others))


def _conflict(reason: str) -> PairRelation:
    """!
    @brief Build a CONFLICT relation.
    @param reason Why the pairs clash, in plain words.
    @return The relation.
    """
    return PairRelation(RelationKind.CONFLICT, reason=reason)


def _compare_local(first: str, second: str) -> tuple:
    """!
    @brief Compare two local folders.
    @param first First local path.
    @param second Second local path.
    @return A tuple (how, parts): how is "separate", "same", "first_inside" or "second_inside"; parts is the path of the inside folder below the outside one.
    """
    first, second = _normalise_local(first), _normalise_local(second)
    try:
        common = os.path.commonpath([first, second])
    except ValueError:
        return "separate", []

    if first == second:
        return "same", []
    if common == first:
        return "second_inside", _parts(os.path.relpath(second, first))
    if common == second:
        return "first_inside", _parts(os.path.relpath(first, second))
    return "separate", []


def _compare_remote(first: str, second: str) -> tuple:
    """!
    @brief Compare two remotes of the form ``cloud:Docs/Work``, like ``_compare_local``.
    @param first First remote.
    @param second Second remote.
    @return A tuple (how, parts), as for ``_compare_local``.

    Different remotes are different clouds. Many clouds (OneDrive, iCloud, ...)
    ignore case in folder names, so the parts are lower-cased. That is the safe
    choice for the others too: folders that MIGHT be the same are treated as the
    same. A remote without a folder (``cloud:``) is the whole drive and contains
    every folder. On Windows, local paths on different drives (C: and D:) have
    nothing in common and count as separate.
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
    """!
    @brief Resolve symlinks and '..' and, on Windows, ignore upper/lower case.
    @param path A local path.
    @return The normalised path.
    """
    return os.path.normcase(os.path.realpath(path))


def _split_remote(remote: str) -> tuple:
    """!
    @brief Split a remote into its name and lower-cased folder parts.
    @param remote A remote such as ``cloud:Docs/Work``.
    @return A tuple, e.g. ``('cloud', ['docs', 'work'])``.
    """
    name, _separator, folder = remote.partition(":")
    return name, [part for part in folder.casefold().split("/") if part]


def _parts(relative_path: str) -> list:
    """!
    @brief Split a relative path into its non-empty parts.
    @param relative_path The path to split.
    @return The list of parts.
    """
    return [part for part in relative_path.split(os.sep) if part]


def _escape_for_filter(name: str) -> str:
    """!
    @brief Escape a folder name so it matches literally in a filter pattern.
    @param name A folder name, possibly containing the special characters * ? [ ] { } and backslash.
    @return The escaped name.
    """
    return _FILTER_SPECIAL_CHARACTERS.sub(r"\\\1", name)
