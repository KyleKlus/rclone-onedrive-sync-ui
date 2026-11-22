"""!
@file pair_job.py
@brief One folder pair's sync job, run in a background thread.

A ``PairJob`` runs rclone for exactly ONE folder pair, in its own background
thread, and keeps the state of that pair (running / done / ...).
``SyncManager`` creates one job per active pair and starts them all together;
the job itself knows nothing about the other pairs. (They cannot get in each
other's way: pairs with clashing folders cannot exist, and a pair that lies
inside another one is excluded from it, see pair_relations.py.)

Life cycle of one job
---------------------
    IDLE --start()--> RUNNING --finished--> SUCCEEDED | FAILED
                         |
                  --request_stop()--> STOPPING --finished--> CANCELLED
"""

import shlex
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from . import config
from .command.log_buffer import LogBuffer
from .command.rclone import FilterFiles, RcloneCommandBuilder, RcloneRunner
from .errors import RcloneNotFoundError
from .models import RunOptions, SyncMode, SyncState
from .pairs import FolderPair
from .remote_health import (
    SOURCE_RUN,
    RemoteHealth,
    find_expired_login_line,
    reconnect_command,
    remote_name_of,
)

_ACCESS_FILE_CONTENT = (
    "This file is used by 'rclone bisync --check-access'.\n"
    "It proves that both sides are reachable. Do not delete it.\n"
)

STOPPED_MESSAGE = (
    "Stopped by you. Files that were mid-transfer may be incomplete; run again to finish."
)


class _StepFailed(Exception):
    """!
    @brief Internal exception: one step of a job failed and the job must be aborted.
    """


def describe_run(options: RunOptions, pair_count: int = 1) -> str:
    """!
    @brief Build the plain-words sentence for "a sync is running", used in the UI and the log.
    @param options What the user asked for (mode, resync, dry run).
    @param pair_count How many folder pairs take part in the run; only mentioned when not 1.
    @return The sentence to show.
    """
    scope = "" if pair_count == 1 else f" for {pair_count} folder pairs"
    if options.mode is SyncMode.DOWNLOAD:
        text = f"Download is running{scope}. This PC is being made to match the remote."
    elif options.resync:
        text = f"First-time setup is running{scope} (resync). The remote wins on conflicts."
    else:
        text = f"Two-way sync is running{scope}. The remote wins on conflicts."
    if options.dry_run:
        text += " DRY RUN: no files are changed."
    return text


def expired_login_message(remote_name: str) -> str:
    """!
    @brief Build the plain-words explanation for a pair that failed because its login expired.
    @param remote_name Name of the rclone remote whose login expired.
    @return The message, including the command that signs in again.
    """
    return (
        f"The login for the remote '{remote_name}' has expired. "
        f"Sign in again by running this in a terminal: {reconnect_command(remote_name)}"
    )


def idle_runtime() -> dict:
    """!
    @brief Build what a pair reports when it is not part of the latest run.
    @return A dict with the same keys as ``PairJob.snapshot``.
    """
    return {
        "state": SyncState.IDLE.value,
        "message": "",
        "started_at": None,
        "finished_at": None,
        "exit_code": None,
        "needs_resync": False,
    }


