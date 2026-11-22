"""!
@file sync_manager.py
@brief Owns the overall system state and runs one job per folder pair.

Life cycle of a run (the overall state the UI shows)::

    IDLE / SUCCEEDED / FAILED / CANCELLED
        --start()-->  RUNNING  --all pairs finished-->  SUCCEEDED | FAILED
                         |
                      --stop()-->  STOPPING  --all pairs finished-->  CANCELLED

``start()`` creates one ``PairJob`` for every ACTIVE folder pair (pairs that are
switched off are skipped) and starts them all at once, in parallel.

Nothing is synced twice: when one pair lies inside another one, the outer pair
gets the inner folder as an automatic exclusion (see pair_relations.py). Pairs
whose folders clash in any other way cannot be saved, and a run refuses to
start if such pairs exist anyway (e.g. from an edited pairs.json).

Only one run can exist at a time. Every job runs in its own background thread
so the web server stays responsive and the UI can watch the log live.
"""

import shutil
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from .command.log_buffer import LogBuffer
from .command.rclone import FilterFiles, RcloneCommandBuilder, RcloneRunner
from .errors import SyncBusyError, SyncConfigError
from .models import RunOptions, SyncMode, SyncState
from .pair_job import STOPPED_MESSAGE, PairJob, describe_run, idle_runtime
from .pair_relations import automatic_exclusions, find_conflict, lies_inside
from .pairs import FolderPair, FolderPairStore
from .remote_health import RemoteHealth, reconnect_command


