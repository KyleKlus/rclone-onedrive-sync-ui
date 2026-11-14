"""
End-to-end tests: real backend, real HTTP, fake rclone.

Run from the project folder with:
    python -m unittest discover -s tests -v
"""

import http.client
import json
import os
import shutil
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import Application          # noqa: E402
from backend.security import LocalhostGuard  # noqa: E402

FAKE_RCLONE = Path(__file__).resolve().parent / "fake_rclone.py"


class GuardTests(unittest.TestCase):
    """The localhost guard, tested without any network."""

    def setUp(self):
        self.guard = LocalhostGuard(port=8765)

    def test_client_addresses(self):
        for ip in ("127.0.0.1", "::1", "::ffff:127.0.0.1"):
            self.assertTrue(self.guard.is_client_allowed(ip), ip)
        for ip in ("192.168.1.20", "10.0.0.5", "8.8.8.8", "not-an-ip", ""):
            self.assertFalse(self.guard.is_client_allowed(ip), ip)

    def test_host_header(self):
        for host in ("localhost:8765", "127.0.0.1:8765", "[::1]:8765", "localhost"):
            self.assertTrue(self.guard.is_host_header_allowed(host), host)
        for host in ("evil.com", "evil.com:8765", "127.0.0.1.evil.com", "", None):
            self.assertFalse(self.guard.is_host_header_allowed(host), host)

    def test_origin_header(self):
        self.assertTrue(self.guard.is_origin_allowed(None))
        self.assertTrue(self.guard.is_origin_allowed("http://127.0.0.1:8765"))
        self.assertTrue(self.guard.is_origin_allowed("http://localhost:8765"))
        for origin in ("http://evil.com", "http://localhost:3000", "null", "http://127.0.0.1"):
            self.assertFalse(self.guard.is_origin_allowed(origin), origin)


class ServerTestCase(unittest.TestCase):
    """Starts the whole app on a free port for each test."""

    def setUp(self):
        os.chmod(FAKE_RCLONE, os.stat(FAKE_RCLONE).st_mode | stat.S_IXUSR)
        self.workdir = Path(tempfile.mkdtemp())
        self.local_dir = self.workdir / "local"
        self.local_dir.mkdir()

        os.environ["FAKE_RCLONE_MODE"] = "ok"
        self.app = Application(
            data_dir=self.workdir / "data",
            rclone_binary=str(FAKE_RCLONE),
            port=0,
        )
        threading.Thread(target=self.app.run, daemon=True).start()

    def tearDown(self):
        self.app.shutdown()
        shutil.rmtree(self.workdir, ignore_errors=True)

    # --- helpers ---

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=5)
        payload = json.dumps(body) if body is not None else None
        request_headers = {"Content-Type": "application/json"} if payload else {}
        request_headers.update(headers or {})
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        raw = response.read().decode("utf-8")
        connection.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw

    def save_settings(self, **overrides):
        settings = {
            "local_path": str(self.local_dir),
            "remote": "onedrive:",
            "max_size": "50M",
            "exclusions": ["*.tmp"],
        }
        settings.update(overrides)
        return self.request("PUT", "/api/settings", settings)

    def wait_for_state(self, wanted, timeout=10):
        deadline = time.time() + timeout
        status = {}
        while time.time() < deadline:
            _, status = self.request("GET", "/api/status")
            if status["state"] in wanted:
                return status
            time.sleep(0.05)
        self.fail(f"Timed out waiting for {wanted}; last status: {status}")

    def log_text(self):
        _, log = self.request("GET", "/api/log?after=0")
        return "\n".join(entry["text"] for entry in log["entries"])


class SecurityTests(ServerTestCase):
    def test_foreign_host_header_is_rejected(self):
        status, _ = self.request("GET", "/api/status", headers={"Host": "evil.com"})
        self.assertEqual(status, 403)

    def test_foreign_origin_is_rejected(self):
        status, _ = self.request("POST", "/api/stop", headers={"Origin": "http://evil.com"})
        self.assertEqual(status, 403)

    def test_path_traversal_is_blocked(self):
        for path in ("/../run.py", "/..%2Frun.py", "/%2e%2e/run.py", "/css/../../run.py"):
            status, _ = self.request("GET", path)
            self.assertEqual(status, 404, path)

    def test_frontend_files_are_served_with_correct_types(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.app.port, timeout=5)
        for path, expected in (("/", "text/html"), ("/css/base.css", "text/css"),
                               ("/js/main.js", "text/javascript")):
            connection.request("GET", path)
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.status, 200, path)
            self.assertIn(expected, response.getheader("Content-Type"), path)
        connection.close()


class SettingsTests(ServerTestCase):
    def test_round_trip_and_cleanup(self):
        status, saved = self.save_settings(exclusions=["  node_modules/ ", "*.iso", "*.iso", ""])
        self.assertEqual(status, 200)
        self.assertEqual(saved["exclusions"], ["node_modules/", "*.iso"])
        _, loaded = self.request("GET", "/api/settings")
        self.assertEqual(loaded, saved)

    def test_invalid_values_are_rejected(self):
        for bad in ({"max_size": "huge"}, {"remote": "nocolon"}, {"remote": "C:"},
                    {"local_path": "relative/path"}, {"exclusions": ["#comment"]}):
            status, body = self.save_settings(**bad)
            self.assertEqual(status, 400, bad)
            self.assertIn("error", body)

    def test_defaults_endpoint(self):
        status, defaults = self.request("GET", "/api/settings/defaults")
        self.assertEqual(status, 200)
        self.assertEqual(defaults["remote"], "onedrive:")
        self.assertEqual(defaults["max_size"], "50M")
        self.assertIn("*.tmp", defaults["exclusions"])
        # Asking for defaults must not change the saved settings.
        self.save_settings(max_size="2G")
        self.request("GET", "/api/settings/defaults")
        _, current = self.request("GET", "/api/settings")
        self.assertEqual(current["max_size"], "2G")

    def test_settings_persist_to_disk(self):
        self.save_settings(max_size="2G")
        saved = json.loads((self.workdir / "data" / "settings.json").read_text())
        self.assertEqual(saved["max_size"], "2G")


