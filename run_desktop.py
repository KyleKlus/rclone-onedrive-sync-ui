#!/usr/bin/env python3
"""
Start Rclone Sync as a desktop app: one command, one native window.

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
    parser = argparse.ArgumentParser(description="Rclone Sync (desktop window)")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--install-launcher", action="store_true",
                       help="add Rclone Sync to the app menu (gives the dock its icon)")
    group.add_argument("--uninstall-launcher", action="store_true",
                       help="remove the app menu entry again")
    return parser.parse_args()


def manage_launcher(arguments: argparse.Namespace) -> int:
    entry = LauncherEntry(script_path=config.PROJECT_ROOT / "run_desktop.py")
    if arguments.install_launcher:
        print(f"Installed: {entry.install()}")
        print("Start 'Rclone Sync' from your app menu; its window will show the icon in the dock.")
    else:
        entry.uninstall()
        print("Removed the app menu entry.")
    return 0


def run_app() -> int:
    lock = InstanceLock(config.DATA_DIR / "app.lock")
    if not lock.acquire():
        print("Rclone Sync is already running (look for its window or dock icon).")
        return 1

    try:
        # Port 0 = the OS picks a free port, so the window can never clash
        # with another program. The server still only listens on 127.0.0.1.
        app = Application(port=0)
        threading.Thread(target=app.run, name="web-server", daemon=True).start()

        window = DesktopWindow(
            url=f"http://{config.HOST}:{app.port}",
            icon_path=ICON_PNG,
            is_sync_running=app.sync_manager.is_busy,
        )
        try:
            window.run()  # blocks until the window is closed
        except DesktopUnavailable as problem:
            print(problem)
            return 1
        finally:
            app.shutdown()
        return 0
    finally:
        lock.release()


def main() -> int:
    arguments = parse_arguments()
    if arguments.install_launcher or arguments.uninstall_launcher:
        return manage_launcher(arguments)
    return run_app()


if __name__ == "__main__":
    sys.exit(main())
