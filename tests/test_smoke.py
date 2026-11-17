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
                    {"max_size": "huge"}, {"remote": ""}, {"remote": "nocolon"}, {"remote": "C:"},
                    {"local_path": "relative/path"}, {"exclusions": ["#comment"]}):
            status, body = self.request("POST", "/api/pairs", self.pair_data(**bad))
            self.assertEqual(status, 400, bad)
            self.assertIn("error", body)
        self.assertEqual(self.pairs_by_name(), {})   # nothing was created

    def test_a_missing_remote_asks_the_user_to_choose_one(self):
        status, body = self.request("POST", "/api/pairs", self.pair_data(remote=""))
        self.assertEqual(status, 400)
        self.assertIn("Choose a remote", body["error"])

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
        self.assertEqual(defaults["remote"], "")       # no cloud is preselected: the user picks one
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
            self.assertEqual(pair["skips_pairs"], [])
        self.assertEqual(status["pairs"][0]["remote"], "onedrive:A")

    def test_a_pair_inside_another_one_is_named_in_the_outer_pairs_status(self):
        self.create_pair("Outer", local_path=str(self.local_dir), remote="onedrive:Docs")
        inner_dir = self.local_dir / "Photos"
        inner_dir.mkdir()
        inner = self.create_pair("Inner", local_path=str(inner_dir), remote="onedrive:Docs/Photos")

        pairs = self.pairs_by_name()
        self.assertEqual(pairs["Outer"]["skips_pairs"], ["Inner"])
        self.assertEqual(pairs["Inner"]["skips_pairs"], [])

        # Switching the inner pair off does not change that: its folder is still not the outer pair's job.
        self.request("PUT", f"/api/pairs/{inner['id']}/enabled", {"enabled": False})
        self.assertEqual(self.pairs_by_name()["Outer"]["skips_pairs"], ["Inner"])

    def test_pairs_with_clashing_folders_are_refused(self):
        self.create_pair("Docs", local_path=str(self.local_dir), remote="onedrive:Docs")
        for clash in (
            {"local_path": str(self.local_dir), "remote": "onedrive:Docs"},                # identical
            {"local_path": str(self.make_folder("other")), "remote": "onedrive:Docs"},     # same remote folder
            {"local_path": str(self.local_dir), "remote": "onedrive:Other"},               # same local folder
        ):
            status, body = self.request("POST", "/api/pairs", self.pair_data("Clash", **clash))
            self.assertEqual(status, 400, clash)
            self.assertIn("clash with the folder pair 'Docs'", body["error"])
        self.assertEqual(list(self.pairs_by_name()), ["Docs"])


