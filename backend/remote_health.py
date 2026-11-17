"""!
@file remote_health.py
@brief Knows which remotes have an expired login and tells the user how to fix it.

Clouds such as iCloud or OneDrive hand rclone a login that stops working after a
while. rclone then fails with an authentication error until the user signs in again
with `rclone config reconnect <remote>:`.

Two sources feed the same registry:
  - the output of every sync run (a job that sees such an error reports it), and
  - a background check that lists the top folder of every remote used by an active
    folder pair, once at startup and then every few minutes.

A remote is flagged only when rclone's output matches a known expired-login message.
A failing check for any other reason (no internet, server down) changes nothing.
"""

import subprocess
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

from . import config
from .command.rclone import RcloneCommandBuilder
from .pairs import FolderPairStore

SOURCE_RUN = "run"
SOURCE_CHECK = "check"

_MAX_REASON_LENGTH = 300


def remote_name_of(remote: str) -> str:
    """!
    @brief The name of a remote without its folder.
    @param remote A remote as saved in a folder pair, e.g. "icloud:Documents".
    @return The part before the first colon, e.g. "icloud".
    """
    return remote.partition(":")[0]


def reconnect_command(name: str) -> str:
    """!
    @brief The command the user runs in a terminal to sign in to a remote again.
    @param name A remote name without the colon.
    @return The full command line, e.g. "rclone config reconnect icloud:".
    """
    return f"rclone config reconnect {name}:"


def find_expired_login_line(text: str) -> Optional[str]:
    """!
    @brief Find the first line of rclone output that says a login has expired.
    @param text Any amount of rclone output.
    @return The matching line, shortened if it is very long, or None if nothing matches.
    """
    for line in text.splitlines():
        lowered = line.lower()
        if any(pattern in lowered for pattern in config.EXPIRED_LOGIN_PATTERNS):
            return line.strip()[:_MAX_REASON_LENGTH]
    return None


@dataclass(frozen=True)
class ExpiredLogin:
    """!
    @brief One remote whose login has expired.
    """

    name: str
    reason: str
    detected_at: float
    source: str

    def to_dict(self) -> dict:
        """!
        @brief The JSON form sent to the UI, including the command that fixes it.
        @return A dict with name, reason, detected_at, source and command.
        """
        return {
            "name": self.name,
            "reason": self.reason,
            "detected_at": self.detected_at,
            "source": self.source,
            "command": reconnect_command(self.name),
        }


class RemoteHealth:
    """!
    @brief A thread-safe list of the remotes whose login has expired.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._expired: dict = {}

    def mark_expired(self, name: str, reason: str, source: str) -> None:
        """!
        @brief Remember that a remote needs to be reconnected.
        @param name The remote name without the colon.
        @param reason The rclone output line that showed it.
        @param source SOURCE_RUN or SOURCE_CHECK.
        """
        if not name:
            return
        with self._lock:
            self._expired[name] = ExpiredLogin(name, reason, time.time(), source)

    def mark_ok(self, name: str) -> None:
        """!
        @brief Forget an expired login, because rclone just worked with the remote.
        @param name The remote name without the colon.
        """
        with self._lock:
            self._expired.pop(name, None)

    def expired(self, names: Optional[set] = None) -> list:
        """!
        @brief The remotes that are currently flagged.
        @param names If given, only remotes with one of these names are returned.
        @return A list of ExpiredLogin sorted by name.
        """
        with self._lock:
            items = list(self._expired.values())
        if names is not None:
            items = [item for item in items if item.name in names]
        return sorted(items, key=lambda item: item.name)


class RemoteHealthMonitor:
    """!
    @brief Checks the remotes of all active folder pairs in a background thread.
    """

    def __init__(
        self,
        health: RemoteHealth,
        pair_store: FolderPairStore,
        command_builder: RcloneCommandBuilder,
        is_busy: Callable[[], bool],
        interval_seconds: float = config.REMOTE_CHECK_INTERVAL_SECONDS,
        timeout_seconds: float = config.REMOTE_CHECK_TIMEOUT_SECONDS,
    ) -> None:
        """!
        @param health The registry that receives the results.
        @param pair_store Tells which remotes are in use.
        @param command_builder Builds the rclone command that probes a remote.
        @param is_busy Returns True while a sync runs; no check starts then.
        @param interval_seconds Time between two automatic rounds.
        @param timeout_seconds Longest time one remote may take to answer.
        """
        self._health = health
        self._pair_store = pair_store
        self._command_builder = command_builder
        self._is_busy = is_busy
        self._interval_seconds = interval_seconds
        self._timeout_seconds = timeout_seconds

        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopped = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._pending = False
        self._checking = False
        self._checked_at: Optional[float] = None

    def start(self) -> None:
        """!
        @brief Start the background thread. The first round begins immediately.
        """
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, name="remote-health", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """!
        @brief Ask the background thread to end.
        """
        self._stopped.set()
        self._wake.set()

    def check_now(self) -> None:
        """!
        @brief Ask for a round right away instead of waiting for the next one.
        """
        with self._lock:
            self._pending = True
        self._wake.set()

    def snapshot(self) -> dict:
        """!
        @brief What the UI shows about remote logins.
        @return A dict with the expired logins of remotes in use, whether a check is
                running or queued, and when the last round finished.
        """
        with self._lock:
            checking = self._checking or self._pending
            checked_at = self._checked_at
        used = self._used_remote_names()
        return {
            "expired": [item.to_dict() for item in self._health.expired(used)],
            "checking": checking,
            "checked_at": checked_at,
        }

    def _used_remote_names(self) -> set:
        """!
        @return The names of the remotes used by active (switched-on) folder pairs.
        """
        names = {remote_name_of(pair.setup.remote) for pair in self._pair_store.all() if pair.enabled}
        names.discard("")
        return names

    def _loop(self) -> None:
        """!
        @brief Run a round, wait for the interval or a request, repeat until stopped.
        """
        while not self._stopped.is_set():
            self._run_round()
            self._wake.wait(timeout=self._interval_seconds)
            self._wake.clear()

    def _run_round(self) -> None:
        """!
        @brief Probe every remote in use, unless a sync is running.
        """
        with self._lock:
            self._pending = False
            if self._is_busy():
                return
            self._checking = True
        try:
            for name in sorted(self._used_remote_names()):
                if self._stopped.is_set() or self._is_busy():
                    break
                self._probe(name)
        finally:
            with self._lock:
                self._checking = False
                self._checked_at = time.time()

    def _probe(self, name: str) -> None:
        """!
        @brief Ask rclone to list the top folder of one remote and record the outcome.
        @param name The remote name without the colon.
        """
        command = self._command_builder.build_probe_command(name)
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
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return

        if result.returncode == 0:
            self._health.mark_ok(name)
            return
        output = f"{result.stderr}\n{result.stdout}"
        reason = find_expired_login_line(output)
        if reason is not None:
            self._health.mark_expired(name, reason, SOURCE_CHECK)
