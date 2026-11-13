"""
Starts an rclone process and streams its output.
"""

import subprocess
import threading
from typing import Callable, Optional

from .errors import RcloneNotFoundError

# After asking rclone to stop politely, wait this long before killing it.
_KILL_GRACE_SECONDS = 10


class RcloneRunner:
    """
    Runs one rclone command at a time and can cancel it from another thread.

    stderr is merged into stdout because rclone writes its ``-v`` log to
    stderr, and we want one ordered stream of lines.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: Optional[subprocess.Popen] = None
        self._cancel_requested = False

    def reset(self) -> None:
        """Forget an earlier cancel request. Call before starting a new job."""
        with self._lock:
            self._cancel_requested = False

    def run(self, command: list, on_line: Callable[[str], None]) -> int:
        """
        Run ``command``, call ``on_line`` for every output line, and return
        the exit code. Blocks until rclone has finished.
        """
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,  # line buffered
            )
        except FileNotFoundError as error:
            raise RcloneNotFoundError(
                f"Could not start '{command[0]}'. Is rclone installed and on your PATH?"
            ) from error

        with self._lock:
            self._process = process
            cancelled_early = self._cancel_requested
        if cancelled_early:
            # Stop was pressed in the instant before the process existed.
            process.terminate()

        try:
            for line in process.stdout:
                on_line(line.rstrip("\r\n"))
            return process.wait()
        finally:
            process.stdout.close()
            with self._lock:
                self._process = None

    def terminate(self) -> None:
        """
        Ask the running rclone to stop. If it has not exited after a grace
        period it is killed.
        """
        with self._lock:
            self._cancel_requested = True
            process = self._process
        if process is None or process.poll() is not None:
            return
        process.terminate()
        timer = threading.Timer(_KILL_GRACE_SECONDS, self._kill_if_alive, args=(process,))
        timer.daemon = True
        timer.start()

    @staticmethod
    def _kill_if_alive(process: subprocess.Popen) -> None:
        if process.poll() is None:
            process.kill()