class RemoteListTests(ServerTestCase):
    """The remotes rclone knows, which the setup form offers in its dropdown."""

    def use_fake_remotes(self, remotes="", fail=False):
        """Set what the fake rclone answers to ``listremotes`` (restored after the test)."""
        for name, value in (("FAKE_RCLONE_REMOTES", remotes or None),
                            ("FAKE_RCLONE_REMOTES_FAIL", "1" if fail else None)):
            self.addCleanup(os.environ.pop, name, None)
            if value is not None:
                os.environ[name] = value

    def test_lists_the_remotes_with_their_types(self):
        status, body = self.request("GET", "/api/remotes")
        self.assertEqual(status, 200)
        self.assertEqual(body["error"], "")
        self.assertEqual(
            body["remotes"],
            [{"name": "onedrive", "type": "onedrive"}, {"name": "icloud", "type": "iclouddrive"}],
        )

    def test_remotes_added_later_show_up_without_a_restart(self):
        self.use_fake_remotes("work:drive,home:s3,backup:crypt")
        _, body = self.request("GET", "/api/remotes")
        self.assertEqual([remote["name"] for remote in body["remotes"]], ["work", "home", "backup"])

    def test_no_remotes_is_an_empty_list_not_an_error(self):
        self.use_fake_remotes(remotes=",")   # rclone answers, but has nothing configured
        status, body = self.request("GET", "/api/remotes")
        self.assertEqual((status, body), (200, {"remotes": [], "error": ""}))

    def test_a_failing_rclone_is_reported_in_the_answer(self):
        self.use_fake_remotes(fail=True)
        status, body = self.request("GET", "/api/remotes")
        self.assertEqual(status, 200)                       # the form must keep working
        self.assertEqual(body["remotes"], [])
        self.assertIn("permission denied", body["error"])

    def test_a_missing_rclone_is_reported_in_the_answer(self):
        from backend.command.rclone import RcloneCommandBuilder
        from backend.command.remotes import RemoteCatalog
        listing = RemoteCatalog(RcloneCommandBuilder("definitely-not-installed-rclone")).list_remotes()
        self.assertEqual(listing.remotes, ())
        self.assertIn("rclone installed", listing.error)

    def test_the_localhost_guard_covers_the_remote_list(self):
        status, _ = self.request("GET", "/api/remotes", headers={"Host": "evil.com"})
        self.assertEqual(status, 403)

    def test_parsing_understands_padded_and_unpadded_lines(self):
        from backend.command.remotes import RemoteInfo, parse_remote_listing
        output = "onedrive:    onedrive\nmy drive: drive\n\nWARNING no colon here\nbare:\n"
        self.assertEqual(
            parse_remote_listing(output),
            (RemoteInfo("onedrive", "onedrive"), RemoteInfo("my drive", "drive"), RemoteInfo("bare", "")),
        )


