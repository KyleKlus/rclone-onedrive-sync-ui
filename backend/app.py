"""
The composition root: creates all objects and connects them.

This is the only place that knows about every module. Everything else
receives its collaborators through its constructor, so each part can be
changed or replaced (e.g. by a fake in tests) without touching the others.
"""

from pathlib import Path

from . import config
from .api import ApiRouter
from .http_server import WebServer
from .log_buffer import LogBuffer
from .rclone import FilterFile, RcloneCommandBuilder, RcloneRunner
from .setup import SetupStore
from .sync_manager import SyncManager


class Application:
    """Builds and runs the whole backend."""

    def __init__(
        self,
        data_dir: Path = config.DATA_DIR,
        frontend_dir: Path = config.FRONTEND_DIR,
        rclone_binary: str = config.RCLONE_BINARY,
        host: str = config.HOST,
        port: int = config.PORT,
    ) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)

        log_buffer = LogBuffer(config.LOG_BUFFER_CAPACITY)
        setup_store = SetupStore(data_dir / "setup.json", legacy_path=data_dir / "settings.json")

        self.sync_manager = SyncManager(
            setup_store=setup_store,
            log_buffer=log_buffer,
            runner=RcloneRunner(),
            command_builder=RcloneCommandBuilder(rclone_binary),
            filter_file=FilterFile(data_dir / "filters.txt"),
            rclone_binary=rclone_binary,
        )
        router = ApiRouter(setup_store, self.sync_manager, log_buffer)
        self.web_server = WebServer(host, port, frontend_dir, router)

    @property
    def port(self) -> int:
        return self.web_server.port

    def run(self) -> None:
        """Serve requests until ``shutdown()`` is called."""
        self.web_server.serve_forever()

    def shutdown(self) -> None:
        """Stop a running sync (if any) and the web server."""
        self.sync_manager.stop()
        self.web_server.shutdown()
