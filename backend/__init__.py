"""
OneDrive Sync backend.

A small, dependency-free (standard library only) Python backend that wraps
the ``rclone`` command line tool and exposes it to the web frontend through
a local-only HTTP API.

Module overview
---------------
config              Fixed app settings: paths, port, the rclone flag lists.
errors              Custom exception types shared by all modules.
models              Small data types (enums, run options, log entry).
setup               The setup of ONE folder pair (local folder, remote, exclusions ...): validation.
pairs               Folder pairs (name, on/off switch, setup) and the list of them, saved as pairs.json.
pair_relations      How two pairs relate: separate, nested (outer skips inner) or clashing (not allowed).
pair_job            One folder pair's sync in a background thread, with its own state.
sync_manager        Runs one job per active pair, all in parallel; owns the overall state.
app                 Wires everything together.

command/rclone      Builds the exact rclone command lines and runs them.
command/log_buffer  Thread-safe in-memory log that the UI reads from.

server/security     The "localhost only" guard.
server/api          Maps API URLs (e.g. /api/status) to actions.
server/http_server  HTTP plumbing: security checks, JSON, static files.
"""
