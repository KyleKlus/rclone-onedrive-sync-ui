#!/usr/bin/env python3
"""!
@file run.py
@brief Start Rclone Sync in browser mode.

    python run.py            start the server, then open the printed address
    python run.py --open     also open it in your default browser
    python run.py --port 9000
"""

import argparse
import sys
import webbrowser

from backend import config
from backend.app import Application


def parse_arguments() -> argparse.Namespace:
    """!
    @brief Read the command line.
    @return The parsed arguments (``port``, ``open``).
    """
    parser = argparse.ArgumentParser(description="Rclone Sync (rclone front end)")
    parser.add_argument("--port", type=int, default=config.PORT, help="port to listen on")
    parser.add_argument("--open", action="store_true", help="open the UI in the default browser")
    return parser.parse_args()


def main() -> int:
    """!
    @brief Start the server and run it until Ctrl+C.
    @return The process exit code (1 if the server could not start, else 0).
    """
    arguments = parse_arguments()

    try:
        app = Application(port=arguments.port)
    except OSError as error:
        print(f"Could not start the server on port {arguments.port}: {error}")
        return 1

    url = f"http://{config.HOST}:{app.port}"
    print(f"Rclone Sync is running at {url}")
    print("Only this computer can reach it. Press Ctrl+C to quit.")
    if arguments.open:
        webbrowser.open(url)

    try:
        app.run()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
