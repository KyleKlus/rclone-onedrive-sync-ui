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
from backend.server.security import LocalhostGuard  # noqa: E402

FAKE_RCLONE = Path(__file__).resolve().parent / "fake_rclone.py"


class LogBufferTests(unittest.TestCase):
    def test_ansi_colour_codes_are_removed(self):
        from backend.command.log_buffer import LogBuffer
        log = LogBuffer(10)
        entry = log.append("2026/11/14 15:52:03 ERROR : \x1b[31mBisync critical error\x1b[0m")
        self.assertEqual(entry.text, "2026/11/14 15:52:03 ERROR : Bisync critical error")
        self.assertEqual(entry.level, "error")
        self.assertEqual(log.append("\x1b[33mplain\x1b[0m").text, "plain")

    def test_lines_carry_the_name_of_their_folder_pair(self):
        from backend.command.log_buffer import LogBuffer
        log = LogBuffer(10)
        self.assertEqual(log.append("from a pair", source="Docs").source, "Docs")
        self.assertEqual(log.append("from the app").source, "")
        self.assertEqual(log.entries_after(0)[0].to_dict()["source"], "Docs")


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
        self.local_dir = self.make_folder("local")

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

    def make_folder(self, name):
        folder = self.workdir / name
        folder.mkdir()
        return folder

    def pair_data(self, name="Docs", **overrides):
        data = {
            "name": name,
            "local_path": str(self.local_dir),
            "remote": "onedrive:",
            "max_size": "50M",
            "exclusions": ["*.tmp"],
        }
        data.update(overrides)
        return data

    def create_pair(self, name="Docs", **overrides):
        """Create a folder pair and return it as the API reports it."""
        status, pair = self.request("POST", "/api/pairs", self.pair_data(name, **overrides))
        self.assertEqual(status, 201, pair)
        return pair

    def create_separate_pairs(self, *names):
        """Pairs with their own local and remote folder each, so they may sync in parallel."""
        return [
            self.create_pair(
                name,
                local_path=str(self.make_folder(name)),
                remote=f"onedrive:{name}",
            )
            for name in names
        ]

    def pairs_by_name(self):
        _, status = self.request("GET", "/api/status")
        return {pair["name"]: pair for pair in status["pairs"]}

    def wait_for_state(self, wanted, timeout=10):
        deadline = time.time() + timeout
        status = {}
        while time.time() < deadline:
            _, status = self.request("GET", "/api/status")
            if status["state"] in wanted:
                return status
            time.sleep(0.05)
        self.fail(f"Timed out waiting for {wanted}; last status: {status}")

    def wait_for_pairs(self, condition, timeout=10):
        """Wait until ``condition(pairs_by_name)`` is true; return the pairs."""
        deadline = time.time() + timeout
        pairs = {}
        while time.time() < deadline:
            pairs = self.pairs_by_name()
            if condition(pairs):
                return pairs
            time.sleep(0.05)
        self.fail(f"Timed out waiting for a condition; last pairs: {pairs}")

    def log_entries(self):
        _, log = self.request("GET", "/api/log?after=0")
        return log["entries"]

    def log_text(self):
        return "\n".join(entry["text"] for entry in self.log_entries())


class SecurityTests(ServerTestCase):
    def test_foreign_host_header_is_rejected(self):
        status, _ = self.request("GET", "/api/status", headers={"Host": "evil.com"})
        self.assertEqual(status, 403)

    def test_foreign_origin_is_rejected(self):
        status, _ = self.request("POST", "/api/stop", headers={"Origin": "http://evil.com"})
        self.assertEqual(status, 403)

    def test_deleting_is_guarded_like_everything_else(self):
        pair = self.create_pair()
        for headers in ({"Host": "evil.com"}, {"Origin": "http://evil.com"}):
            status, _ = self.request("DELETE", f"/api/pairs/{pair['id']}", headers=headers)
            self.assertEqual(status, 403, headers)
        self.assertEqual(self.request("GET", f"/api/pairs/{pair['id']}")[0], 200)

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


