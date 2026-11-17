"""
The composition root: creates all objects and connects them.

This is the only place that knows about every module. Everything else
receives its collaborators through its constructor, so each part can be
changed or replaced (e.g. by a fake in tests) without touching the others.
"""

from pathlib import Path

from . import config
from .server.api import ApiRouter
from .server.http_server import WebServer
from .command.log_buffer import LogBuffer
from .command.rclone import FilterFiles, RcloneCommandBuilder, RcloneRunner
from .command.remotes import RemoteCatalog
from .pairs import FolderPairStore
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
        pair_store = FolderPairStore(
            data_dir / "pairs.json",
            # Older versions saved ONE setup in these files; it becomes the first folder pair.
            legacy_paths=[data_dir / "setup.json", data_dir / "settings.json"],
        )

        command_builder = RcloneCommandBuilder(rclone_binary)

        self.sync_manager = SyncManager(
            pair_store=pair_store,
            log_buffer=log_buffer,
            command_builder=command_builder,
            filter_files=FilterFiles(data_dir / "filters"),
            runner_factory=RcloneRunner,   # every folder pair's job gets its own runner
            rclone_binary=rclone_binary,
        )
        router = ApiRouter(pair_store, self.sync_manager, log_buffer, RemoteCatalog(command_builder))
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
