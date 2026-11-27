"""!
@file test_desktop.py
@brief Tests for the desktop shell.

No real window or tray is needed: pywebview and pystray are replaced by stubs.
"""

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.errors import SyncConfigError
from backend.last_mode import LastModeStore
from backend.models import SyncMode, SyncState
from desktop.identity import APP_ID, ICON_PNG, ICON_SVG
from desktop.launcher_entry import LauncherEntry
from desktop.single_instance import InstanceLock
from desktop.status_icons import RED, YELLOW, StatusIcons
from desktop.sync_toggle import SyncToggle
from desktop.tray import TrayIcon, TrayUnavailable
from desktop.window import DesktopUnavailable, DesktopWindow


class InstanceLockTests(unittest.TestCase):
    """!
    @brief Tests for the single-instance lock.
    """

    def test_second_lock_is_refused_until_first_is_released(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "sub" / "app.lock"
            first, second = InstanceLock(path), InstanceLock(path)
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(second.acquire())
            second.release()


class LauncherEntryTests(unittest.TestCase):
    """!
    @brief Tests for the app-menu entry. A path with a space must be quoted in the Exec line.
    """

    def test_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as folder:
            entry = LauncherEntry(Path("/opt/my app/run_desktop.py"), data_home=Path(folder))
            desktop_file = entry.install()

            self.assertEqual(desktop_file.name, f"{APP_ID}.desktop")
            text = desktop_file.read_text()
            self.assertIn(f"Icon={APP_ID}", text)
            self.assertIn(f"StartupWMClass={APP_ID}", text)
            self.assertIn("'/opt/my app/run_desktop.py'", text)
            self.assertTrue((Path(folder) / "icons/hicolor/512x512/apps" / f"{APP_ID}.png").is_file())
            self.assertTrue((Path(folder) / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg").is_file())

            entry.uninstall()
            self.assertFalse(desktop_file.exists())

    def test_icon_sources_exist(self):
        self.assertTrue(ICON_PNG.is_file())
        self.assertTrue(ICON_SVG.is_file())


class _Event(list):
    """!
    @brief A minimal pywebview event: ``+=`` registers a handler.
    """

    def __iadd__(self, handler):
        """!
        @brief Register a handler.
        @param handler The callable to remember.
        @return This event.
        """
        self.append(handler)
        return self


class _FakeWindow:
    """!
    @brief A stand-in for the pywebview window.
    """

    def __init__(self, answer=True):
        """!
        @brief Create the window stub.
        @param answer What the confirmation dialog answers.
        """
        self.events = types.SimpleNamespace(closing=_Event())
        self.answer = answer
        self.asked = False

    def create_confirmation_dialog(self, title, message):
        """!
        @brief Record that the user was asked and answer.
        @param title The dialog title.
        @param message The dialog text.
        @return The preset answer.
        """
        self.asked = True
        return self.answer


class DesktopWindowTests(unittest.TestCase):
    """!
    @brief Tests for the native window wrapper, with pywebview replaced by a stub.
    """

    def _run_with_fake_webview(self, running, answer=True):
        """!
        @brief Run the window with a stubbed pywebview.
        @param running Whether a sync counts as running.
        @param answer What the confirmation dialog answers.
        @return A tuple (the fake webview module, the fake window).
        """
        window = _FakeWindow(answer)
        fake = types.SimpleNamespace(
            create_window=mock.Mock(return_value=window), start=mock.Mock()
        )
        with mock.patch.dict(sys.modules, {"webview": fake}):
            shell = DesktopWindow("http://127.0.0.1:1", ICON_PNG, lambda: running)
            shell.run()
        return fake, window

    def test_window_is_created_with_url_and_icon(self):
        fake, _ = self._run_with_fake_webview(running=False)
        self.assertEqual(fake.create_window.call_args.args[1], "http://127.0.0.1:1")
        self.assertEqual(fake.start.call_args.kwargs["icon"], str(ICON_PNG))

    def test_closing_is_free_when_idle(self):
        _, window = self._run_with_fake_webview(running=False)
        self.assertTrue(window.events.closing[0]())
        self.assertFalse(window.asked)

    def test_closing_during_sync_asks_and_can_be_cancelled(self):
        _, window = self._run_with_fake_webview(running=True, answer=False)
        self.assertFalse(window.events.closing[0]())
        self.assertTrue(window.asked)

    def test_missing_pywebview_gives_help(self):
        with mock.patch.dict(sys.modules, {"webview": None}):
            with self.assertRaises(DesktopUnavailable):
                DesktopWindow("http://x", ICON_PNG, lambda: False).run()


class _TrayWindow(_FakeWindow):
    """!
    @brief A window stub that records what the tray features call.
    """

    def __init__(self, answer=True):
        """!
        @brief Create the stub with all events the tray mode uses.
        @param answer What the confirmation dialog answers.
        """
        super().__init__(answer)
        self.events.minimized = _Event()
        self.events.restored = _Event()
        self.show, self.hide = mock.Mock(), mock.Mock()
        self.restore, self.destroy = mock.Mock(), mock.Mock()


class CloseToTrayTests(unittest.TestCase):
    """!
    @brief Tests for how the window behaves together with a tray icon.
    """

    def _start(self, running=False, answer=True, tray_error=None):
        """!
        @brief Run the window with a stubbed pywebview and tray.
        @param running Whether a sync counts as running.
        @param answer What the confirmation dialog answers.
        @param tray_error An exception the tray raises on start, or None.
        @return A tuple (the DesktopWindow, the fake window, the fake tray).
        """
        window = _TrayWindow(answer)
        tray = mock.Mock()
        tray.start.side_effect = tray_error
        fake = types.SimpleNamespace(create_window=mock.Mock(return_value=window), start=mock.Mock())
        shell = DesktopWindow("http://x", ICON_PNG, lambda: running, tray=tray)
        with mock.patch.dict(sys.modules, {"webview": fake}), mock.patch("builtins.print"):
            shell.run()
        return shell, window, tray

    def test_closing_hides_the_window(self):
        _, window, tray = self._start(running=True)
        self.assertFalse(window.events.closing[0]())
        window.hide.assert_called_once()
        self.assertFalse(window.asked)
        tray.stop.assert_called_once()

    def test_closing_quits_if_there_is_no_tray(self):
        _, window, _ = self._start(tray_error=TrayUnavailable("none"))
        self.assertTrue(window.events.closing[0]())
        window.hide.assert_not_called()

    def test_quit_while_idle_closes_without_asking(self):
        shell, window, _ = self._start()
        shell.quit()
        window.destroy.assert_called_once()
        self.assertTrue(window.events.closing[0]())
        self.assertFalse(window.asked)

    def test_cancelled_quit_returns_to_hiding_on_close(self):
        shell, window, _ = self._start(running=True, answer=False)
        shell.quit()
        window.show.assert_called_once()
        self.assertFalse(window.events.closing[0]())
        self.assertTrue(window.asked)
        window.asked = False
        self.assertFalse(window.events.closing[0]())
        self.assertFalse(window.asked)

    def test_open_shows_a_closed_window_and_never_hides_it(self):
        shell, window, _ = self._start()
        window.events.closing[0]()
        window.hide.reset_mock()
        shell.open()
        window.show.assert_called_once()
        window.hide.assert_not_called()

    def test_open_presents_a_gtk_window(self):
        shell, window, _ = self._start()
        window.native = mock.Mock()
        shell.open()
        window.native.present.assert_called_once()
        window.hide.assert_not_called()

    def test_open_restores_only_a_minimized_window(self):
        shell, window, _ = self._start()
        shell.open()
        window.restore.assert_not_called()
        window.events.minimized[0]()
        shell.open()
        window.restore.assert_called_once()


class SyncToggleTests(unittest.TestCase):
    """!
    @brief Tests for the Start / Stop entry, with a stubbed sync manager.
    """

    def setUp(self):
        """!
        @brief Create a toggle around an idle manager stub.
        """
        self.manager = mock.Mock(state=SyncState.IDLE, last_mode=SyncMode.DOWNLOAD)
        self.manager.is_busy.return_value = False
        self.toggle = SyncToggle(self.manager)

    def test_idle_starts_the_last_used_mode(self):
        self.assertEqual(self.toggle.label(), "Start sync (download only)")
        self.assertEqual(self.toggle.toggle(), "")
        self.manager.start.assert_called_once_with(SyncMode.DOWNLOAD)

    def test_running_stops(self):
        self.manager.state = SyncState.RUNNING
        self.manager.is_busy.return_value = True
        self.assertEqual(self.toggle.label(), "Stop sync")
        self.toggle.toggle()
        self.manager.stop.assert_called_once()
        self.manager.start.assert_not_called()

    def test_stopping_is_disabled(self):
        self.manager.state = SyncState.STOPPING
        self.assertFalse(self.toggle.is_enabled())

    def test_refused_start_returns_the_reason(self):
        self.manager.start.side_effect = SyncConfigError("No active folder pair.")
        self.assertEqual(self.toggle.toggle(), "No active folder pair.")


class TrayIconTests(unittest.TestCase):
    """!
    @brief Tests for the pystray wrapper, with pystray and Pillow replaced by stubs.
    """

    def _start(self, problem=""):
        """!
        @brief Start a tray icon on a pretend Windows (no D-Bus check needed).
        @param problem What the toggle answers to a click.
        @return A tuple (tray, fake pystray, menu actions by position, mocks).
        """
        pystray = mock.Mock()
        pil = types.SimpleNamespace(Image=mock.Mock())
        calls = types.SimpleNamespace(open=mock.Mock(), quit=mock.Mock(), report=mock.Mock())
        toggle = mock.Mock()
        toggle.toggle.return_value = problem
        tray = TrayIcon(ICON_PNG, toggle, calls.report)
        with mock.patch.dict(sys.modules, {"pystray": pystray, "PIL": pil}), \
                mock.patch.object(sys, "platform", "win32"):
            tray.start(calls.open, calls.quit)
        self.addCleanup(tray.stop)
        actions = [call.args[1] for call in pystray.MenuItem.call_args_list]
        return tray, pystray, actions, calls

    def test_menu_has_three_working_entries(self):
        _, pystray, actions, calls = self._start()
        self.assertEqual(len(actions), 3)
        for action in actions:
            action(None, None)
        calls.open.assert_called_once()
        calls.quit.assert_called_once()
        pystray.Icon.return_value.run_detached.assert_called_once()

    def test_refused_start_is_reported_and_opens_the_dashboard(self):
        _, pystray, actions, calls = self._start(problem="rclone was not found")
        actions[1](None, None)
        calls.report.assert_called_once_with("rclone was not found")
        calls.open.assert_called_once()
        pystray.Icon.return_value.notify.assert_called_once()

    def test_missing_pystray_gives_help(self):
        tray = TrayIcon(ICON_PNG, mock.Mock(), mock.Mock())
        with mock.patch.dict(sys.modules, {"pystray": None}), \
                mock.patch.object(sys, "platform", "win32"):
            with self.assertRaisesRegex(TrayUnavailable, "python3-pystray"):
                tray.start(mock.Mock(), mock.Mock())


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow is not installed")
class StatusIconsTests(unittest.TestCase):
    """!
    @brief Tests for the coloured icons, made from the real app icon.
    """

    def setUp(self):
        """!
        @brief Load the icons.
        """
        self.icons = StatusIcons(ICON_PNG)

    def _tile_colour(self, state):
        """!
        @brief Read a pixel of the tile, left of the symbol.
        @param state The sync state.
        @return The colour as (red, green, blue).
        """
        return self.icons.for_state(state).getpixel((8, 24))[:3]

    def test_ready_and_successful_states_are_green(self):
        for state in (SyncState.IDLE, SyncState.SUCCEEDED, SyncState.CANCELLED):
            red, green, blue = self._tile_colour(state)
            self.assertTrue(green > red and green > blue, state)

    def test_syncing_is_yellow_and_failure_is_red(self):
        for state, wanted in ((SyncState.RUNNING, YELLOW), (SyncState.STOPPING, YELLOW),
                              (SyncState.FAILED, RED)):
            for actual, expected in zip(self._tile_colour(state), wanted):
                self.assertAlmostEqual(actual, expected, delta=8, msg=state)

    def test_corners_stay_transparent(self):
        self.assertEqual(self.icons.for_state(SyncState.FAILED).getpixel((0, 0))[3], 0)


class TrayRefreshTests(unittest.TestCase):
    """!
    @brief Tests that the tray follows the sync state.
    """

    def test_icon_changes_only_when_the_colour_changes(self):
        toggle = mock.Mock()
        toggle.state.return_value = SyncState.IDLE
        pictures = {SyncState.IDLE: "green", SyncState.RUNNING: "yellow"}
        tray = TrayIcon(ICON_PNG, toggle, mock.Mock())
        tray._icon = mock.Mock(icon="green")
        tray._images = mock.Mock(for_state=pictures.get)
        tray._shown_image = "green"

        tray.refresh()
        tray.refresh()
        self.assertEqual(tray._icon.icon, "green")
        tray._icon.update_menu.assert_called_once()

        toggle.state.return_value = SyncState.RUNNING
        tray.refresh()
        self.assertEqual(tray._icon.icon, "yellow")


class LastModeStoreTests(unittest.TestCase):
    """!
    @brief Tests for remembering the sync mode.
    """

    def test_saved_mode_is_loaded_and_bad_files_fall_back_to_two_way(self):
        with tempfile.TemporaryDirectory() as folder:
            store = LastModeStore(Path(folder) / "last_mode.txt")
            self.assertIs(store.load(), SyncMode.BISYNC)
            store.save(SyncMode.DOWNLOAD)
            self.assertIs(store.load(), SyncMode.DOWNLOAD)
            (Path(folder) / "last_mode.txt").write_text("nonsense")
            self.assertIs(store.load(), SyncMode.BISYNC)


if __name__ == "__main__":
    unittest.main()
