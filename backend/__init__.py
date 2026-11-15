"""
OneDrive Sync backend.

A small, dependency-free (standard library only) Python backend that wraps
the ``rclone`` command line tool and exposes it to the web frontend through
a local-only HTTP API.

Module overview
---------------
config            Fixed settings: paths, port, the rclone flag lists.
errors            Custom exception types shared by all modules.
models            Small data types (enums, log entry).
settings          The user-editable settings: validation and saving / loading.
log_buffer        Thread-safe in-memory log that the UI reads from.
rclone            Builds the exact rclone command lines and runs them.
sync_manager      The state machine: idle -> running -> done / failed.
security          The "localhost only" guard.
api               Maps API URLs (e.g. /api/status) to actions.
http_server       HTTP plumbing: security checks, JSON, static files.
app               Wires everything together.
"""
