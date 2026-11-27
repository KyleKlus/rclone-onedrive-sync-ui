"""!
@file sync_toggle.py
@brief The logic behind the tray's "Start / Stop sync" entry.

It knows nothing about pystray or any window, so it can be tested on its own
and reused on every platform.
"""

from backend.errors import SyncBusyError, SyncConfigError
from backend.models import SyncMode, SyncState
from backend.sync_manager import SyncManager

_MODE_NAMES = {
    SyncMode.BISYNC: "two-way",
    SyncMode.DOWNLOAD: "download only",
}


class SyncToggle:
    """!
    @brief One button that starts a sync when idle and stops it while one runs.

    A start uses the mode of the last real run (never a dry run), and the label
    names it, because "download only" can delete files on this computer.
    """

    def __init__(self, sync_manager: SyncManager) -> None:
        """!
        @brief Create the toggle.
        @param sync_manager Starts, stops and reports on runs.
        """
        self._sync = sync_manager

    def state(self) -> SyncState:
        """!
        @brief Get the overall sync state, e.g. to colour the tray icon.
        @return The current state.
        """
        return self._sync.state

    def label(self) -> str:
        """!
        @brief Get the text that describes what a click does right now.
        @return The menu text.
        """
        state = self._sync.state
        if state is SyncState.RUNNING:
            return "Stop sync"
        if state is SyncState.STOPPING:
            return "Stopping sync..."
        return f"Start sync ({_MODE_NAMES[self._sync.last_mode]})"

    def is_enabled(self) -> bool:
        """!
        @brief Tell whether a click can do anything.
        @return False while a run is stopping.
        """
        return self._sync.state is not SyncState.STOPPING

    def toggle(self) -> str:
        """!
        @brief Stop the running sync, or start one if none is running.
        @return "" on success, otherwise the reason why no sync could be started.
        """
        if self._sync.is_busy():
            self._sync.stop()
            return ""
        try:
            self._sync.start(self._sync.last_mode)
        except (SyncBusyError, SyncConfigError) as problem:
            return str(problem)
        return ""
