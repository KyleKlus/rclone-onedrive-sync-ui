"""
The API: maps URLs like ``GET /api/status`` to actions.

This module knows nothing about HTTP sockets or headers. It receives a
method, a path, query parameters and an already-parsed JSON body, and
returns an ``ApiResponse``. That keeps it simple to read and to test.

Endpoints
---------
GET  /api/status     Current system state.
GET  /api/setup   Current user setup.
GET  /api/setup/defaults   The default values (used by "Reset to defaults").
PUT  /api/setup   Validate and save setup (not while a sync runs).
POST /api/sync       Start a job. Body: {"mode", "resync", "dry_run"}.
POST /api/stop       Ask the running job to stop.
GET  /api/log        Log lines. Query: ?after=<last id the client has seen>.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from .errors import SetupError, SyncBusyError, SyncConfigError
from .log_buffer import LogBuffer
from .models import SyncMode
from .setup import AppSetup, SetupStore
from .sync_manager import SyncManager


@dataclass(frozen=True)
class ApiResponse:
    """A status code plus a JSON-serialisable payload."""

    status: int
    payload: dict


class ApiRouter:
    """Dispatches API requests to the right handler method."""

    def __init__(
        self,
        setup_store: SetupStore,
        sync_manager: SyncManager,
        log_buffer: LogBuffer,
    ) -> None:
        self._setup_store = setup_store
        self._sync_manager = sync_manager
        self._log = log_buffer

        # (HTTP method, path) -> handler
        self._routes: dict = {
            ("GET", "/api/status"): self._get_status,
            ("GET", "/api/setup"): self._get_setup,
            ("GET", "/api/setup/defaults"): self._get_default_setup,
            ("PUT", "/api/setup"): self._put_setup,
            ("POST", "/api/sync"): self._post_sync,
            ("POST", "/api/stop"): self._post_stop,
            ("GET", "/api/log"): self._get_log,
        }

    def handle(self, method: str, path: str, query: dict, body: Optional[dict]) -> ApiResponse:
        """Run the matching handler and turn our exceptions into HTTP statuses."""
        handler: Optional[Callable] = self._routes.get((method, path))
        if handler is None:
            path_exists = any(route_path == path for _, route_path in self._routes)
            if path_exists:
                return ApiResponse(405, {"error": "Method not allowed for this endpoint."})
            return ApiResponse(404, {"error": "Unknown API endpoint."})

        try:
            return handler(query, body or {})
        except (SetupError, SyncConfigError) as error:
            return ApiResponse(400, {"error": str(error)})
        except SyncBusyError as error:
            return ApiResponse(409, {"error": str(error)})

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _get_status(self, query: dict, body: dict) -> ApiResponse:
        return ApiResponse(200, self._sync_manager.status())

    def _get_setup(self, query: dict, body: dict) -> ApiResponse:
        return ApiResponse(200, self._setup_store.get().to_dict())

    def _get_default_setup(self, query: dict, body: dict) -> ApiResponse:
        """The defaults live in config.py; the UI asks for them instead of copying them."""
        return ApiResponse(200, AppSetup().to_dict())

    def _put_setup(self, query: dict, body: dict) -> ApiResponse:
        if self._sync_manager.is_busy():
            raise SyncBusyError("Setup is locked while a sync is running.")
        saved = self._setup_store.update(body)
        return ApiResponse(200, saved.to_dict())

    def _post_sync(self, query: dict, body: dict) -> ApiResponse:
        try:
            mode = SyncMode(body.get("mode"))
        except ValueError:
            raise SyncConfigError("Unknown sync mode. Use 'bisync' or 'download'.") from None

        resync = body.get("resync", False)
        dry_run = body.get("dry_run", False)
        if not isinstance(resync, bool) or not isinstance(dry_run, bool):
            raise SyncConfigError("'resync' and 'dry_run' must be true or false.")

        self._sync_manager.start(mode, resync=resync, dry_run=dry_run)
        return ApiResponse(202, self._sync_manager.status())

    def _post_stop(self, query: dict, body: dict) -> ApiResponse:
        self._sync_manager.stop()
        return ApiResponse(200, self._sync_manager.status())

    def _get_log(self, query: dict, body: dict) -> ApiResponse:
        try:
            after = int(query.get("after", ["0"])[0])
        except ValueError:
            raise SyncConfigError("'after' must be a whole number.") from None

        entries = self._log.entries_after(after)
        last_id = entries[-1].id if entries else after
        return ApiResponse(200, {
            "entries": [entry.to_dict() for entry in entries],
            "last_id": last_id,
        })
