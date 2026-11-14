"""Tests for the desktop shell (no real window needed: pywebview is replaced by a stub)."""

import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from desktop.identity import APP_ID, ICON_PNG, ICON_SVG
from desktop.launcher_entry import LauncherEntry
from desktop.single_instance import InstanceLock
from desktop.window import DesktopUnavailable, DesktopWindow


class InstanceLockTests(unittest.TestCase):
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
    def test_install_and_uninstall(self):
        with tempfile.TemporaryDirectory() as folder:
            entry = LauncherEntry(Path("/opt/my app/run_desktop.py"), data_home=Path(folder))
            desktop_file = entry.install()

            self.assertEqual(desktop_file.name, f"{APP_ID}.desktop")
            text = desktop_file.read_text()
            self.assertIn(f"Icon={APP_ID}", text)
            self.assertIn(f"StartupWMClass={APP_ID}", text)
            self.assertIn("'/opt/my app/run_desktop.py'", text)  # path with a space is quoted
            self.assertTrue((Path(folder) / "icons/hicolor/512x512/apps" / f"{APP_ID}.png").is_file())
            self.assertTrue((Path(folder) / "icons/hicolor/scalable/apps" / f"{APP_ID}.svg").is_file())

            entry.uninstall()
            self.assertFalse(desktop_file.exists())

    def test_icon_sources_exist(self):
        self.assertTrue(ICON_PNG.is_file())
        self.assertTrue(ICON_SVG.is_file())


class _Event(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self


class _FakeWindow:
    def __init__(self, answer=True):
        self.events = types.SimpleNamespace(closing=_Event())
        self.answer = answer
        self.asked = False

    def create_confirmation_dialog(self, title, message):
        self.asked = True
        return self.answer


class DesktopWindowTests(unittest.TestCase):
    def _run_with_fake_webview(self, running, answer=True):
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

    def test_dmabuf_workaround_is_set_but_overridable(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("WEBKIT_DISABLE_DMABUF_RENDERER", None)
            DesktopWindow._apply_rendering_workarounds()
            self.assertEqual(env["WEBKIT_DISABLE_DMABUF_RENDERER"], "1")
            env["WEBKIT_DISABLE_DMABUF_RENDERER"] = "0"
            DesktopWindow._apply_rendering_workarounds()
            self.assertEqual(env["WEBKIT_DISABLE_DMABUF_RENDERER"], "0")

    def test_missing_pywebview_gives_help(self):
        with mock.patch.dict(sys.modules, {"webview": None}):
            with self.assertRaises(DesktopUnavailable):
                DesktopWindow("http://x", ICON_PNG, lambda: False).run()


if __name__ == "__main__":
    unittest.main()
