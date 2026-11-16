"""
The API: maps URLs like ``GET /api/status`` to actions.

This module knows nothing about HTTP sockets or headers. It receives a
method, a path, query parameters and an already-parsed JSON body, and
returns an ``ApiResponse``. That keeps it simple to read and to test.

Endpoints
---------
GET    /api/status               Current system state, including every folder pair's own state.
GET    /api/setup/defaults       The default values for a new pair (used by "Reset to defaults").
GET    /api/pairs/<id>           One folder pair with its full setup.
POST   /api/pairs                Create a folder pair (not while a sync runs).
PUT    /api/pairs/<id>           Change name and setup of a pair (not while a sync runs).
PUT    /api/pairs/<id>/enabled   Switch a pair on or off. Body: {"enabled": true|false} (not while a sync runs).
DELETE /api/pairs/<id>           Delete a pair (not while a sync runs).
POST   /api/sync                 Start a run for all active pairs. Body: {"mode", "resync", "dry_run"}.
POST   /api/stop                 Ask the running sync to stop.
GET    /api/log                  Log lines. Query: ?after=<last id the client has seen>.

``<id>`` is the id of a folder pair as given in ``/api/status`` or when it was created.
"""

from dataclasses import dataclass
from typing import Callable, Optional

from ..errors import PairNotFoundError, SetupError, SyncBusyError, SyncConfigError
from ..command.log_buffer import LogBuffer
from ..models import SyncMode
from ..pairs import FolderPairStore
from ..setup import PairSetup
from ..sync_manager import SyncManager


@dataclass(frozen=True)
class ApiRequest:
    """Everything a handler may need to know about one request."""

    path_params: dict   # the <id> parts of the URL, e.g. {"pair_id": "a1b2c3d4"}
    query: dict
    body: dict


@dataclass(frozen=True)
class ApiResponse:
    """A status code plus a JSON-serialisable payload."""

    status: int
    payload: dict


class ApiRouter:
    """Dispatches API requests to the right handler method."""

    def __init__(
        self,
        pair_store: FolderPairStore,
        sync_manager: SyncManager,
        log_buffer: LogBuffer,
    ) -> None:
        self._pair_store = pair_store
        self._sync_manager = sync_manager
        self._log = log_buffer

        # (HTTP method, path pattern, handler). "{name}" in a pattern matches one URL part.
        self._routes: list = [
            ("GET", "/api/status", self._get_status),
            ("GET", "/api/setup/defaults", self._get_default_setup),
            ("GET", "/api/pairs/{pair_id}", self._get_pair),
            ("POST", "/api/pairs", self._post_pair),
            ("PUT", "/api/pairs/{pair_id}", self._put_pair),
            ("PUT", "/api/pairs/{pair_id}/enabled", self._put_pair_enabled),
            ("DELETE", "/api/pairs/{pair_id}", self._delete_pair),
            ("POST", "/api/sync", self._post_sync),
            ("POST", "/api/stop", self._post_stop),
            ("GET", "/api/log", self._get_log),
        ]

    def handle(self, method: str, path: str, query: dict, body: Optional[dict]) -> ApiResponse:
        """Run the matching handler and turn our exceptions into HTTP statuses."""
        path_exists = False
        for route_method, pattern, handler in self._routes:
            params = _match_path(pattern, path)
            if params is None:
                continue
            path_exists = True
            if route_method == method:
                return self._call(handler, ApiRequest(params, query, body or {}))

        if path_exists:
            return ApiResponse(405, {"error": "Method not allowed for this endpoint."})
        return ApiResponse(404, {"error": "Unknown API endpoint."})

    @staticmethod
    def _call(handler: Callable, request: ApiRequest) -> ApiResponse:
        try:
            return handler(request)
        except (SetupError, SyncConfigError) as error:
            return ApiResponse(400, {"error": str(error)})
        except PairNotFoundError as error:
            return ApiResponse(404, {"error": str(error)})
        except SyncBusyError as error:
            return ApiResponse(409, {"error": str(error)})

    # ------------------------------------------------------------------
    # Handlers: state
    # ------------------------------------------------------------------

    def _get_status(self, request: ApiRequest) -> ApiResponse:
        return ApiResponse(200, self._sync_manager.status())

    def _get_default_setup(self, request: ApiRequest) -> ApiResponse:
        """The defaults live in config.py; the UI asks for them instead of copying them."""
        return ApiResponse(200, PairSetup().to_dict())

    # ------------------------------------------------------------------
    # Handlers: folder pairs
    # ------------------------------------------------------------------

    def _get_pair(self, request: ApiRequest) -> ApiResponse:
        return ApiResponse(200, self._pair_store.get(request.path_params["pair_id"]).to_dict())

    def _post_pair(self, request: ApiRequest) -> ApiResponse:
        self._refuse_while_syncing()
        return ApiResponse(201, self._pair_store.create(request.body).to_dict())

    def _put_pair(self, request: ApiRequest) -> ApiResponse:
        self._refuse_while_syncing()
        saved = self._pair_store.update(request.path_params["pair_id"], request.body)
        return ApiResponse(200, saved.to_dict())

    def _put_pair_enabled(self, request: ApiRequest) -> ApiResponse:
        self._refuse_while_syncing()
        saved = self._pair_store.set_enabled(request.path_params["pair_id"], request.body.get("enabled"))
        return ApiResponse(200, saved.to_dict())

    def _delete_pair(self, request: ApiRequest) -> ApiResponse:
        self._refuse_while_syncing()
        pair_id = request.path_params["pair_id"]
        self._pair_store.delete(pair_id)
        return ApiResponse(200, {"deleted": pair_id})

    def _refuse_while_syncing(self) -> None:
        """Folder pairs are locked during a run, so a run always works on what it started with."""
        if self._sync_manager.is_busy():
            raise SyncBusyError("Folder pairs are locked while a sync is running.")

    # ------------------------------------------------------------------
    # Handlers: running
    # ------------------------------------------------------------------

    def _post_sync(self, request: ApiRequest) -> ApiResponse:
        body = request.body
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

    def _post_stop(self, request: ApiRequest) -> ApiResponse:
        self._sync_manager.stop()
        return ApiResponse(200, self._sync_manager.status())

    def _get_log(self, request: ApiRequest) -> ApiResponse:
        try:
            after = int(request.query.get("after", ["0"])[0])
        except ValueError:
            raise SyncConfigError("'after' must be a whole number.") from None

        entries = self._log.entries_after(after)
        last_id = entries[-1].id if entries else after
        return ApiResponse(200, {
            "entries": [entry.to_dict() for entry in entries],
            "last_id": last_id,
        })


def _match_path(pattern: str, path: str) -> Optional[dict]:
    """
    Compare a URL with a route pattern, part by part.
    ``/api/pairs/{pair_id}`` matches ``/api/pairs/a1b2`` and returns ``{"pair_id": "a1b2"}``.
    Returns None if the URL does not match.
    """
    pattern_parts = pattern.split("/")
    path_parts = path.split("/")
    if len(pattern_parts) != len(path_parts):
        return None

    params = {}
    for expected, actual in zip(pattern_parts, path_parts):
        if expected.startswith("{") and expected.endswith("}"):
            if not actual:
                return None
            params[expected[1:-1]] = actual
        elif expected != actual:
            return None
    return params