class SyncTests(ServerTestCase):
    def test_start_requires_a_local_folder(self):
        status, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 400)
        self.assertIn("local folder", body["error"].lower())

    def test_unknown_mode_is_rejected(self):
        self.save_settings()
        status, _ = self.request("POST", "/api/sync", {"mode": "teleport"})
        self.assertEqual(status, 400)

    def test_bisync_command_and_success(self):
        self.save_settings(max_size="10M", exclusions=["*.tmp", "node_modules/"])
        status, _ = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 202)
        result = self.wait_for_state({"succeeded", "failed"})
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["exit_code"], 0)

        log = self.log_text()
        # Path1 = local, Path2 = OneDrive; OneDrive (path2) wins conflicts.
        self.assertIn(f"ARGS: bisync {self.local_dir} onedrive:", log)
        self.assertIn("--conflict-resolve path2", log)
        self.assertIn("--max-size 10M", log)          # user's value replaced the 50M default
        self.assertNotIn("--max-size 50M", log)
        self.assertIn("--check-access", log)
        self.assertIn("--filters-file", log)
        self.assertNotIn("--resync", log)
        self.assertIn("Copied (new)", log)             # rclone output is streamed into the log

        filters = (self.workdir / "data" / "filters.txt").read_text()
        self.assertIn("- *.tmp", filters)
        self.assertIn("- node_modules/", filters)

    def test_download_command(self):
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "download"})
        self.assertEqual(self.wait_for_state({"succeeded", "failed"})["state"], "succeeded")
        log = self.log_text()
        self.assertIn(f"ARGS: sync onedrive: {self.local_dir}", log)   # OneDrive is the source
        self.assertNotIn("bisync", log.split("ARGS:")[1])
        self.assertIn("--max-delete 25", log)

    def test_dry_run_flag(self):
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "download", "dry_run": True})
        status = self.wait_for_state({"succeeded", "failed"})
        self.assertTrue(status["dry_run"])
        self.assertIn("--dry-run", self.log_text())

    def test_first_time_setup_creates_access_file_and_resyncs(self):
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "bisync", "resync": True})
        self.assertEqual(self.wait_for_state({"succeeded", "failed"})["state"], "succeeded")
        self.assertTrue((self.local_dir / "RCLONE_TEST").exists())
        log = self.log_text()
        self.assertIn("ARGS: copyto --ignore-existing", log)           # uploads RCLONE_TEST
        self.assertIn("onedrive:RCLONE_TEST", log)
        self.assertIn("--resync --resync-mode path2", log)             # OneDrive wins on baseline

    def test_resync_is_refused_for_download_mode(self):
        self.save_settings()
        status, _ = self.request("POST", "/api/sync", {"mode": "download", "resync": True})
        self.assertEqual(status, 400)

    def test_failure_is_reported(self):
        os.environ["FAKE_RCLONE_MODE"] = "fail"
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        result = self.wait_for_state({"succeeded", "failed"})
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["exit_code"], 1)
        self.assertFalse(result["needs_resync"])

    def test_resync_hint_is_detected(self):
        os.environ["FAKE_RCLONE_MODE"] = "need_resync"
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        result = self.wait_for_state({"failed"})
        self.assertTrue(result["needs_resync"])
        self.assertIn("first-time setup", result["message"])

    def test_log_levels_are_detected(self):
        os.environ["FAKE_RCLONE_MODE"] = "fail"
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"failed"})
        _, log = self.request("GET", "/api/log?after=0")
        levels = {entry["text"]: entry["level"] for entry in log["entries"]}
        self.assertEqual(levels["2026/11/13 21:40:00 ERROR : something went wrong"], "error")

    def test_log_is_incremental(self):
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"succeeded"})
        _, first = self.request("GET", "/api/log?after=0")
        _, second = self.request("GET", f"/api/log?after={first['last_id']}")
        self.assertGreater(len(first["entries"]), 3)
        self.assertEqual(second["entries"], [])
        self.assertEqual(second["last_id"], first["last_id"])

    def test_busy_stop_and_settings_lock(self):
        os.environ["FAKE_RCLONE_MODE"] = "slow"
        self.save_settings()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(self.wait_for_state({"running"})["state"], "running")

        status, _ = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 409)                      # second start refused
        status, _ = self.save_settings(max_size="1G")
        self.assertEqual(status, 409)                      # settings locked while running

        self.request("POST", "/api/stop")
        result = self.wait_for_state({"cancelled", "succeeded", "failed"})
        self.assertEqual(result["state"], "cancelled")
        self.assertIn("Stopped by you", result["message"])

        status, _ = self.save_settings(max_size="1G")
        self.assertEqual(status, 200)                      # unlocked again

    def test_missing_rclone_is_reported(self):
        self.app.sync_manager._rclone_binary = "definitely-not-installed-rclone"
        self.save_settings()
        _, status = self.request("GET", "/api/status")
        self.assertFalse(status["rclone_available"])
        code, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(code, 400)
        self.assertIn("rclone was not found", body["error"])


if __name__ == "__main__":
    unittest.main()