class ExpiredLoginTests(ServerTestCase):
    """Remotes whose login has expired are noticed and the user is told how to reconnect."""

    def expire(self, *remotes):
        """Make the fake rclone fail like an expired login for these remotes (restored after the test)."""
        self.addCleanup(os.environ.pop, "FAKE_RCLONE_EXPIRED", None)
        os.environ["FAKE_RCLONE_EXPIRED"] = ",".join(remotes)

    def renew(self):
        os.environ.pop("FAKE_RCLONE_EXPIRED", None)

    def health(self):
        _, status = self.request("GET", "/api/status")
        return status["remote_health"]

    def run_check(self):
        """Press 'check again' and wait until the check is over."""
        status, _ = self.request("POST", "/api/remotes/check")
        self.assertEqual(status, 202)
        deadline = time.time() + 10
        while time.time() < deadline:
            health = self.health()
            if not health["checking"] and health["checked_at"] is not None:
                return health
            time.sleep(0.05)
        self.fail("The check did not finish")

    def test_nothing_is_flagged_when_all_logins_work(self):
        self.create_pair("Cloud", remote="icloud:Docs")
        health = self.run_check()
        self.assertEqual(health["expired"], [])

    def test_a_check_flags_an_expired_login_and_suggests_reconnecting(self):
        self.create_pair("Cloud", remote="icloud:Docs")
        self.expire("icloud")
        health = self.run_check()
        self.assertEqual([item["name"] for item in health["expired"]], ["icloud"])
        item = health["expired"][0]
        self.assertEqual(item["command"], "rclone config reconnect icloud:")
        self.assertEqual(item["source"], "check")
        self.assertIn("Invalid Session Token", item["reason"])

    def test_reconnecting_clears_the_flag_on_the_next_check(self):
        self.create_pair("Cloud", remote="icloud:Docs")
        self.expire("icloud")
        self.assertEqual(len(self.run_check()["expired"]), 1)
        self.renew()
        self.assertEqual(self.run_check()["expired"], [])

    def test_only_the_expired_remote_is_flagged(self):
        self.create_separate_pairs("Photos")
        self.create_pair("Cloud", remote="icloud:Docs", local_path=str(self.make_folder("cloud")))
        self.expire("icloud")
        names = [item["name"] for item in self.run_check()["expired"]]
        self.assertEqual(names, ["icloud"])

    def test_a_switched_off_pair_is_not_checked_or_reported(self):
        pair = self.create_pair("Cloud", remote="icloud:Docs")
        self.request("PUT", f"/api/pairs/{pair['id']}/enabled", {"enabled": False})
        self.expire("icloud")
        self.assertEqual(self.run_check()["expired"], [])

    def test_a_deleted_pair_takes_its_warning_with_it(self):
        pair = self.create_pair("Cloud", remote="icloud:Docs")
        self.expire("icloud")
        self.assertEqual(len(self.run_check()["expired"]), 1)
        self.request("DELETE", f"/api/pairs/{pair['id']}")
        self.assertEqual(self.health()["expired"], [])

    def test_a_failed_run_names_the_expired_login_and_flags_it(self):
        self.create_pair("Cloud", remote="icloud:Docs")
        self.expire("icloud")
        self.request("POST", "/api/sync", {"mode": "bisync", "resync": False})
        status = self.wait_for_state({"failed"})
        self.assertIn("rclone config reconnect icloud:", status["message"])
        self.assertIn("rclone config reconnect icloud:", status["pairs"][0]["message"])
        expired = status["remote_health"]["expired"]
        self.assertEqual([(item["name"], item["source"]) for item in expired], [("icloud", "run")])

    def test_a_successful_run_clears_the_flag(self):
        self.create_pair("Cloud", remote="icloud:Docs")
        self.expire("icloud")
        self.request("POST", "/api/sync", {"mode": "bisync", "resync": False})
        self.wait_for_state({"failed"})
        self.renew()
        self.request("POST", "/api/sync", {"mode": "bisync", "resync": False})
        status = self.wait_for_state({"succeeded"})
        self.assertEqual(status["remote_health"]["expired"], [])

    def test_a_run_with_several_pairs_names_every_expired_remote(self):
        self.create_pair("Cloud", remote="icloud:Docs", local_path=str(self.make_folder("cloud")))
        self.create_separate_pairs("Photos")
        self.expire("icloud")
        self.request("POST", "/api/sync", {"mode": "bisync", "resync": False})
        status = self.wait_for_state({"failed"})
        self.assertIn("1 of 2 folder pairs failed", status["message"])
        self.assertIn("rclone config reconnect icloud:", status["message"])
        self.assertNotIn("onedrive:", status["message"])

    def test_the_check_endpoint_is_guarded_like_the_rest(self):
        status, _ = self.request("POST", "/api/remotes/check", headers={"Host": "evil.com"})
        self.assertEqual(status, 403)

    def test_known_messages_are_recognised(self):
        from backend.remote_health import find_expired_login_line
        expired = [
            'HTTP error 400 (400 Bad Request) returned body:"{\\"success\\":false,\\"error\\":\\"Invalid Session Token\\"}"',
            "Failed: Missing X-APPLE-WEBAUTH-TOKEN cookie",
            "couldn't fetch token - maybe it has expired? - refresh with \"rclone config reconnect onedrive:\"",
            "oauth2: cannot fetch token: 400 Bad Request: invalid_grant",
        ]
        for line in expired:
            self.assertIsNotNone(find_expired_login_line(line), line)

    def test_ordinary_errors_are_not_mistaken_for_an_expired_login(self):
        from backend.remote_health import find_expired_login_line
        ordinary = [
            "dial tcp: lookup www.icloud.com: no such host",
            "Failed to copy: file name too long",
            "Bisync critical error: path1 and path2 are out of sync, must run --resync",
            "NOTICE: Config file not found",
            "",
        ]
        for line in ordinary:
            self.assertIsNone(find_expired_login_line(line), line)

    def test_remote_names_and_commands(self):
        from backend.remote_health import reconnect_command, remote_name_of
        self.assertEqual(remote_name_of("icloud:Docs/Work"), "icloud")
        self.assertEqual(remote_name_of("icloud:"), "icloud")
        self.assertEqual(reconnect_command("icloud"), "rclone config reconnect icloud:")


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
        # Path1 = local, Path2 = the remote; the remote (path2) wins conflicts.
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
        self.assertIn(f"ARGS: sync onedrive: {self.local_dir}", log)   # the remote is the source
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
        self.assertIn("--resync --resync-mode path2", log)             # the remote wins on baseline

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

    def nested_pairs(self):
        """'Outer' with 'Inner' (a folder inside it, at the same spot on the remote) and a separate pair."""
        outer_dir = self.make_folder("outer")
        inner_dir = outer_dir / "inner"
        inner_dir.mkdir()
        outer = self.create_pair("Outer", local_path=str(outer_dir), remote="onedrive:Shared")
        inner = self.create_pair("Inner", local_path=str(inner_dir), remote="onedrive:Shared/inner")
        return outer, inner

    def filter_file(self, pair):
        return (self.workdir / "data" / "filters" / f"{pair['id']}.txt").read_text()

    def test_a_pair_inside_another_one_is_synced_by_itself_only(self):
        os.environ["FAKE_RCLONE_MODE"] = "slow"
        outer, inner = self.nested_pairs()
        self.request("POST", "/api/sync", {"mode": "bisync"})

        # No waiting: both run at the same time, because they no longer touch the same files.
        pairs = self.wait_for_pairs(lambda pairs: all(pair["state"] == "running" for pair in pairs.values()))
        self.assertEqual(len(pairs), 2)

        self.assertIn("- /inner/", self.filter_file(outer))        # the outer pair leaves the folder out ...
        self.assertNotIn("/inner/", self.filter_file(inner))       # ... the inner pair does not
        self.assertIn("- *.tmp", self.filter_file(outer))          # the user's own exclusions stay
        self.assertTrue(any(entry["source"] == "Outer" and "Skipping /inner/" in entry["text"]
                            for entry in self.log_entries()))

        self.request("POST", "/api/stop")
        self.wait_for_state({"cancelled"})

    def test_a_switched_off_inner_pair_is_still_left_out_of_the_outer_pair(self):
        outer, inner = self.nested_pairs()
        self.request("PUT", f"/api/pairs/{inner['id']}/enabled", {"enabled": False})
        self.request("POST", "/api/sync", {"mode": "bisync"})
        result = self.wait_for_state({"succeeded", "failed"})

        states = {pair["name"]: pair["state"] for pair in result["pairs"]}
        self.assertEqual(states, {"Outer": "succeeded", "Inner": "idle"})
        # The outer pair's filters do not depend on the switch (bisync would demand a new first-time setup).
        self.assertIn("- /inner/", self.filter_file(outer))

    def test_the_filters_of_a_pair_do_not_change_between_runs(self):
        outer, _inner = self.nested_pairs()
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"succeeded"})
        first = self.filter_file(outer)
        self.request("POST", "/api/sync", {"mode": "bisync"})
        self.wait_for_state({"succeeded"})
        self.assertEqual(self.filter_file(outer), first)

    def test_a_run_refuses_clashing_pairs_that_were_edited_in_by_hand(self):
        from backend.pairs import FolderPair
        self.create_pair("Docs", local_path=str(self.local_dir), remote="onedrive:Docs")
        # The store would refuse this pair, so it is slipped in the way an edited pairs.json would.
        store = self.app.sync_manager._pair_store
        store._pairs.append(FolderPair.from_dict(
            self.pair_data("Hand made", local_path=str(self.make_folder("other")), remote="onedrive:Docs"),
            pair_id="hand",
        ))
        status, body = self.request("POST", "/api/sync", {"mode": "bisync"})
        self.assertEqual(status, 400)
        self.assertIn("'Docs' and 'Hand made' clash", body["error"])

        # Switching one of them off is the way out.
        self.request("PUT", "/api/pairs/hand/enabled", {"enabled": False})
        self.assertEqual(self.request("POST", "/api/sync", {"mode": "bisync"})[0], 202)
        self.wait_for_state({"succeeded", "failed"})

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
