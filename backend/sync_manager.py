"""
The sync manager: owns the system state and runs sync jobs.

Life cycle of one job
---------------------
    IDLE / SUCCEEDED / FAILED / CANCELLED
        --start()-->  RUNNING  --finished-->  SUCCEEDED | FAILED
                         |
                      --stop()-->  STOPPING  --finished-->  CANCELLED

Only one job can run at a time. The job itself runs in a background thread
so the web server stays responsive and the UI can watch the log live.
"""

import shlex
import shutil
import threading
import time
from pathlib import Path
from typing import Optional

from . import config
from .errors import RcloneNotFoundError, SyncBusyError, SyncConfigError
from .log_buffer import LogBuffer
from .models import SyncMode, SyncState
from .rclone import FilterFile, RcloneCommandBuilder, RcloneRunner
from .setup import AppSetup, SetupStore

_ACCESS_FILE_CONTENT = (
    "This file is used by 'rclone bisync --check-access'.\n"
    "It proves that both sides are reachable. Do not delete it.\n"
)


class _StepFailed(Exception):
    """Internal: one step of a job failed and the job must be aborted."""


class SyncManager:
    """Starts, stops and reports on sync jobs."""

    def __init__(
        self,
        setup_store: SetupStore,
        log_buffer: LogBuffer,
        runner: RcloneRunner,
        command_builder: RcloneCommandBuilder,
        filter_file: FilterFile,
        rclone_binary: str,
    ) -> None:
        self._setup_store = setup_store
        self._log = log_buffer
        self._runner = runner
        self._command_builder = command_builder
        self._filter_file = filter_file
        self._rclone_binary = rclone_binary

        # Everything below is protected by self._lock.
        self._lock = threading.Lock()
        self._state = SyncState.IDLE
        self._message = "Ready. Nothing is running."
        self._mode: Optional[SyncMode] = None
        self._resync = False
        self._dry_run = False
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None
        self._exit_code: Optional[int] = None
        self._stop_requested = False
        self._needs_resync = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """A snapshot of everything the UI needs to describe the system state."""
        with self._lock:
            return {
                "state": self._state.value,
                "message": self._message,
                "mode": self._mode.value if self._mode else None,
                "resync": self._resync,
                "dry_run": self._dry_run,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "exit_code": self._exit_code,
                "needs_resync": self._needs_resync,
                "rclone_available": shutil.which(self._rclone_binary) is not None,
            }

    def is_busy(self) -> bool:
        with self._lock:
            return self._state in (SyncState.RUNNING, SyncState.STOPPING)

    def start(self, mode: SyncMode, resync: bool = False, dry_run: bool = False) -> None:
        """
        Start a job in the background.

        ``resync=True`` is the first-time setup for two-way sync: it places
        the access-check files and builds the initial baseline.

        Raises ``SyncConfigError`` if the setup is incomplete and
        ``SyncBusyError`` if a job is already running.
        """
        if resync and mode is not SyncMode.BISYNC:
            raise SyncConfigError("First-time setup only applies to two-way sync.")

        setup = self._setup_store.get()
        self._check_ready(setup)

        with self._lock:
            if self._state in (SyncState.RUNNING, SyncState.STOPPING):
                raise SyncBusyError("A sync is already running. Stop it first.")
            self._state = SyncState.RUNNING
            self._mode = mode
            self._resync = resync
            self._dry_run = dry_run
            self._message = self._describe_running(mode, resync, dry_run)
            self._started_at = time.time()
            self._finished_at = None
            self._exit_code = None
            self._stop_requested = False
            self._needs_resync = False
            self._runner.reset()

        thread = threading.Thread(
            target=self._run_job,
            args=(mode, setup, resync, dry_run),
            name="sync-job",
            daemon=True,
        )
        thread.start()

    def stop(self) -> bool:
        """Ask the running job to stop. Returns False if nothing was running."""
        with self._lock:
            if self._state is not SyncState.RUNNING:
                return False
            self._state = SyncState.STOPPING
            self._stop_requested = True
            self._message = "Stopping... waiting for rclone to exit."
        self._log.append("Stop requested. Asking rclone to exit...", level="app")
        self._runner.terminate()
        return True

    # ------------------------------------------------------------------
    # The background job
    # ------------------------------------------------------------------

    def _run_job(self, mode: SyncMode, setup: AppSetup, resync: bool, dry_run: bool) -> None:
        """Everything that happens between 'Start' and 'finished'."""
        exit_code: Optional[int] = None
        error_message: Optional[str] = None
        try:
            self._log.append(self._describe_running(mode, resync, dry_run), level="app")
            filter_path = self._filter_file.write(setup.exclusions)

            if resync:
                self._prepare_access_files(setup)

            command = self._command_builder.build_sync_command(
                mode, setup, filter_path, resync=resync, dry_run=dry_run
            )
            self._log.append("$ " + shlex.join(command), level="app")
            exit_code = self._runner.run(command, self._handle_rclone_line)
        except (RcloneNotFoundError, _StepFailed) as error:
            error_message = str(error)
        except Exception as error:  # noqa: BLE001 - last line of defence for the thread
            error_message = f"Unexpected error: {error}"
        self._finish(exit_code, error_message)

    def _prepare_access_files(self, setup: AppSetup) -> None:
        """
        Make sure the RCLONE_TEST file exists on both sides, as required by
        ``bisync --check-access``. Only done during first-time setup.
        """
        local_file = Path(setup.local_path) / config.ACCESS_CHECK_FILENAME
        if not local_file.exists():
            local_file.write_text(_ACCESS_FILE_CONTENT, encoding="utf-8")
            self._log.append(f"Created access-check file {local_file}", level="app")

        command = self._command_builder.build_access_file_upload(setup, local_file)
        self._log.append("$ " + shlex.join(command), level="app")
        exit_code = self._runner.run(command, self._handle_rclone_line)
        if exit_code != 0:
            raise _StepFailed("Could not place the access-check file on OneDrive.")

    def _handle_rclone_line(self, line: str) -> None:
        """Called for every line rclone prints."""
        self._log.append(line)
        if "must run --resync" in line.lower():
            with self._lock:
                self._needs_resync = True

    def _finish(self, exit_code: Optional[int], error_message: Optional[str]) -> None:
        """Decide the final state and tell the user in plain words."""
        with self._lock:
            self._finished_at = time.time()
            self._exit_code = exit_code

            if self._stop_requested:
                self._state = SyncState.CANCELLED
                self._message = "Stopped by you. Files that were mid-transfer may be incomplete; run again to finish."
            elif error_message is None and exit_code == 0:
                self._state = SyncState.SUCCEEDED
                self._message = "Finished successfully. Everything is up to date."
            else:
                self._state = SyncState.FAILED
                self._message = error_message or f"rclone stopped with an error (exit code {exit_code}). See the log."
                if self._needs_resync:
                    self._message += " rclone says a first-time setup (resync) is required."

            final_message = self._message
            final_state = self._state

        level = "app" if final_state is not SyncState.FAILED else "error"
        self._log.append(f"== {final_state.value.upper()}: {final_message}", level=level)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _check_ready(self, setup: AppSetup) -> None:
        """Fail early, with a clear message, if a job could not possibly work."""
        if shutil.which(self._rclone_binary) is None:
            raise SyncConfigError(
                f"rclone was not found ('{self._rclone_binary}'). Install it or add it to your PATH."
            )
        if not setup.local_path:
            raise SyncConfigError("Set the local folder in the setup first.")
        if not Path(setup.local_path).is_dir():
            raise SyncConfigError(f"The local folder does not exist: {setup.local_path}")

    @staticmethod
    def _describe_running(mode: SyncMode, resync: bool, dry_run: bool) -> str:
        if mode is SyncMode.DOWNLOAD:
            text = "Download is running. This PC is being made to match OneDrive."
        elif resync:
            text = "First-time setup is running (resync). OneDrive wins on conflicts."
        else:
            text = "Two-way sync is running. OneDrive wins on conflicts."
        if dry_run:
            text += " DRY RUN: no files are changed."
        return text