class PairApiTests(ServerTestCase):
    def test_create_read_update_delete(self):
        pair = self.create_pair(exclusions=["  node_modules/ ", "*.iso", "*.iso", ""])
        self.assertEqual(pair["exclusions"], ["node_modules/", "*.iso"])   # cleaned up
        self.assertTrue(pair["enabled"])

        _, loaded = self.request("GET", f"/api/pairs/{pair['id']}")
        self.assertEqual(loaded, pair)

        status, updated = self.request("PUT", f"/api/pairs/{pair['id']}", self.pair_data("Renamed", max_size="2G"))
        self.assertEqual(status, 200)
        self.assertEqual((updated["id"], updated["name"], updated["max_size"]), (pair["id"], "Renamed", "2G"))

        status, _ = self.request("DELETE", f"/api/pairs/{pair['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(self.request("GET", f"/api/pairs/{pair['id']}")[0], 404)

    def test_invalid_values_are_rejected(self):
        for bad in ({"name": ""}, {"name": "x" * 41}, {"name": "two\nlines"},
                    {"max_size": "huge"}, {"remote": "nocolon"}, {"remote": "C:"},
                    {"local_path": "relative/path"}, {"exclusions": ["#comment"]}):
            status, body = self.request("POST", "/api/pairs", self.pair_data(**bad))
            self.assertEqual(status, 400, bad)
            self.assertIn("error", body)
        self.assertEqual(self.pairs_by_name(), {})   # nothing was created

    def test_names_must_be_unique(self):
        first = self.create_pair("Docs")
        status, body = self.request("POST", "/api/pairs", self.pair_data("docs"))
        self.assertEqual(status, 400)
        self.assertIn("already called", body["error"])
        # A pair may of course keep its own name when it is saved again.
        status, _ = self.request("PUT", f"/api/pairs/{first['id']}", self.pair_data("Docs", max_size="2G"))
        self.assertEqual(status, 200)

    def test_unknown_pair_is_reported_as_404(self):
        for method, path, body in (("GET", "/api/pairs/nope", None),
                                   ("PUT", "/api/pairs/nope", self.pair_data()),
                                   ("PUT", "/api/pairs/nope/enabled", {"enabled": True}),
                                   ("DELETE", "/api/pairs/nope", None)):
            status, _ = self.request(method, path, body)
            self.assertEqual(status, 404, (method, path))

    def test_wrong_method_is_reported_as_405(self):
        pair = self.create_pair()
        self.assertEqual(self.request("POST", f"/api/pairs/{pair['id']}", {})[0], 405)
        self.assertEqual(self.request("DELETE", "/api/status")[0], 405)

    def test_pairs_can_be_switched_on_and_off(self):
        pair = self.create_pair()
        status, saved = self.request("PUT", f"/api/pairs/{pair['id']}/enabled", {"enabled": False})
        self.assertEqual(status, 200)
        self.assertFalse(saved["enabled"])
        self.assertFalse(self.pairs_by_name()["Docs"]["enabled"])

        for bad in ({"enabled": "no"}, {}):
            status, _ = self.request("PUT", f"/api/pairs/{pair['id']}/enabled", bad)
            self.assertEqual(status, 400, bad)

        self.request("PUT", f"/api/pairs/{pair['id']}/enabled", {"enabled": True})
        self.assertTrue(self.pairs_by_name()["Docs"]["enabled"])

    def test_defaults_endpoint(self):
        status, defaults = self.request("GET", "/api/setup/defaults")
        self.assertEqual(status, 200)
        self.assertEqual(defaults["remote"], "onedrive:")
        self.assertEqual(defaults["max_size"], "50M")
        self.assertIn("*.tmp", defaults["exclusions"])
        # Asking for defaults must not change anything that is saved.
        pair = self.create_pair(max_size="2G")
        self.request("GET", "/api/setup/defaults")
        _, current = self.request("GET", f"/api/pairs/{pair['id']}")
        self.assertEqual(current["max_size"], "2G")

    def test_pairs_persist_to_disk(self):
        self.create_pair(max_size="2G")
        saved = json.loads((self.workdir / "data" / "pairs.json").read_text())
        self.assertEqual([(pair["name"], pair["max_size"]) for pair in saved["pairs"]], [("Docs", "2G")])

    def test_status_lists_every_pair_with_its_own_state(self):
        self.create_separate_pairs("A", "B")
        _, status = self.request("GET", "/api/status")
        self.assertEqual([pair["name"] for pair in status["pairs"]], ["A", "B"])   # creation order
        for pair in status["pairs"]:
            self.assertEqual(pair["state"], "idle")
            self.assertTrue(pair["enabled"])
            self.assertEqual(pair["overlaps_with"], [])
        self.assertEqual(status["pairs"][0]["remote"], "onedrive:A")

    def test_status_names_the_pairs_that_share_folders(self):
        self.create_pair("Whole drive", local_path=str(self.make_folder("a")), remote="onedrive:")
        other = self.create_pair("Docs", local_path=str(self.make_folder("b")), remote="onedrive:Docs")

        pairs = self.pairs_by_name()
        self.assertEqual(pairs["Whole drive"]["overlaps_with"], ["Docs"])
        self.assertEqual(pairs["Docs"]["overlaps_with"], ["Whole drive"])

        # A pair that is switched off cannot collide with anything.
        self.request("PUT", f"/api/pairs/{other['id']}/enabled", {"enabled": False})
        pairs = self.pairs_by_name()
        self.assertEqual(pairs["Whole drive"]["overlaps_with"], [])
        self.assertEqual(pairs["Docs"]["overlaps_with"], [])


class SyncTests(ServerTestCase):
    def test_start_requires_a_local_folder(self):
        self.create_pair(local_path="")
        status, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 400)
        self.assertIn("local folder", body["error"].lower())
        self.assertIn("'Docs'", body["error"])        # says WHICH pair is incomplete

    def test_start_requires_an_existing_local_folder(self):
        self.create_pair(local_path=str(self.workdir / "missing"))
        status, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 400)
        self.assertIn("does not exist", body["error"])

    def test_start_requires_an_active_pair(self):
        status, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 400)
        self.assertIn("no active folder pair", body["error"].lower())

        pair = self.create_pair()
        self.request("PUT", f"/api/pairs/{pair['id']}/enabled", {"enabled": False})
        status, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 400)
        self.assertIn("no active folder pair", body["error"].lower())

    def test_unknown_mode_is_rejected(self):
        self.create_pair()
        status, _ = self.request("POST", "/api/sync", {"mode": "teleport"})
        self.assertEqual(status, 400)

    def test_bisync_command_and_success(self):
        pair = self.create_pair(max_size="10M", exclusions=["*.tmp", "node_modules/"])
        status, _ = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 202)
        result = self.wait_for_state({"succeeded", "failed"})
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(result["pairs"][0]["state"], "succeeded")
        self.assertEqual(result["pairs"][0]["exit_code"], 0)

        log = self.log_text()
        # Path1 = local, Path2 = OneDrive; OneDrive (path2) wins conflicts.
        self.assertIn(f"ARGS: bisync {self.local_dir} onedrive:", log)
        self.assertIn("--conflict-resolve path2", log)
        self.assertIn("--max-size 10M", log)          # user's value replaced the 50M default
        self.assertNotIn("--max-size 50M", log)
        self.assertIn("--check-access", log)
        self.assertIn("--filters-file", log)           # bisync's own flag
        self.assertNotIn("--filter-from", log)
        self.assertNotIn("--resync", log)
        self.assertIn("Copied (new)", log)             # rclone output is streamed into the log

        # Every pair has its own filter file, named after the pair's id.
        filters = (self.workdir / "data" / "filters" / f"{pair['id']}.txt").read_text()
        self.assertIn("- *.tmp", filters)
        self.assertIn("- node_modules/", filters)

    def test_download_command(self):
        self.create_pair()
        self.request("POST", "/api/sync", {"mode": "download"})
        self.assertEqual(self.wait_for_state({"succeeded", "failed"})["state"], "succeeded")
        log = self.log_text()
        self.assertIn(f"ARGS: sync onedrive: {self.local_dir}", log)   # OneDrive is the source
        self.assertNotIn("bisync", log.split("ARGS:")[1])
        self.assertIn("--max-delete 25", log)
        self.assertIn("--filter-from", log)            # `sync` has no --filters-file
        self.assertNotIn("--filters-file", log)
        self.assertIn("Copied (new)", log)             # i.e. the fake rclone accepted every flag

    def test_dry_run_flag(self):
        self.create_pair()
        self.request("POST", "/api/sync", {"mode": "download", "dry_run": True})
        status = self.wait_for_state({"succeeded", "failed"})
        self.assertTrue(status["dry_run"])
        self.assertIn("--dry-run", self.log_text())

    def test_first_time_setup_creates_access_file_and_resyncs(self):
        self.create_pair()
        self.request("POST", "/api/sync", {"mode": "bisync", "resync": True})
        self.assertEqual(self.wait_for_state({"succeeded", "failed"})["state"], "succeeded")
        self.assertTrue((self.local_dir / "RCLONE_TEST").exists())
        log = self.log_text()
        self.assertIn("ARGS: copyto --ignore-existing", log)           # uploads RCLONE_TEST
        self.assertIn("onedrive:RCLONE_TEST", log)
        self.assertIn("--resync --resync-mode path2", log)             # OneDrive wins on baseline

    def test_resync_is_refused_for_download_mode(self):
        self.create_pair()
        status, _ = self.request("POST", "/api/sync", {"mode": "download", "resync": True})
        self.assertEqual(status, 400)

    def test_failure_is_reported(self):
        os.environ["FAKE_RCLONE_MODE"] = "fail"
        self.create_pair()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        result = self.wait_for_state({"succeeded", "failed"})
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["pairs"][0]["state"], "failed")
        self.assertEqual(result["pairs"][0]["exit_code"], 1)
        self.assertFalse(result["needs_resync"])

    def test_resync_hint_is_detected(self):
        os.environ["FAKE_RCLONE_MODE"] = "need_resync"
        self.create_pair()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        result = self.wait_for_state({"failed"})
        self.assertTrue(result["needs_resync"])
        self.assertTrue(result["pairs"][0]["needs_resync"])
        self.assertIn("first-time setup", result["message"])

    def test_log_levels_are_detected(self):
        os.environ["FAKE_RCLONE_MODE"] = "fail"
        self.create_pair()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"failed"})
        levels = {entry["text"]: entry["level"] for entry in self.log_entries()}
        self.assertEqual(levels["2026/11/13 21:40:00 ERROR : something went wrong"], "error")

    def test_log_is_incremental(self):
        self.create_pair()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"succeeded"})
        _, first = self.request("GET", "/api/log?after=0")
        _, second = self.request("GET", f"/api/log?after={first['last_id']}")
        self.assertGreater(len(first["entries"]), 3)
        self.assertEqual(second["entries"], [])
        self.assertEqual(second["last_id"], first["last_id"])

    def test_log_lines_are_tagged_with_the_pair_name(self):
        self.create_separate_pairs("Docs", "Photos")
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"succeeded"})

        entries = self.log_entries()
        for name in ("Docs", "Photos"):
            tagged = [entry["text"] for entry in entries if entry["source"] == name]
            self.assertTrue(any("Copied (new)" in text for text in tagged), name)   # rclone lines
            self.assertTrue(any(text.startswith("$ ") for text in tagged), name)    # the app's own lines
        # The overall closing line belongs to no pair.
        closing = [entry for entry in entries if entry["text"].startswith("== SUCCEEDED")]
        self.assertEqual([entry["source"] for entry in closing if "All 2" in entry["text"]], [""])

    def test_busy_stop_and_lock(self):
        os.environ["FAKE_RCLONE_MODE"] = "slow"
        pair = self.create_pair()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(self.wait_for_state({"running"})["state"], "running")

        status, _ = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 409)                      # second start refused
        # Folder pairs cannot be changed in any way while a sync runs.
        for method, path, body in (("POST", "/api/pairs", self.pair_data("Other")),
                                   ("PUT", f"/api/pairs/{pair['id']}", self.pair_data(max_size="1G")),
                                   ("PUT", f"/api/pairs/{pair['id']}/enabled", {"enabled": False}),
                                   ("DELETE", f"/api/pairs/{pair['id']}", None)):
            status, _ = self.request(method, path, body)
            self.assertEqual(status, 409, (method, path))

        self.request("POST", "/api/stop")
        result = self.wait_for_state({"cancelled", "succeeded", "failed"})
        self.assertEqual(result["state"], "cancelled")
        self.assertEqual(result["pairs"][0]["state"], "cancelled")
        self.assertIn("Stopped by you", result["message"])

        status, _ = self.request("PUT", f"/api/pairs/{pair['id']}", self.pair_data(max_size="1G"))
        self.assertEqual(status, 200)                      # unlocked again

    def test_missing_rclone_is_reported(self):
        self.app.sync_manager._rclone_binary = "definitely-not-installed-rclone"
        self.create_pair()
        _, status = self.request("GET", "/api/status")
        self.assertFalse(status["rclone_available"])
        code, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(code, 400)
        self.assertIn("rclone was not found", body["error"])


