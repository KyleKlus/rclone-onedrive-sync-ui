"""
OneDrive Sync backend.

A small, dependency-free (standard library only) Python backend that wraps
the ``rclone`` command line tool and exposes it to the web frontend through
a local-only HTTP API.

Module overview
---------------
config              Fixed app settings: paths, port, the rclone flag lists.
errors              Custom exception types shared by all modules.
models              Small data types (enums, log entry).
setup               The folder-sync setup (local folder, remote, exclusions ...): validation and saving.
sync_manager        The state machine: idle -> running -> done / failed.
app                 Wires everything together.

command/rclone      Builds the exact rclone command lines and runs them.
command/log_buffer  Thread-safe in-memory log that the UI reads from.

server/security     The "localhost only" guard.
server/api          Maps API URLs (e.g. /api/status) to actions.
server/http_server  HTTP plumbing: security checks, JSON, static files.
"""
