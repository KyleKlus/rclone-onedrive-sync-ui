"""!
@file window.py
@brief The native window around the web UI.

pywebview shows the page in a GTK / WebKit window, so the app looks like any
other desktop program: its own window, taskbar entry and icon.

pywebview is imported lazily. Without it the rest of the project (including the
browser mode in ``run.py``) keeps working, and the user gets a clear message.
"""

from pathlib import Path
from typing import Callable

from .identity import APP_ID, APP_NAME

WINDOW_SIZE = (1280, 900)
WINDOW_MIN_SIZE = (720, 600)

INSTALL_HELP = """\
The desktop window needs pywebview and the WebKitGTK system library.

  Debian / Ubuntu:  sudo apt install python3-gi gir1.2-webkit2-4.1 python3-webview
  Fedora:           sudo dnf install python3-gobject webkit2gtk4.1 python3-pywebview
  Arch:             sudo pacman -S python-gobject webkit2gtk-4.1 python-pywebview

(or: pip install -r requirements-desktop.txt  inside a venv created with
 --system-site-packages, so that it can see the system's PyGObject.)

Without it you can still use the browser mode:  python run.py --open"""


class DesktopUnavailable(Exception):
    """!
    @brief Raised when the native window cannot be created on this system.
    """


class DesktopWindow:
    """!
    @brief Opens the UI in a native window and blocks until the window is closed.
    """

    def __init__(self, url: str, icon_path: Path, is_sync_running: Callable[[], bool]) -> None:
        """!
        @brief Remember what to show; no window is created yet.
        @param url The address of the web UI.
        @param icon_path The PNG used as the window icon.
        @param is_sync_running Returns True while a sync runs, so closing can be confirmed.
        """
        self._url = url
        self._icon_path = icon_path
        self._is_sync_running = is_sync_running
        self._window = None

    def run(self) -> None:
        """!
        @brief Show the window and block until it is closed.
        @throws DesktopUnavailable If pywebview is not installed.

        Must be called from the main thread (GUI rule).
        """
        webview = self._import_webview()
        self._announce_identity()

        self._window = webview.create_window(
            APP_NAME,
            self._url,
            width=WINDOW_SIZE[0],
            height=WINDOW_SIZE[1],
            min_size=WINDOW_MIN_SIZE,
        )
        self._window.events.closing += self._on_closing
        webview.start(icon=str(self._icon_path))

    @staticmethod
    def _import_webview():
        """!
        @brief Import pywebview lazily.
        @return The ``webview`` module.
        @throws DesktopUnavailable With install help if pywebview is missing.
        """
        try:
            import webview
        except ImportError as error:
            raise DesktopUnavailable(INSTALL_HELP) from error
        return webview

    @staticmethod
    def _announce_identity() -> None:
        """!
        @brief Tell GTK the application id.

        Must happen BEFORE any window exists. On Wayland it becomes the window's
        app_id, on X11 its WM_CLASS; the dock uses it to find the matching
        .desktop file and with it the icon. Without GTK there is nothing to
        announce (pywebview will report its own problem).
        """
        try:
            from gi.repository import GLib
        except ImportError:
            return
        GLib.set_prgname(APP_ID)
        GLib.set_application_name(APP_NAME)

    def _on_closing(self):
        """!
        @brief Ask before closing while a sync runs.
        @return False to cancel the close, True to allow it.

        If the dialog itself fails the close is allowed, so the user is never
        trapped in the window.
        """
        if not self._is_sync_running():
            return True
        try:
            return self._window.create_confirmation_dialog(
                "Sync is running",
                "A sync is still running. Closing the window will stop it.\n\nClose anyway?",
            )
        except Exception:
            return True