class MultiplePairsTests(ServerTestCase):
    """Several folder pairs in one run: parallel when allowed, one after the other when not."""

    def test_pairs_without_shared_folders_run_at_the_same_time(self):
        os.environ["FAKE_RCLONE_MODE"] = "slow"
        self.create_separate_pairs("A", "B", "C")
        self.request("POST", "/api/sync", {"mode": "bisync"})

        pairs = self.wait_for_pairs(lambda pairs: all(pair["state"] == "running" for pair in pairs.values()))
        self.assertEqual(len(pairs), 3)
        self.assertEqual(self.wait_for_state({"running"})["state"], "running")
        self.assertIn("3 folder pairs", self.request("GET", "/api/status")[1]["message"])

        self.request("POST", "/api/stop")
        result = self.wait_for_state({"cancelled"})
        self.assertTrue(all(pair["state"] == "cancelled" for pair in result["pairs"]))

    def test_pairs_with_shared_folders_wait_for_each_other(self):
        os.environ["FAKE_RCLONE_MODE"] = "slow"
        # "Inner" lies inside the OneDrive folder of "Outer", so they must not run together.
        self.create_pair("Outer", local_path=str(self.make_folder("outer")), remote="onedrive:Shared")
        self.create_pair("Inner", local_path=str(self.make_folder("inner")), remote="onedrive:Shared/Sub")
        self.create_separate_pairs("Elsewhere")
        self.request("POST", "/api/sync", {"mode": "bisync"})

        pairs = self.wait_for_pairs(lambda pairs: pairs["Outer"]["state"] == "running"
                                    and pairs["Elsewhere"]["state"] == "running")
        self.assertEqual(pairs["Inner"]["state"], "queued")            # waits ...
        self.assertIn("Waiting for 'Outer'", pairs["Inner"]["message"])  # ... and says for whom

        self.request("POST", "/api/stop")
        result = self.wait_for_state({"cancelled"})
        states = {pair["name"]: pair["state"] for pair in result["pairs"]}
        self.assertEqual(states, {"Outer": "cancelled", "Inner": "cancelled", "Elsewhere": "cancelled"})
        # The waiting pair never started, so rclone was never called for it.
        self.assertNotIn(str(self.workdir / "inner"), self.log_text())

    def test_a_waiting_pair_starts_when_the_pair_in_front_is_done(self):
        self.create_pair("First", local_path=str(self.make_folder("first")), remote="onedrive:Shared")
        self.create_pair("Second", local_path=str(self.make_folder("second")), remote="onedrive:Shared")
        self.request("POST", "/api/sync", {"mode": "bisync"})

        result = self.wait_for_state({"succeeded", "failed"})
        self.assertEqual(result["state"], "succeeded")
        first, second = (pair for pair in result["pairs"])
        self.assertEqual((first["state"], second["state"]), ("succeeded", "succeeded"))
        self.assertGreaterEqual(second["started_at"], first["finished_at"])   # strictly one after the other

    def test_pairs_that_are_switched_off_are_skipped(self):
        first, second = self.create_separate_pairs("On", "Off")
        self.request("PUT", f"/api/pairs/{second['id']}/enabled", {"enabled": False})
        self.request("POST", "/api/sync", {"mode": "bisync"})

        result = self.wait_for_state({"succeeded", "failed"})
        self.assertEqual(result["state"], "succeeded")
        self.assertIn("Finished successfully", result["message"])     # one pair: no "All 2 pairs"
        states = {pair["name"]: pair["state"] for pair in result["pairs"]}
        self.assertEqual(states, {"On": "succeeded", "Off": "idle"})
        log = self.log_text()
        self.assertIn(str(self.workdir / "On"), log)
        self.assertNotIn(str(self.workdir / "Off"), log)

    def test_one_failing_pair_does_not_stop_the_others(self):
        self.create_pair("Good", local_path=str(self.make_folder("good")), remote="onedrive:Good")
        self.create_pair("Bad", local_path=str(self.make_folder("FAIL_ME")), remote="onedrive:Bad")
        self.request("POST", "/api/sync", {"mode": "bisync"})

        result = self.wait_for_state({"failed", "succeeded"})
        self.assertEqual(result["state"], "failed")
        self.assertIn("1 of 2 folder pairs failed: 'Bad'", result["message"])
        states = {pair["name"]: pair["state"] for pair in result["pairs"]}
        self.assertEqual(states, {"Good": "succeeded", "Bad": "failed"})

    def test_all_pairs_succeeding_is_reported_as_one_success(self):
        self.create_separate_pairs("A", "B")
        self.request("POST", "/api/sync", {"mode": "bisync"})
        result = self.wait_for_state({"succeeded", "failed"})
        self.assertEqual(result["state"], "succeeded")
        self.assertIn("All 2 folder pairs finished successfully", result["message"])
        self.assertIsNotNone(result["finished_at"])

    def test_every_pair_gets_its_own_first_time_setup(self):
        first, second = self.create_separate_pairs("A", "B")
        self.request("POST", "/api/sync", {"mode": "bisync", "resync": True})
        self.assertEqual(self.wait_for_state({"succeeded", "failed"})["state"], "succeeded")
        for name in ("A", "B"):
            self.assertTrue((self.workdir / name / "RCLONE_TEST").exists(), name)
        log = self.log_text()
        self.assertIn("onedrive:A/RCLONE_TEST", log)
        self.assertIn("onedrive:B/RCLONE_TEST", log)

    def test_a_result_is_forgotten_when_its_pair_is_edited(self):
        pair = self.create_separate_pairs("A")[0]
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"succeeded"})
        self.assertEqual(self.pairs_by_name()["A"]["state"], "succeeded")

        # Renaming does not change what was synced, so the result stays ...
        self.request("PUT", f"/api/pairs/{pair['id']}", self.pair_data("Renamed", local_path=pair["local_path"], remote=pair["remote"]))
        self.assertEqual(self.pairs_by_name()["Renamed"]["state"], "succeeded")
        # ... but a changed setup is a different pair as far as the result is concerned.
        self.request("PUT", f"/api/pairs/{pair['id']}", self.pair_data("Renamed", local_path=pair["local_path"], remote="onedrive:Other"))
        self.assertEqual(self.pairs_by_name()["Renamed"]["state"], "idle")


if __name__ == "__main__":
    unittest.main()
