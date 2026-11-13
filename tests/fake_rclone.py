#!/usr/bin/env python3
"""
A stand-in for rclone, used only by the tests.

Behaviour is chosen with the environment variable FAKE_RCLONE_MODE:
    ok           print a few log lines, exit 0   (default)
    fail         print an error, exit 1
    need_resync  print the bisync "must run --resync" error, exit 2
    slow         keep printing for ~30 s (so tests can press STOP)

The first thing it prints is its own argument list, so tests can check
exactly which command the app built.
"""

import os
import sys
import time

mode = os.environ.get("FAKE_RCLONE_MODE", "ok")
print("ARGS: " + " ".join(sys.argv[1:]), flush=True)

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
