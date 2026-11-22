"""!
@file remotes.py
@brief Asks rclone which remotes ("cloud accounts") are set up on this PC.

rclone keeps its remotes in its own config file (created with ``rclone config``).
This module never reads that file itself: it runs ``rclone listremotes --long``
and understands the answer. That way it also sees remotes that come from
environment variables, and it keeps working if rclone changes where it stores things.

The file has three parts, from the inside out:

1. ``RemoteInfo``      one remote: its name and its type (``onedrive``, ``drive``, ...)
2. ``RemoteListing``   the answer to "which remotes exist?": a list, or an error text
3. ``RemoteCatalog``   runs rclone and turns its output into a ``RemoteListing``

The catalog never raises: when rclone cannot be asked, the listing carries an error
message instead, so the UI can show it next to an otherwise working form.
"""

import subprocess
from dataclasses import dataclass

from .. import config
from .rclone import RcloneCommandBuilder


@dataclass(frozen=True)
class RemoteInfo:
    """!
    @brief One remote from ``rclone config``.

    Attributes: ``name`` is the remote's name without the colon ("onedrive");
    ``type`` is the kind of cloud ("onedrive", "drive", "iclouddrive", "s3", ...).
    """

    name: str
    type: str

    def to_dict(self) -> dict:
        """!
        @brief Convert the remote to a JSON-friendly dict.
        @return A dict with the keys "name" and "type".
        """
        return {"name": self.name, "type": self.type}


@dataclass(frozen=True)
class RemoteListing:
    """!
    @brief The remotes rclone knows, or the reason why they could not be listed.

    Attributes: ``remotes`` is a tuple of ``RemoteInfo``; ``error`` is empty when
    rclone answered, otherwise a sentence for the user.
    """

    remotes: tuple = ()
    error: str = ""

    def to_dict(self) -> dict:
        """!
        @brief Convert the listing to a JSON-friendly dict.
        @return A dict with the keys "remotes" and "error".
        """
        return {"remotes": [remote.to_dict() for remote in self.remotes], "error": self.error}


class RemoteCatalog:
    """!
    @brief Lists the remotes that rclone has configured.
    """

    def __init__(
        self,
        command_builder: RcloneCommandBuilder,
        timeout_seconds: float = config.REMOTE_LIST_TIMEOUT_SECONDS,
    ) -> None:
        """!
        @brief Create a catalog.
        @param command_builder Builds the ``listremotes`` command line.
        @param timeout_seconds How long to wait for rclone's answer.
        """
        self._command_builder = command_builder
        self._timeout_seconds = timeout_seconds

    def list_remotes(self) -> RemoteListing:
        """!
        @brief Run ``rclone listremotes --long``.
        @return A listing with the remotes or an error text; it never raises.
        """
        command = self._command_builder.build_list_remotes_command()
        try:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError:
            return RemoteListing(error=f"Could not start '{command[0]}'. Is rclone installed and on your PATH?")
        except subprocess.TimeoutExpired:
            return RemoteListing(error="rclone did not answer in time while listing the remotes.")

        if result.returncode != 0:
            detail = _last_line(result.stderr) or f"exit code {result.returncode}"
            return RemoteListing(error=f"rclone could not list the remotes ({detail}).")
        return RemoteListing(remotes=parse_remote_listing(result.stdout))


def parse_remote_listing(output: str) -> tuple:
    """!
    @brief Understand the output of ``rclone listremotes --long``.
    @param output The text rclone printed.
    @return A tuple of ``RemoteInfo``.

    Each line is the remote's name with a colon, then its type, padded with spaces:

        onedrive:    onedrive
        my-drive:    drive

    Lines that do not look like that (blank lines, a stray warning) are ignored.
    """
    remotes = []
    for line in output.splitlines():
        name, separator, remote_type = line.partition(":")
        name = name.strip()
        if not separator or not name:
            continue
        remotes.append(RemoteInfo(name=name, type=remote_type.strip()))
    return tuple(remotes)


def _last_line(text: str) -> str:
    """!
    @brief Pick the last non-empty line of a text; rclone puts the actual reason there.
    @param text Usually rclone's stderr.
    @return The stripped line, or an empty string if there is none.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""
