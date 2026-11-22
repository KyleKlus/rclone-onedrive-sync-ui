#!/usr/bin/env python3
"""!
@file demo_rclone.py
@brief A pretend rclone that prints believable output. Used only to take screenshots.

It knows three remotes (onedrive, icloud, gdrive). Copy runs take a few seconds and
print one "Copied (new)" line per file, so the live log looks like a real sync.
The environment variable DEMO_EXPIRED ("icloud") makes every command for that remote
fail with the iCloud "Invalid Session Token" error, like an expired login.
"""

import datetime
import os
import sys
import time

REMOTES = (("onedrive", "onedrive"), ("icloud", "iclouddrive"), ("gdrive", "drive"))

FILES = {
    "icloud": [
        "2026/Summer/IMG_0412.jpg", "2026/Summer/IMG_0413.jpg", "2026/Summer/IMG_0419.heic",
        "2026/Summer/IMG_0421.jpg", "2026/Autumn/IMG_0520.jpg", "2026/Autumn/IMG_0522.jpg",
        "2026/Autumn/IMG_0531.heic", "2026/Autumn/IMG_0544.jpg",
    ],
    "onedrive": [
        "Taxes/2025/summary.pdf", "Taxes/2025/receipts.xlsx", "Letters/landlord.docx",
        "Letters/insurance.docx", "Notes/ideas.md", "Notes/books.md", "CV/cv-2026.pdf",
        "Manuals/dishwasher.pdf",
    ],
    "gdrive": [
        "Projects/website/index.html", "Projects/website/style.css", "Projects/website/app.js",
        "Projects/report/draft-3.docx", "Projects/report/figures/plot-1.png",
        "Projects/report/figures/plot-2.png", "Projects/budget.xlsx", "Projects/todo.txt",
    ],
}


def stamp() -> str:
    """!
    @brief The current time in rclone's log format.
    @return For example "2026/11/22 10:15:03".
    """
    return datetime.datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def find_remote(arguments: list) -> str:
    """!
    @brief Find which remote a command is about.
    @param arguments The command line arguments after the program name.
    @return The remote name, or "" if no argument names a known remote.
    """
    names = {name for name, _ in REMOTES}
    for argument in arguments:
        name, separator, _ = argument.partition(":")
        if separator and name in names:
            return name
    return ""


def main() -> int:
    """!
    @brief Act like rclone for the few commands the app uses.
    @return The exit code.
    """
    arguments = sys.argv[1:]
    command = arguments[0] if arguments else ""

    if command == "listremotes":
        for name, kind in REMOTES:
            print(f"{name + ':':<12} {kind}", flush=True)
        return 0

    remote = find_remote(arguments[1:])
    if remote and remote in os.environ.get("DEMO_EXPIRED", "").split(","):
        print(
            f'{stamp()} ERROR : Failed to create file system for "{remote}:": HTTP error 400 '
            '(400 Bad Request) returned body: "{\\"success\\":false,\\"error\\":\\"Invalid Session Token\\"}"',
            file=sys.stderr, flush=True,
        )
        return 1

    if command in ("lsd", "copyto"):
        return 0

    files = FILES.get(remote, [])
    print(f"{stamp()} INFO  : Starting {command} for {remote}:", flush=True)
    for name in files:
        time.sleep(0.5)
        print(f"{stamp()} INFO  : {name}: Copied (new)", flush=True)
    print(f"{stamp()} INFO  : Transferred: {len(files)} / {len(files)}, 100%", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