class PairJob:
    """!
    @brief Syncs one folder pair in a background thread and reports its own state.

    Every attribute that changes while the job runs (state, message, timestamps,
    exit code, stop/resync/login flags) is protected by one lock, ``self._lock``.
    """

    def __init__(
        self,
        pair: FolderPair,
        options: RunOptions,
        *,
        command_builder: RcloneCommandBuilder,
        filter_files: FilterFiles,
        runner: RcloneRunner,
        log_buffer: LogBuffer,
        on_finished: Callable[["PairJob"], None],
        remote_health: RemoteHealth,
        automatic_exclusions: tuple = (),
    ) -> None:
        """!
        @brief Create a job for one folder pair; nothing runs until ``start()``.
        @param pair The folder pair to sync.
        @param options What the user asked for (mode, resync, dry run).
        @param command_builder Builds the rclone command lines.
        @param filter_files Writes the filter file with the exclusions.
        @param runner Runs rclone. Must be used by this job only: every job has its own, so stopping one pair never touches another pair's rclone.
        @param log_buffer The live log that rclone output and app messages are written to.
        @param on_finished Called (from the job's thread) when the job is over.
        @param remote_health Told when rclone says the remote's login has expired, and when a run with the remote worked after all.
        @param automatic_exclusions Filter patterns added to the user's own: the folders of pairs that lie inside this one and are synced by those pairs. Default: none.
        """
        self.pair = pair
        self._automatic_exclusions = automatic_exclusions
        self._options = options
        self._command_builder = command_builder
        self._filter_files = filter_files
        self._runner = runner
        self._log = log_buffer
        self._on_finished = on_finished
        self._remote_health = remote_health
        self._remote_name = remote_name_of(pair.setup.remote)

        self._lock = threading.Lock()
        self._state = SyncState.IDLE
        self._message = "Starting."
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._stop_requested = False
        self._needs_resync = False
        self._login_expired = False

    @property
    def state(self) -> SyncState:
        """!
        @brief Get the current state of this pair's job.
        @return The state.
        """
        with self._lock:
            return self._state

    @property
    def message(self) -> str:
        """!
        @brief Get the plain-words message describing the current state.
        @return The message.
        """
        with self._lock:
            return self._message

    @property
    def needs_resync(self) -> bool:
        """!
        @brief Tell whether rclone reported that a first-time setup (resync) is required.
        @return True if it did.
        """
        with self._lock:
            return self._needs_resync

    @property
    def login_expired(self) -> bool:
        """!
        @brief Tell whether rclone reported that the remote's login has expired.
        @return True if it did.
        """
        with self._lock:
            return self._login_expired

    @property
    def remote_name(self) -> str:
        """!
        @brief Get the name of the rclone remote this pair uses.
        @return The remote name without folder.
        """
        return self._remote_name

    def snapshot(self) -> dict:
        """!
        @brief Collect everything the UI shows about this pair's run.
        @return A dict with state, message, started_at, finished_at, exit_code and needs_resync (see also ``idle_runtime``).
        """
        with self._lock:
            return {
                "state": self._state.value,
                "message": self._message,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "exit_code": self._exit_code,
                "needs_resync": self._needs_resync,
            }

    def start(self) -> None:
        """!
        @brief Begin syncing in the background. Called by the SyncManager.
        """
        with self._lock:
            self._state = SyncState.RUNNING
            self._started_at = time.time()
            self._message = describe_run(self._options)
        threading.Thread(target=self._run, name=f"sync-{self.pair.id}", daemon=True).start()

    def request_stop(self) -> None:
        """!
        @brief Ask this pair's rclone to exit. Called by the SyncManager.

        Does nothing if the job is already stopping or finished. The job reports
        CANCELLED itself once it has stopped.
        """
        with self._lock:
            if self._state is not SyncState.RUNNING:
                return
            self._state = SyncState.STOPPING
            self._stop_requested = True
            self._message = "Stopping... waiting for rclone to exit."
        self._runner.terminate()

    def _run(self) -> None:
        """!
        @brief Do everything that happens between "start" and "finished" for this pair.

        Runs in the background thread. Any unexpected exception is caught as a
        last line of defence so the thread never dies silently; the manager is
        always notified through ``on_finished`` so it may start waiting pairs.
        """
        setup = self.pair.setup
        exit_code: Optional[int] = None
        error_message: Optional[str] = None
        try:
            self._log_app(describe_run(self._options))
            filter_path = self._write_filter_file()

            if self._options.resync:
                self._prepare_access_files()

            command = self._command_builder.build_sync_command(
                self._options.mode,
                setup,
                filter_path,
                resync=self._options.resync,
                dry_run=self._options.dry_run,
            )
            self._log_app("$ " + shlex.join(command))
            exit_code = self._runner.run(command, self._handle_rclone_line)
        except (RcloneNotFoundError, _StepFailed) as error:
            error_message = str(error)
        except Exception as error:
            error_message = f"Unexpected error: {error}"

        try:
            self._finish(exit_code, error_message)
        finally:
            self._on_finished(self)

    def _write_filter_file(self) -> Path:
        """!
        @brief Write the filter file: the user's exclusions plus the folders that other folder pairs sync instead.
        @return Path of the written filter file.
        """
        exclusions = self.pair.setup.exclusions
        for pattern in self._automatic_exclusions:
            if pattern not in exclusions:
                exclusions = exclusions + (pattern,)
                self._log_app(f"Skipping {pattern} (it belongs to another folder pair, which syncs it).")
        return self._filter_files.write(self.pair.id, exclusions)

    def _prepare_access_files(self) -> None:
        """!
        @brief Make sure the RCLONE_TEST file exists on both sides, as required by ``bisync --check-access``.
        @throws _StepFailed When the file could not be placed on the remote.

        Only done during first-time setup.
        """
        setup = self.pair.setup
        local_file = Path(setup.local_path) / config.ACCESS_CHECK_FILENAME
        if not local_file.exists():
            local_file.write_text(_ACCESS_FILE_CONTENT, encoding="utf-8")
            self._log_app(f"Created access-check file {local_file}")

        command = self._command_builder.build_access_file_upload(setup, local_file)
        self._log_app("$ " + shlex.join(command))
        exit_code = self._runner.run(command, self._handle_rclone_line)
        if exit_code != 0:
            raise _StepFailed("Could not place the access-check file on the remote.")

    def _handle_rclone_line(self, line: str) -> None:
        """!
        @brief Handle one line rclone printed: log it and watch for resync and expired-login hints.
        @param line The output line.
        """
        self._log.append(line, source=self.pair.name)
        if "must run --resync" in line.lower():
            with self._lock:
                self._needs_resync = True
        expired_line = find_expired_login_line(line)
        if expired_line is not None:
            with self._lock:
                self._login_expired = True
            self._remote_health.mark_expired(self._remote_name, expired_line, SOURCE_RUN)

    def _finish(self, exit_code: Optional[int], error_message: Optional[str]) -> None:
        """!
        @brief Decide the final state and tell the user in plain words.
        @param exit_code Exit code of rclone, or None if it never ran.
        @param error_message Reason the job failed before or besides rclone's exit code, or None.
        """
        with self._lock:
            self._finished_at = time.time()
            self._exit_code = exit_code

            if self._stop_requested:
                self._state = SyncState.CANCELLED
                self._message = STOPPED_MESSAGE
            elif error_message is None and exit_code == 0:
                self._state = SyncState.SUCCEEDED
                self._message = "Finished successfully. Everything is up to date."
                self._remote_health.mark_ok(self._remote_name)
            elif self._login_expired:
                self._state = SyncState.FAILED
                self._message = expired_login_message(self._remote_name)
            else:
                self._state = SyncState.FAILED
                self._message = error_message or f"rclone stopped with an error (exit code {exit_code}). See the log."
                if self._needs_resync:
                    self._message += " rclone says a first-time setup (resync) is required."

            final_state = self._state
            final_message = self._message

        level = "error" if final_state is SyncState.FAILED else "app"
        self._log.append(f"== {final_state.value.upper()}: {final_message}", level=level, source=self.pair.name)

    def _log_app(self, text: str) -> None:
        """!
        @brief Write a line of this app (not of rclone) to the log, tagged with the pair's name.
        @param text The line to write.
        """
        self._log.append(text, level="app", source=self.pair.name)
