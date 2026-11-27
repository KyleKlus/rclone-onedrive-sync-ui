"""!
@file tray.py
@brief The system tray icon (pystray): Open dashboard, Start / Stop sync, Quit.

pystray runs "detached" here: it does not start an event loop of its own on
Linux, but uses the GTK loop that the pywebview window runs.

pystray is imported lazily. Without it (or without a usable tray) the app still
works, and closing the window quits it as before.
"""

import os
import sys
import threading
from pathlib import Path
from typing import Callable

from .identity import APP_ID, APP_NAME
from .status_icons import StatusIcons
from .sync_toggle import SyncToggle

REFRESH_SECONDS = 1.0

INSTALL_HELP = """\
The tray icon needs pystray, Pillow and the AppIndicator system library.

  Debian / Ubuntu:  sudo apt install python3-pystray python3-pil gir1.2-ayatanaappindicator3-0.1

On GNOME the "AppIndicator" shell extension must also be switched on (Ubuntu
includes it; elsewhere install gnome-shell-extension-appindicator)."""


class TrayUnavailable(Exception):
    """!
    @brief Raised when no visible tray icon can be created on this system.
    """


class TrayIcon:
    """!
    @brief Shows the tray icon and keeps its colour and menu in step with the sync state.
    """

    def __init__(self, icon_path: Path, sync_toggle: SyncToggle,
                 report_problem: Callable[[str], None]) -> None:
        """!
        @brief Remember what to show; no icon is created yet.
        @param icon_path The app icon PNG that the coloured tray icons are made from.
        @param sync_toggle The logic of the Start / Stop entry.
        @param report_problem Called with the reason when a sync cannot be started.
        """
        self._icon_path = icon_path
        self._toggle = sync_toggle
        self._report_problem = report_problem
        self._icon = None
        self._images = None
        self._shown_image = None
        self._shown_menu = None
        self._on_open: Callable[[], None] = lambda: None
        self._stopped = threading.Event()

    def start(self, on_open: Callable[[], None], on_quit: Callable[[], None]) -> None:
        """!
        @brief Create the icon. Call this before the window's event loop starts.
        @param on_open Called for "Open dashboard".
        @param on_quit Called for "Quit".
        @throws TrayUnavailable If the icon cannot be shown.
        """
        pystray, self._images = self._load_libraries()
        self._shown_image = self._images.for_state(self._toggle.state())
        self._shown_menu = None
        self._on_open = on_open

        # pystray inspects the parameters of these callables, hence the lambdas.
        menu = pystray.Menu(
            pystray.MenuItem("Open dashboard", lambda _icon, _item: on_open(), default=True),
            pystray.MenuItem(
                lambda _item: self._toggle.label(),
                lambda _icon, _item: self._toggle_sync(),
                enabled=lambda _item: self._toggle.is_enabled(),
            ),
            pystray.MenuItem("Quit", lambda _icon, _item: on_quit()),
        )
        try:
            self._icon = pystray.Icon(APP_ID, self._shown_image, APP_NAME, menu)
            self._icon.run_detached()
        except Exception as error:
            raise TrayUnavailable(f"The tray icon could not be created: {error}") from error

        self._stopped.clear()
        threading.Thread(target=self._keep_current, name="tray-refresh", daemon=True).start()

    def stop(self) -> None:
        """!
        @brief Remove the icon; does nothing if it was never started.
        """
        self._stopped.set()
        if self._icon is None:
            return
        icon, self._icon = self._icon, None
        try:
            icon.visible = False
            icon.stop()
        except Exception as error:
            # The app is quitting: a failing clean-up must not stop that.
            print(f"Warning: could not remove the tray icon ({error}).")

    def _toggle_sync(self) -> None:
        """!
        @brief Handle a click on Start / Stop sync.

        A refused start would otherwise be invisible while the window is hidden,
        so it is reported, shown as a notification and the dashboard is opened.
        """
        problem = self._toggle.toggle()
        if not problem:
            return
        self._report_problem(problem)
        try:
            self._icon.notify(problem, APP_NAME)
        except Exception as error:
            print(f"Warning: could not show a notification ({error}).")
        self._on_open()

    def _keep_current(self) -> None:
        """!
        @brief Refresh the icon again and again until stop() (runs in its own thread).

        A sync can start or end without a click on the tray, e.g. from the
        dashboard, so the state has to be watched.
        """
        while not self._stopped.wait(REFRESH_SECONDS):
            self.refresh()

    def refresh(self) -> None:
        """!
        @brief Bring colour and menu up to date with the sync state.

        Only changes are sent to the tray, so an open menu is not rebuilt every
        second and the icon does not flicker.
        """
        icon = self._icon
        if icon is None:
            return
        image = self._images.for_state(self._toggle.state())
        if image is not self._shown_image:
            icon.icon = image
            self._shown_image = image
        menu = (self._toggle.label(), self._toggle.is_enabled())
        if menu != self._shown_menu:
            icon.update_menu()
            self._shown_menu = menu

    def _load_libraries(self):
        """!
        @brief Import pystray and prepare the icon pictures.
        @return A tuple (the ``pystray`` module, the StatusIcons).
        @throws TrayUnavailable If the platform is unsupported or something is missing.

        On Linux only the AppIndicator backend is accepted: pystray's fallbacks
        show no icon on GNOME or no menu, and a window hidden behind an
        invisible icon could not be reached any more.
        """
        if sys.platform == "darwin":
            raise TrayUnavailable("The tray icon is not supported on macOS yet.")
        on_linux = sys.platform.startswith("linux")
        if on_linux:
            os.environ["PYSTRAY_BACKEND"] = "appindicator"
        try:
            import pystray

            images = StatusIcons(self._icon_path)
        except Exception as error:
            # Not only ImportError: a missing system library raises ValueError.
            raise TrayUnavailable(f"{INSTALL_HELP}\n\n({error})") from error
        if on_linux and not self._has_tray_host():
            raise TrayUnavailable(f"This desktop shows no tray icons.\n\n{INSTALL_HELP}")
        return pystray, images

    @staticmethod
    def _has_tray_host() -> bool:
        """!
        @brief Ask the Linux session bus whether something displays tray icons.
        @return True if a StatusNotifierWatcher is running, False if not or if asking fails.
        """
        try:
            from gi.repository import Gio, GLib

            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            reply = bus.call_sync(
                "org.freedesktop.DBus", "/org/freedesktop/DBus",
                "org.freedesktop.DBus", "NameHasOwner",
                GLib.Variant("(s)", ("org.kde.StatusNotifierWatcher",)),
                GLib.VariantType("(b)"), Gio.DBusCallFlags.NONE, -1, None,
            )
            return reply.unpack()[0]
        except Exception:
            return False
