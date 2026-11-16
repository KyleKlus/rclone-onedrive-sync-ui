"""
Decides whether two folder pairs "intersect".

Two pairs must not sync at the same moment when they touch the same files,
because two rclone processes working on the same folder get in each other's
way. They touch the same files when EITHER side overlaps:

* local folders    the same folder, or one lies inside the other
* remote folders   the same remote (e.g. ``onedrive:``) AND the same folder,
                   or one folder lies inside the other

A remote without a folder (``onedrive:``) is the whole drive, so it overlaps
with every other folder on that remote.

Everything here is a pure function of the setups, which keeps it easy to test.
"""

import os

from .setup import PairSetup


def setups_overlap(first: PairSetup, second: PairSetup) -> bool:
    """True if the two pairs must not sync at the same time."""
    return (
        local_paths_overlap(first.local_path, second.local_path)
        or remote_paths_overlap(first.remote, second.remote)
    )


def local_paths_overlap(first: str, second: str) -> bool:
    """True if one folder is the other one or lies inside it. Empty paths never overlap."""
    if not first or not second:
        return False  # "not configured yet" must not be mistaken for the current directory
    first, second = _normalise_local(first), _normalise_local(second)
    try:
        # The common parent of two nested folders is the outer folder itself.
        return os.path.commonpath([first, second]) in (first, second)
    except ValueError:
        # Windows: folders on different drives (C: and D:) have nothing in common.
        return False


def remote_paths_overlap(first: str, second: str) -> bool:
    """True if both point into the same remote and one folder contains the other."""
    first_name, first_folders = _split_remote(first)
    second_name, second_folders = _split_remote(second)
    if first_name != second_name:
        return False  # different remotes are different clouds
    shorter, longer = sorted((first_folders, second_folders), key=len)
    # The shorter path must be the beginning of the longer one (an empty one is the root).
    return longer[:len(shorter)] == shorter


# ----------------------------------------------------------------------

def _normalise_local(path: str) -> str:
    """Resolve symlinks and '..' and, on Windows, ignore upper/lower case."""
    return os.path.normcase(os.path.realpath(path))


def _split_remote(remote: str) -> tuple:
    """'onedrive:Docs/Work' -> ('onedrive', ['docs', 'work']). OneDrive ignores case in folder names."""
    name, _separator, folder = remote.partition(":")
    folders = [part for part in folder.casefold().split("/") if part]
    return name, folders
