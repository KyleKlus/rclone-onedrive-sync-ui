"""
How the desktop environment recognises this app.

The dock (taskbar) decides which icon to show by matching a window's
"application id" against the name of an installed ``.desktop`` file. So these
three values must stay in sync:

    APP_ID                      == window application id (set in window.py)
    <APP_ID>.desktop            == the file written by launcher_entry.py
    StartupWMClass=<APP_ID>     == inside that file (for X11 sessions)
"""

from pathlib import Path

APP_ID = "onedrive-sync"
APP_NAME = "OneDrive Sync"
APP_COMMENT = "Sync a folder with OneDrive using rclone"

_FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

# The same artwork that the web page uses as its favicon.
ICON_PNG = _FRONTEND / "img" / "icons" / "icon-512.png"
ICON_SVG = _FRONTEND / "favicon.svg"
