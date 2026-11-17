#!/usr/bin/env python3
"""
A stand-in for rclone, used only by the tests.

Behaviour is chosen with the environment variable FAKE_RCLONE_MODE:
    ok           print a few log lines, exit 0   (default)
    fail         print an error, exit 1
    need_resync  print the bisync "must run --resync" error, exit 2
    slow         keep printing for ~30 s (so tests can press STOP)

``listremotes --long`` is answered before any mode applies, like the real thing:
one "name:  type" line per remote. The remotes come from FAKE_RCLONE_REMOTES
("name:type,name:type"); FAKE_RCLONE_REMOTES_FAIL=1 makes the listing fail.

Independent of the mode, a command fails if any argument contains FAIL_ME.
Tests use that to make ONE folder pair fail (by naming its folder FAIL_ME)
while the other pairs of the same run succeed.

The first thing it prints is its own argument list, so tests can check
exactly which command the app built.
"""

import os
import sys
import time

mode = os.environ.get("FAKE_RCLONE_MODE", "ok")

# `listremotes` prints only the remotes (no ARGS line: the app parses this output).
if len(sys.argv) > 1 and sys.argv[1] == "listremotes":
    if os.environ.get("FAKE_RCLONE_REMOTES_FAIL"):
        print("CRITICAL: Failed to load config file: permission denied", file=sys.stderr, flush=True)
        sys.exit(1)
    for entry in os.environ.get("FAKE_RCLONE_REMOTES", "onedrive:onedrive,icloud:iclouddrive").split(","):
        if entry:
            name, _, remote_type = entry.partition(":")
            print(f"{name + ':':<12} {remote_type}", flush=True)
    sys.exit(0)

print("ARGS: " + " ".join(sys.argv[1:]), flush=True)

# Like the real rclone, refuse flags a subcommand does not have.
# (--filters-file exists only for bisync; plain sync uses --filter-from.)
if len(sys.argv) > 1 and sys.argv[1] == "sync" and "--filters-file" in sys.argv:
    print("Error: unknown flag: --filters-file", flush=True)
    sys.exit(1)

if any("FAIL_ME" in argument for argument in sys.argv[1:]):
    print("2026/11/13 21:40:00 ERROR : this folder pair was told to fail", flush=True)
    sys.exit(1)

if mode == "slow":
    for second in range(150):
        print(f"2026/11/13 21:40:00 INFO  : working... {second}", flush=True)
        time.sleep(0.2)
    sys.exit(0)

if mode == "fail":
    print("2026/11/13 21:40:00 ERROR : something went wrong", flush=True)
    sys.exit(1)

if mode == "need_resync":
    print("2026/11/13 21:40:00 ERROR : Bisync critical error: cannot find prior listings", flush=True)
    print("2026/11/13 21:40:00 NOTICE: Bisync aborted. Must run --resync to recover.", flush=True)
    sys.exit(2)

print("2026/11/13 21:40:00 INFO  : file.txt: Copied (new)", flush=True)
print("Transferred:   1 / 1, 100%", flush=True)
sys.exit(0)
