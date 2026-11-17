"""
Fixed configuration of the application.

Everything in this file is decided by the developer, NOT by the user at
runtime. What the user can change in the UI lives elsewhere: the setup of one
folder pair (local folder, exclusions, maximum file size, ...) in ``setup.py``
and the list of folder pairs in ``pairs.py``.

If you want to tweak how rclone is called, the two flag lists below are the
place to do it.
"""

import os
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"

# Everything the app writes (setup, generated filter file) goes here.
DATA_DIR = PROJECT_ROOT / "data"

# --------------------------------------------------------------------------
# Web server
# --------------------------------------------------------------------------

# The server only listens on the loopback interface. Together with the
# checks in security.py this makes sure that only this PC can talk to it.
HOST = "127.0.0.1"
PORT = int(os.environ.get("RCLONE_SYNC_PORT", "8765"))

# --------------------------------------------------------------------------
# rclone
# --------------------------------------------------------------------------

# Name (or full path) of the rclone executable. Can be overridden with the
# environment variable RCLONE_SYNC_BINARY, which the tests use to plug in
# a fake rclone.
RCLONE_BINARY = os.environ.get("RCLONE_SYNC_BINARY", "rclone")

# How long ``rclone listremotes`` may take before the app gives up on it.
REMOTE_LIST_TIMEOUT_SECONDS = 10

# ``rclone bisync --check-access`` only runs if a file with this name exists
# on BOTH sides. It protects against syncing an empty / unmounted folder.
ACCESS_CHECK_FILENAME = "RCLONE_TEST"

# The flag that carries the maximum file size. The value after it is
# replaced with whatever the user configured in the UI.
MAX_SIZE_FLAG = "--max-size"

BISYNC_FLAGS = [
    "--max-size", "50M",
    "--resilient", "--recover",
    "--conflict-resolve", "path2",   # path2 = the remote: the remote wins conflicts
    "--conflict-loser", "num",
    "--check-access",
    "--max-delete", "25",
    "--create-empty-src-dirs",
    "--drive-skip-gdocs",
    "--metadata",
    "--compare", "size,modtime,checksum",
    "--slow-hash-sync-only",
    "-v", "--stats", "5s",
]

DOWNLOAD_FLAGS = [
    "--max-size", "50M",
    "--max-delete", "25",
    "--create-empty-src-dirs",
    "--drive-skip-gdocs",
    "--metadata",
    "-v", "--stats", "5s",
]

# --------------------------------------------------------------------------
# Setup: default values (used until the user saves their own)
# --------------------------------------------------------------------------

# No default remote: which cloud a pair uses is the user's choice, made in the UI
# from the remotes that rclone knows (see command/remotes.py).
DEFAULT_REMOTE = ""
DEFAULT_MAX_SIZE = "50M"
DEFAULT_EXCLUSIONS = (
    "~$*",          # Office lock files
    "*.tmp",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
)

# --------------------------------------------------------------------------
# Folder pairs
# --------------------------------------------------------------------------

# Names are used in the list and tag every log line, so they stay short.
PAIR_NAME_MAX_LENGTH = 40

# Older versions had exactly one folder pair and no names. When their setup
# file is converted, that one pair gets this name.
MIGRATED_PAIR_NAME = "Folder pair 1"

# --------------------------------------------------------------------------
# Log
# --------------------------------------------------------------------------

# How many log lines are kept in memory. Older lines are dropped.
LOG_BUFFER_CAPACITY = 5000
