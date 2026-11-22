#!/usr/bin/env python3
"""!
@file run_desktop.py
@brief Start Rclone Sync as a desktop app: one command, one native window.

    python run_desktop.py                     open the app window
    python run_desktop.py --install-launcher  add it to the app menu / dock (once)
    python run_desktop.py --uninstall-launcher

Closing the window quits the app. For the browser version use run.py.
"""

import argparse
import sys
import threading

from backend import config
from backend.app import Application
from desktop.identity import ICON_PNG
from desktop.launcher_entry import LauncherEntry
from desktop.single_instance import InstanceLock
from desktop.window import DesktopUnavailable, DesktopWindow


def parse_arguments() -> argparse.Namespace:
    """!
    @brief Read the command line.
    @return The parsed arguments (``install_launcher``, ``uninstall_launcher``).
    """
    parser = argparse.ArgumentParser(description="Rclone Sync (desktop window)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install-launcher", action="store_true",
                       help="add Rclone Sync to the app menu (gives the dock its icon)")
    group.add_argument("--uninstall-launcher", action="store_true",
                       help="remove the app menu entry again")
    return parser.parse_args()


def manage_launcher(arguments: argparse.Namespace) -> int:
    """!
    @brief Install or remove the app-menu entry.
    @param arguments The parsed command line.
    @return The process exit code (0).
    """
    entry = LauncherEntry(script_path=config.PROJECT_ROOT / "run_desktop.py")
    if arguments.install_launcher:
        print(f"Installed: {entry.install()}")
        print("Start 'Rclone Sync' from your app menu; its window will show the icon in the dock.")
    else:
        entry.uninstall()
        print("Removed the app menu entry.")
    return 0


def run_app() -> int:
    """!
    @brief Start the server and show the native window until it is closed.
    @return The process exit code (1 if already running or no window is possible, else 0).

    The server uses port 0, so the OS picks a free port and the window can never
    clash with another program. It still only listens on 127.0.0.1.
    """
    lock = InstanceLock(config.DATA_DIR / "app.lock")
    if not lock.acquire():
        print("Rclone Sync is already running (look for its window or dock icon).")
        return 1

    try:
        app = Application(port=0)
        threading.Thread(target=app.run, name="web-server", daemon=True).start()

        window = DesktopWindow(
            url=f"http://{config.HOST}:{app.port}",
            icon_path=ICON_PNG,
            is_sync_running=app.sync_manager.is_busy,
        )
        try:
            window.run()
        except DesktopUnavailable as problem:
            print(problem)
            return 1
        finally:
            app.shutdown()
        return 0
    finally:
        lock.release()


def main() -> int:
    """!
    @brief Dispatch to the launcher management or to the app.
    @return The process exit code.
    """
    arguments = parse_arguments()
    if arguments.install_launcher or arguments.uninstall_launcher:
        return manage_launcher(arguments)
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
