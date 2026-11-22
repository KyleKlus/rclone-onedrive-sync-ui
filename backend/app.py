"""!
@file app.py
@brief Composition root: creates all objects and connects them.

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
from .remote_health import RemoteHealth, RemoteHealthMonitor
from .sync_manager import SyncManager


class Application:
    """!
    @brief Builds and runs the whole backend.

    Attributes: sync_manager, remote_monitor and web_server are the three
    long-living parts that run() and shutdown() control.
    """

    def __init__(
        self,
        data_dir: Path = config.DATA_DIR,
        frontend_dir: Path = config.FRONTEND_DIR,
        rclone_binary: str = config.RCLONE_BINARY,
        host: str = config.HOST,
        port: int = config.PORT,
    ) -> None:
        """!
        @brief Create all backend objects and wire them together.
        @param data_dir Folder where the app stores its files; created if missing.
        @param frontend_dir Folder with the files the web server serves.
        @param rclone_binary Name or path of the rclone executable.
        @param host Address the web server listens on.
        @param port Port the web server listens on.

        Older versions saved ONE setup in setup.json / settings.json; the pair
        store turns it into the first folder pair. Every folder pair's job gets
        its own runner, which is why the sync manager receives a runner factory.
        """
        data_dir.mkdir(parents=True, exist_ok=True)

        log_buffer = LogBuffer(config.LOG_BUFFER_CAPACITY)
        pair_store = FolderPairStore(
            data_dir / "pairs.json",
            legacy_paths=[data_dir / "setup.json", data_dir / "settings.json"],
        )

        command_builder = RcloneCommandBuilder(rclone_binary)
        remote_health = RemoteHealth()

        self.sync_manager = SyncManager(
            pair_store=pair_store,
            log_buffer=log_buffer,
            command_builder=command_builder,
            filter_files=FilterFiles(data_dir / "filters"),
            runner_factory=RcloneRunner,
            rclone_binary=rclone_binary,
            remote_health=remote_health,
        )
        self.remote_monitor = RemoteHealthMonitor(
            health=remote_health,
            pair_store=pair_store,
            command_builder=command_builder,
            is_busy=self.sync_manager.is_busy,
        )
        router = ApiRouter(
            pair_store, self.sync_manager, log_buffer, RemoteCatalog(command_builder), self.remote_monitor
        )
        self.web_server = WebServer(host, port, frontend_dir, router)

    @property
    def port(self) -> int:
        """!
        @brief Get the port the web server really listens on.
        @return The port number.
        """
        return self.web_server.port

    def run(self) -> None:
        """!
        @brief Start the remote monitor and serve requests until shutdown() is called.
        """
        self.remote_monitor.start()
        self.web_server.serve_forever()

    def shutdown(self) -> None:
        """!
        @brief Stop the remote monitor, a running sync (if any) and the web server.
        """
        self.remote_monitor.stop()
        self.sync_manager.stop()
        self.web_server.shutdown()
