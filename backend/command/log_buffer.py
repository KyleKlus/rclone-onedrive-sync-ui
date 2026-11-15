"""
A thread-safe, in-memory log.

The sync runs in a background thread and writes lines into the buffer; the
web server reads them from other threads when the UI asks for new lines.
"""

import re
import threading
from collections import deque
from datetime import datetime
from typing import Optional

from ..models import LogEntry

# rclone lines look like:  "2026/11/13 21:40:00 INFO  : file.txt: Copied (new)"
# The date and time part is optional so that bare "ERROR : ..." also matches.
_LEVEL_PATTERN = re.compile(
    r"^(?:\S+\s+\S+\s+)?(CRITICAL|ERROR|WARNING|NOTICE|INFO|DEBUG)\s*:"
)


# rclone colours some lines (bisync in particular) with ANSI escape codes such
# as ESC[33m ... ESC[0m. A browser would show them as stray "[33m" text.
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Remove terminal colour / cursor codes from a line."""
    return _ANSI_PATTERN.sub("", text)


def detect_level(text: str) -> str:
    """Work out the severity of a raw rclone output line."""
    match = _LEVEL_PATTERN.match(text)
    if match is None:
        return "info"  # e.g. the "Transferred: ..." statistics block
    level = match.group(1).lower()
    return "error" if level == "critical" else level


class LogBuffer:
    """Keeps the most recent ``capacity`` log lines."""

    def __init__(self, capacity: int) -> None:
        self._entries: deque = deque(maxlen=capacity)
        self._next_id = 1
        self._lock = threading.Lock()

    def append(self, text: str, level: Optional[str] = None) -> LogEntry:
        """
        Add a line. If ``level`` is omitted it is detected from the text.
        Messages written by this app itself use the level ``"app"``.
        """
        text = strip_ansi(text)
        with self._lock:
            entry = LogEntry(
                id=self._next_id,
                timestamp=datetime.now().strftime("%H:%M:%S"),
                level=level or detect_level(text),
                text=text.rstrip("\r\n"),
            )
            self._next_id += 1
            self._entries.append(entry)
            return entry

    def entries_after(self, last_id: int) -> list:
        """Return all lines whose id is greater than ``last_id``."""
        with self._lock:
            return [entry for entry in self._entries if entry.id > last_id]
