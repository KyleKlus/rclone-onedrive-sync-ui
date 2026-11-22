"""!
@file log_buffer.py
@brief A thread-safe, in-memory log.

The sync runs in a background thread and writes lines into the buffer; the
web server reads them from other threads when the UI asks for new lines.

rclone lines look like "2026/11/13 21:40:00 INFO  : file.txt: Copied (new)".
The date and time part is optional so that bare "ERROR : ..." also matches.
rclone also colours some lines (bisync in particular) with ANSI escape codes
such as ESC[33m ... ESC[0m, which a browser would show as stray "[33m" text.
"""

import re
import threading
from collections import deque
from datetime import datetime
from typing import Optional

from ..models import LogEntry

_LEVEL_PATTERN = re.compile(
    r"^(?:\S+\s+\S+\s+)?(CRITICAL|ERROR|WARNING|NOTICE|INFO|DEBUG)\s*:"
)

_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """!
    @brief Remove terminal colour / cursor codes from a line.
    @param text A raw output line.
    @return The line without ANSI escape sequences.
    """
    return _ANSI_PATTERN.sub("", text)


def detect_level(text: str) -> str:
    """!
    @brief Work out the severity of a raw rclone output line.
    @param text A raw output line.
    @return One of "debug", "info", "notice", "warning" or "error"; "critical"
            maps to "error" and lines without a level (e.g. the "Transferred: ..."
            statistics block) count as "info".
    """
    match = _LEVEL_PATTERN.match(text)
    if match is None:
        return "info"
    level = match.group(1).lower()
    return "error" if level == "critical" else level


class LogBuffer:
    """!
    @brief Keeps the most recent log lines.

    Once the capacity is reached the oldest line is dropped. All access is
    guarded by a lock because the sync thread writes while web threads read.
    """

    def __init__(self, capacity: int) -> None:
        """!
        @brief Create an empty buffer.
        @param capacity How many lines to keep at most.
        """
        self._entries: deque = deque(maxlen=capacity)
        self._next_id = 1
        self._lock = threading.Lock()

    def append(self, text: str, level: Optional[str] = None, source: str = "") -> LogEntry:
        """!
        @brief Add a line to the log.
        @param text The line; ANSI codes and the trailing newline are removed.
        @param level Severity. If omitted it is detected from the text. Messages
                     written by this app itself use the level "app".
        @param source Name of the folder pair the line belongs to.
        @return The stored entry, including its new id.

        Pairs can sync at the same time, so their lines are mixed; the source
        tag keeps them apart.
        """
        text = strip_ansi(text)
        with self._lock:
            entry = LogEntry(
                id=self._next_id,
                timestamp=datetime.now().strftime("%H:%M:%S"),
                level=level or detect_level(text),
                text=text.rstrip("\r\n"),
                source=source,
            )
            self._next_id += 1
            self._entries.append(entry)
            return entry

    def entries_after(self, last_id: int) -> list:
        """!
        @brief Return the lines that are newer than a given id.
        @param last_id The id of the newest line the caller already has.
        @return All stored entries whose id is greater than ``last_id``.
        """
        with self._lock:
            return [entry for entry in self._entries if entry.id > last_id]