class SyncManager:
    """!
    @brief Starts, stops and reports on sync runs.

    All run state (state, message, options, timestamps, stop flag and the jobs
    of the latest run, by pair id in the order the pairs were listed) is
    protected by one lock.
    """

    def __init__(
        self,
        pair_store: FolderPairStore,
        log_buffer: LogBuffer,
        command_builder: RcloneCommandBuilder,
        filter_files: FilterFiles,
        runner_factory: Callable[[], RcloneRunner],
        rclone_binary: str,
        remote_health: RemoteHealth,
    ) -> None:
        """!
        @brief Create a manager in the IDLE state.
        @param pair_store Where the folder pairs are kept.
        @param log_buffer The live log that jobs write to.
        @param command_builder Builds the rclone command lines.
        @param filter_files Writes the filter files of the pairs.
        @param runner_factory Called once per job, so every job gets its own runner.
        @param rclone_binary Name or path of the rclone executable.
        @param remote_health Shared record of which remote logins have expired.
        """
        self._pair_store = pair_store
        self._log = log_buffer
        self._command_builder = command_builder
        self._filter_files = filter_files
        self._runner_factory = runner_factory
        self._rclone_binary = rclone_binary
        self._remote_health = remote_health

        self._lock = threading.Lock()
        self._state = SyncState.IDLE
        self._message = "Ready. Nothing is running."
        self._options: Optional[RunOptions] = None
        self._started_at: Optional[float] = None
        self._finished_at: Optional[float] = None
        self._stop_requested = False
        self._jobs: dict = {}

    def status(self) -> dict:
        """!
        @brief Take a snapshot of everything the UI needs to describe the system state.
        @return Dictionary with the overall state, message, options, timestamps and every pair's state.
        """
        pairs = self._pair_store.all()
        rclone_available = shutil.which(self._rclone_binary) is not None

        with self._lock:
            described_pairs = [self._describe_pair(pair, pairs) for pair in pairs]
            return {
                "state": self._state.value,
                "message": self._message,
                "mode": self._options.mode.value if self._options else None,
                "resync": self._options.resync if self._options else False,
                "dry_run": self._options.dry_run if self._options else False,
                "started_at": self._started_at,
                "finished_at": self._finished_at,
                "needs_resync": any(item["needs_resync"] for item in described_pairs),
                "rclone_available": rclone_available,
                "pairs": described_pairs,
            }

    def is_busy(self) -> bool:
        """!
        @brief Tell whether a run is going (running or stopping).
        @return True while a run is active.
        """
        with self._lock:
            return self._state in (SyncState.RUNNING, SyncState.STOPPING)

    def start(self, mode: SyncMode, resync: bool = False, dry_run: bool = False) -> None:
        """!
        @brief Start a run for all active folder pairs, in the background.
        @param mode Two-way or one-way sync.
        @param resync True for the first-time setup of two-way sync.
        @param dry_run True to only show what would happen.
        @throws SyncConfigError If there is nothing to sync or a pair is incomplete.
        @throws SyncBusyError If a run is already going.

        ``resync=True`` is the first-time setup for two-way sync: it places
        the access-check files and builds the initial baseline.
        """
        if resync and mode is not SyncMode.BISYNC:
            raise SyncConfigError("First-time setup only applies to two-way sync.")

        all_pairs = self._pair_store.all()
        pairs = self._pairs_to_sync(all_pairs)
        options = RunOptions(mode, resync=resync, dry_run=dry_run)

        with self._lock:
            if self._state in (SyncState.RUNNING, SyncState.STOPPING):
                raise SyncBusyError("A sync is already running. Stop it first.")
            self._state = SyncState.RUNNING
            self._options = options
            self._message = describe_run(options, len(pairs))
            self._started_at = time.time()
            self._finished_at = None
            self._stop_requested = False
            self._jobs = {pair.id: self._create_job(pair, options, all_pairs) for pair in pairs}
            for job in self._jobs.values():
                job.start()

    def stop(self) -> bool:
        """!
        @brief Ask every pair to stop.
        @return False if nothing was running, otherwise True.
        """
        with self._lock:
            if self._state is not SyncState.RUNNING:
                return False
            self._state = SyncState.STOPPING
            self._stop_requested = True
            self._message = "Stopping... waiting for rclone to exit."
            for job in self._jobs.values():
                job.request_stop()
            outcome = self._finish_run_if_done_locked()
        self._log.append("Stop requested. Asking rclone to exit...", level="app")
        self._log_outcome(outcome)
        return True

    def _create_job(self, pair: FolderPair, options: RunOptions, all_pairs: list) -> PairJob:
        """!
        @brief Create the job for one folder pair.
        @param pair The pair to sync.
        @param options What the user asked for.
        @param all_pairs All pairs, including the switched-off ones.
        @return The new job (not started).

        ``all_pairs`` includes the switched-off ones: a pair that lies inside this one is
        always left out of it. (Otherwise switching a pair on or off would change this
        pair's filters, and bisync demands a new first-time setup whenever they change.)
        """
        others = [other.setup for other in all_pairs if other.id != pair.id]
        return PairJob(
            pair,
            options,
            command_builder=self._command_builder,
            filter_files=self._filter_files,
            runner=self._runner_factory(),
            log_buffer=self._log,
            on_finished=self._job_finished,
            remote_health=self._remote_health,
            automatic_exclusions=automatic_exclusions(pair.setup, others),
        )

    def _job_finished(self, job: PairJob) -> None:
        """!
        @brief Handle the end of one job; called from that job's own thread.
        @param job The job that is over.
        """
        with self._lock:
            outcome = self._finish_run_if_done_locked()
        self._log_outcome(outcome)

    def _finish_run_if_done_locked(self) -> Optional[tuple]:
        """!
        @brief Decide the final overall state if every job is over.
        @return ``(state, message)`` when the run just ended, otherwise None.

        The caller must hold the lock.
        """
        if self._state not in (SyncState.RUNNING, SyncState.STOPPING):
            return None
        if not all(job.state.is_finished for job in self._jobs.values()):
            return None

        self._finished_at = time.time()
        self._state, self._message = self._summarize_run()
        return self._state, self._message

    def _summarize_run(self) -> tuple:
        """!
        @brief Work out the final overall state and a message in plain words.
        @return ``(state, message)``.
        """
        jobs = list(self._jobs.values())
        if self._stop_requested:
            return SyncState.CANCELLED, STOPPED_MESSAGE

        failed = [job for job in jobs if job.state is SyncState.FAILED]
        if not failed:
            if len(jobs) == 1:
                return SyncState.SUCCEEDED, "Finished successfully. Everything is up to date."
            return SyncState.SUCCEEDED, f"All {len(jobs)} folder pairs finished successfully. Everything is up to date."

        if len(jobs) == 1:
            return SyncState.FAILED, failed[0].message

        message = f"{len(failed)} of {len(jobs)} folder pairs failed: {_join_names(failed)}. See the log."
        needing_resync = [job for job in failed if job.needs_resync]
        if needing_resync:
            message += f" rclone says a first-time setup (resync) is required for: {_join_names(needing_resync)}."
        expired = sorted({job.remote_name for job in failed if job.login_expired})
        for name in expired:
            message += f" The login for '{name}' has expired: run {reconnect_command(name)} in a terminal."
        return SyncState.FAILED, message

    def _log_outcome(self, outcome: Optional[tuple]) -> None:
        """!
        @brief Write the closing line of a run into the log.
        @param outcome ``(state, message)`` from the run that just ended, or None if the run is not over (nothing is written).
        """
        if outcome is None:
            return
        state, message = outcome
        level = "error" if state is SyncState.FAILED else "app"
        self._log.append(f"== {state.value.upper()}: {message}", level=level)

    def _describe_pair(self, pair: FolderPair, all_pairs: list) -> dict:
        """!
        @brief Build one entry of ``status()["pairs"]``: the pair itself plus how its sync is going.
        @param pair The pair to describe.
        @param all_pairs All pairs.
        @return The entry as a dictionary.

        A result only describes the pair as it was when it ran. If the pair was
        changed afterwards (setup edited, switched on or off), it is shown as not
        run yet. ``skips_pairs`` names the pairs this one leaves out because they
        lie inside it and sync that folder themselves.
        """
        job = self._jobs.get(pair.id)
        is_current = job is not None and job.pair.setup == pair.setup and job.pair.enabled == pair.enabled

        skips_pairs = [other.name for other in all_pairs
                       if other.id != pair.id and lies_inside(other.setup, pair.setup)]
        return {
            "id": pair.id,
            "name": pair.name,
            "enabled": pair.enabled,
            "local_path": pair.setup.local_path,
            "remote": pair.setup.remote,
            **(job.snapshot() if is_current else idle_runtime()),
            "skips_pairs": skips_pairs,
        }

    def _pairs_to_sync(self, all_pairs: list) -> list:
        """!
        @brief Pick the active pairs, after checking that a run could possibly work.
        @param all_pairs All pairs.
        @return The pairs that are switched on.
        @throws SyncConfigError If rclone is missing, no pair is active, a pair is incomplete or pairs clash.
        """
        if shutil.which(self._rclone_binary) is None:
            raise SyncConfigError(
                f"rclone was not found ('{self._rclone_binary}'). Install it or add it to your PATH."
            )
        pairs = [pair for pair in all_pairs if pair.enabled]
        if not pairs:
            raise SyncConfigError("There is no active folder pair. Add one, or switch one on in the list.")
        for pair in pairs:
            self._check_pair_ready(pair)
        self._check_no_conflicts(pairs)
        return pairs

    @staticmethod
    def _check_no_conflicts(pairs: list) -> None:
        """!
        @brief Make sure no two pairs would work on the same files.
        @param pairs The pairs that would run.
        @throws SyncConfigError If two pairs clash.

        The pairs store refuses clashing pairs, so this only fires if pairs.json
        was edited by hand. Two such pairs would work on the same files, so no
        run is started.
        """
        for index, pair in enumerate(pairs):
            for other in pairs[index + 1:]:
                reason = find_conflict(pair.setup, other.setup)
                if reason:
                    raise SyncConfigError(
                        f"The folder pairs '{pair.name}' and '{other.name}' clash. {reason} "
                        "Change or switch off one of them."
                    )

    @staticmethod
    def _check_pair_ready(pair: FolderPair) -> None:
        """!
        @brief Fail early if the job of a pair could not possibly work.
        @param pair The pair to check.
        @throws SyncConfigError With a message naming the pair, if the local folder is unset or missing.
        """
        local_path = pair.setup.local_path
        if not local_path:
            raise SyncConfigError(f"Folder pair '{pair.name}': set the local folder in its setup first.")
        if not Path(local_path).is_dir():
            raise SyncConfigError(f"Folder pair '{pair.name}': the local folder does not exist: {local_path}")


def _join_names(jobs: list) -> str:
    """!
    @brief Join the pair names of some jobs for a message.
    @param jobs The jobs.
    @return The quoted names separated by commas, e.g. 'Docs', 'Photos'.
    """
    return ", ".join(f"'{job.pair.name}'" for job in jobs)
