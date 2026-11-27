"""!
@file window.py
@brief The native window around the web UI.

pywebview shows the page in a GTK / WebKit window, so the app looks like any
other desktop program: its own window, taskbar entry and icon.

pywebview is imported lazily. Without it the rest of the project (including the
browser mode in ``run.py``) keeps working, and the user gets a clear message.
"""

from pathlib import Path
from typing import Callable, Optional

from .identity import APP_ID, APP_NAME
from .tray import TrayIcon, TrayUnavailable

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
    @brief Opens the UI in a native window and blocks until the app is quit.

    With a tray icon, closing the window only hides it and "Quit" in the tray
    ends the app. Without one, closing the window ends the app.
    """

    def __init__(self, url: str, icon_path: Path, is_sync_running: Callable[[], bool],
                 tray: Optional[TrayIcon] = None) -> None:
        """!
        @brief Remember what to show; no window is created yet.
        @param url The address of the web UI.
        @param icon_path The PNG used as the window icon.
        @param is_sync_running Returns True while a sync runs, so quitting can be confirmed.
        @param tray The tray icon, or None for a plain window.
        """
        self._url = url
        self._icon_path = icon_path
        self._is_sync_running = is_sync_running
        self._tray = tray
        self._window = None
        self._hide_on_close = False
        self._quit_requested = False
        self._minimized = False

    def run(self) -> None:
        """!
        @brief Show the window and block until the app is quit.
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
        self._start_tray()
        try:
            webview.start(icon=str(self._icon_path))
        finally:
            if self._tray is not None:
                self._tray.stop()

    def open(self) -> None:
        """!
        @brief Bring the dashboard to the front, whether hidden, minimized or covered.

        With GTK (Linux) the native window's present() does all of that and keeps a
        maximized window maximized. It must run on the GTK main thread, which is
        where the tray menu calls us. Elsewhere pywebview's own methods are used;
        restore() only for a minimized window, as it can also un-maximize one.

        Never call hide() right before show() here: pywebview's GTK code runs
        the hide later than the show, so the window would stay hidden.
        """
        present = getattr(getattr(self._window, "native", None), "present", None)
        if present is not None:
            present()
            return
        self._window.show()
        if self._minimized:
            self._window.restore()

    def quit(self) -> None:
        """!
        @brief End the app, asking first if a sync is running.
        """
        self._quit_requested = True
        if self._is_sync_running():
            self.open()  # the question must not come from an invisible window
        self._window.destroy()

    def _start_tray(self) -> None:
        """!
        @brief Start the tray icon, if there is one, and only then hide on close.
        """
        if self._tray is None:
            return
        try:
            self._tray.start(on_open=self.open, on_quit=self.quit)
        except TrayUnavailable as problem:
            print(problem)
            print("Continuing without a tray icon: closing the window quits the app.")
            return
        self._hide_on_close = True
        self._window.events.minimized += self._on_minimized
        self._window.events.restored += self._on_restored

    def _on_minimized(self) -> None:
        """!
        @brief Remember that the window is minimized.
        """
        self._minimized = True

    def _on_restored(self) -> None:
        """!
        @brief Remember that the window is no longer minimized.
        """
        self._minimized = False

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
        @brief Decide what closing the window means.
        @return False to keep the app running, True to let the window close (which quits).
        """
        if self._hide_on_close and not self._quit_requested:
            self._window.hide()
            return False
        allowed = self._confirm_quit()
        if not allowed:
            self._quit_requested = False
        return allowed

    def _confirm_quit(self) -> bool:
        """!
        @brief Ask before quitting while a sync runs.
        @return True if the app may quit.

        If the dialog itself fails quitting is allowed, so the user is never
        trapped in the window.
        """
        if not self._is_sync_running():
            return True
        try:
            return self._window.create_confirmation_dialog(
                "Sync is running",
                "A sync is still running. Quitting will stop it.\n\nQuit anyway?",
            )
        except Exception:
            return True
