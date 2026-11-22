"""!
@file config.py
@brief Fixed configuration of the application.

Everything in this file is decided by the developer, NOT by the user at
runtime. What the user can change in the UI lives elsewhere: the setup of one
folder pair (local folder, exclusions, maximum file size, ...) in setup.py
and the list of folder pairs in pairs.py.

If you want to tweak how rclone is called, the two flag lists
(BISYNC_FLAGS and DOWNLOAD_FLAGS) are the place to do it.

Paths:
PROJECT_ROOT: Root folder of the project.
FRONTEND_DIR: Folder with the HTML, CSS and JS files that are served.
DATA_DIR: Everything the app writes (setup, generated filter file) goes here.

Web server:
HOST: The server only listens on the loopback interface. Together with the
checks in security.py this makes sure that only this PC can talk to it.
PORT: Port of the web server; can be set with the environment variable RCLONE_SYNC_PORT.

rclone:
RCLONE_BINARY: Name (or full path) of the rclone executable. Can be overridden
with the environment variable RCLONE_SYNC_BINARY, which the tests use to plug in a fake rclone.
REMOTE_LIST_TIMEOUT_SECONDS: How long "rclone listremotes" may take before the app gives up on it.
ACCESS_CHECK_FILENAME: "rclone bisync --check-access" only runs if a file with
this name exists on BOTH sides. It protects against syncing an empty / unmounted folder.
MAX_SIZE_FLAG: The flag that carries the maximum file size. The value after it
is replaced with whatever the user configured in the UI.
BISYNC_FLAGS: Flags for two-way sync. "--conflict-resolve path2" means path2 is
the remote: the remote wins conflicts.
DOWNLOAD_FLAGS: Flags for one-way sync (this PC is made to match the remote).

Setup defaults (used until the user saves their own):
DEFAULT_REMOTE: Empty on purpose. Which cloud a pair uses is the user's choice,
made in the UI from the remotes that rclone knows (see command/remotes.py).
DEFAULT_MAX_SIZE: Default maximum file size.
DEFAULT_EXCLUSIONS: Default exclusion patterns (the first one is for Office lock files).

Folder pairs:
PAIR_NAME_MAX_LENGTH: Names are used in the list and tag every log line, so they stay short.
MIGRATED_PAIR_NAME: Older versions had exactly one folder pair and no names.
When their setup file is converted, that one pair gets this name.

Expired logins:
REMOTE_CHECK_INTERVAL_SECONDS: Seconds between two automatic checks of the remotes that folder pairs use.
REMOTE_CHECK_TIMEOUT_SECONDS: Longest time one remote may take to answer a check.
EXPIRED_LOGIN_PATTERNS: Lower-case pieces of rclone output that mean "sign in
again". A line that contains any of them marks its remote as expired.

Log:
LOG_BUFFER_CAPACITY: How many log lines are kept in memory. Older lines are dropped.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
DATA_DIR = PROJECT_ROOT / "data"

HOST = "127.0.0.1"
PORT = int(os.environ.get("RCLONE_SYNC_PORT", "8765"))

RCLONE_BINARY = os.environ.get("RCLONE_SYNC_BINARY", "rclone")
REMOTE_LIST_TIMEOUT_SECONDS = 10
ACCESS_CHECK_FILENAME = "RCLONE_TEST"
MAX_SIZE_FLAG = "--max-size"

BISYNC_FLAGS = [
    "--max-size", "50M",
    "--resilient", "--recover",
    "--conflict-resolve", "path2",
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

DEFAULT_REMOTE = ""
DEFAULT_MAX_SIZE = "50M"
DEFAULT_EXCLUSIONS = (
    "~$*",
    "*.tmp",
    ".DS_Store",
    "Thumbs.db",
    "desktop.ini",
)

PAIR_NAME_MAX_LENGTH = 40
MIGRATED_PAIR_NAME = "Folder pair 1"

REMOTE_CHECK_INTERVAL_SECONDS = 30 * 60
REMOTE_CHECK_TIMEOUT_SECONDS = 45
EXPIRED_LOGIN_PATTERNS = (
    "invalid session token",
    "missing x-apple-webauth-token",
    "maybe it has expired",
    "config reconnect",
    "couldn't fetch token",
    "oauth2: cannot fetch token",
    "invalid_grant",
    "invalid refresh token",
    "refresh token has expired",
    "token refresh failed",
)

LOG_BUFFER_CAPACITY = 5000
