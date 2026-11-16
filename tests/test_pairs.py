"""
Unit tests for folder pairs: the overlap rules and the store that keeps the list.
No server and no rclone are involved.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.errors import PairNotFoundError, SetupError          # noqa: E402
from backend.pairs import FolderPairStore                          # noqa: E402
from backend.path_overlap import (                                 # noqa: E402
    local_paths_overlap,
    remote_paths_overlap,
    setups_overlap,
)
from backend.setup import PairSetup                                # noqa: E402


class LocalOverlapTests(unittest.TestCase):
    def test_same_and_nested_folders_overlap(self):
        self.assertTrue(local_paths_overlap("/data/docs", "/data/docs"))
        self.assertTrue(local_paths_overlap("/data/docs", "/data/docs/work"))
        self.assertTrue(local_paths_overlap("/data/docs/work", "/data/docs"))
        self.assertTrue(local_paths_overlap("/", "/data/docs"))

    def test_siblings_do_not_overlap_even_with_a_shared_name_prefix(self):
        self.assertFalse(local_paths_overlap("/data/docs", "/data/docs2"))
        self.assertFalse(local_paths_overlap("/data/docs", "/data/pictures"))

    def test_trailing_slash_and_dots_are_ignored(self):
        self.assertTrue(local_paths_overlap("/data/docs/", "/data/docs"))
        self.assertTrue(local_paths_overlap("/data/docs/../docs", "/data/docs"))

    def test_an_unset_folder_overlaps_with_nothing(self):
        self.assertFalse(local_paths_overlap("", "/data/docs"))
        self.assertFalse(local_paths_overlap("", ""))

    @unittest.skipIf(os.name == "nt", "symlinks need extra rights on Windows")
    def test_a_symlink_counts_as_the_folder_it_points_to(self):
        with tempfile.TemporaryDirectory() as folder:
            real = Path(folder) / "real"
            real.mkdir()
            link = Path(folder) / "link"
            link.symlink_to(real)
            self.assertTrue(local_paths_overlap(str(link), str(real / "inside")))


class RemoteOverlapTests(unittest.TestCase):
    def test_whole_drive_overlaps_with_every_folder_on_it(self):
        self.assertTrue(remote_paths_overlap("onedrive:", "onedrive:Docs"))
        self.assertTrue(remote_paths_overlap("onedrive:", "onedrive:"))

    def test_nested_folders_overlap_and_case_is_ignored(self):
        self.assertTrue(remote_paths_overlap("onedrive:Docs", "onedrive:docs/Work"))
        self.assertTrue(remote_paths_overlap("onedrive:/Docs/", "onedrive:Docs"))

    def test_siblings_do_not_overlap(self):
        self.assertFalse(remote_paths_overlap("onedrive:Docs", "onedrive:Docs2"))
        self.assertFalse(remote_paths_overlap("onedrive:Docs", "onedrive:Photos"))

    def test_different_remotes_never_overlap(self):
        self.assertFalse(remote_paths_overlap("onedrive:", "work:"))


class SetupsOverlapTests(unittest.TestCase):
    def test_pairs_overlap_when_either_side_does(self):
        base = PairSetup(local_path="/a", remote="onedrive:A")
        same_remote_folder = PairSetup(local_path="/b", remote="onedrive:A/Sub")
        same_local_folder = PairSetup(local_path="/a/inner", remote="onedrive:B")
        unrelated = PairSetup(local_path="/c", remote="onedrive:C")

        self.assertTrue(setups_overlap(base, same_remote_folder))
        self.assertTrue(setups_overlap(base, same_local_folder))
        self.assertFalse(setups_overlap(base, unrelated))


class FolderPairStoreTests(unittest.TestCase):
    def setUp(self):
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.folder = Path(self._folder.name)
        self.pairs_file = self.folder / "pairs.json"
        self.store = self.new_store()

    def new_store(self):
        return FolderPairStore(
            self.pairs_file,
            legacy_paths=[self.folder / "setup.json", self.folder / "settings.json"],
        )

    @staticmethod
    def data(name="Docs", **overrides):
        data = {"name": name, "local_path": "/data/docs", "remote": "onedrive:Docs"}
        data.update(overrides)
        return data

    # --- create / read ---

    def test_a_new_store_is_empty_and_writes_nothing(self):
        self.assertEqual(self.store.all(), [])
        self.assertFalse(self.pairs_file.exists())

    def test_create_gives_an_id_and_is_active_by_default(self):
        pair = self.store.create(self.data())
        self.assertTrue(pair.id)
        self.assertTrue(pair.enabled)
        self.assertEqual(self.store.get(pair.id), pair)
        self.assertEqual([item.name for item in self.store.all()], ["Docs"])

    def test_pairs_keep_the_order_they_were_created_in(self):
        for name in ("B", "A", "C"):
            self.store.create(self.data(name))
        self.assertEqual([pair.name for pair in self.store.all()], ["B", "A", "C"])

    def test_pairs_survive_a_restart(self):
        pair = self.store.create(self.data(exclusions=["*.iso"]))
        self.store.set_enabled(pair.id, False)

        reloaded = self.new_store().get(pair.id)
        self.assertEqual(reloaded.name, "Docs")
        self.assertEqual(reloaded.setup.exclusions, ("*.iso",))
        self.assertFalse(reloaded.enabled)

    # --- validation ---

    def test_invalid_names_are_rejected(self):
        for bad in ("", "   ", "x" * 41, "two\nlines", None, 5):
            with self.assertRaises(SetupError, msg=repr(bad)):
                self.store.create(self.data(bad))
        self.assertEqual(self.store.all(), [])

    def test_names_must_be_unique_ignoring_case(self):
        first = self.store.create(self.data("Docs"))
        with self.assertRaises(SetupError):
            self.store.create(self.data("docs"))
        # Keeping its own name when saving is of course fine.
        self.store.update(first.id, self.data("DOCS"))

    def test_invalid_setup_values_are_rejected(self):
        for bad in ({"max_size": "huge"}, {"remote": "nocolon"}, {"local_path": "relative/path"}):
            with self.assertRaises(SetupError, msg=str(bad)):
                self.store.create(self.data(**bad))

    # --- update / switch / delete ---

    def test_update_keeps_id_and_switch(self):
        pair = self.store.create(self.data())
        self.store.set_enabled(pair.id, False)

        updated = self.store.update(pair.id, self.data("Renamed", max_size="2G"))
        self.assertEqual(updated.id, pair.id)
        self.assertFalse(updated.enabled)
        self.assertEqual(updated.name, "Renamed")
        self.assertEqual(updated.setup.max_size, "2G")

    def test_a_failed_update_changes_nothing(self):
        pair = self.store.create(self.data())
        with self.assertRaises(SetupError):
            self.store.update(pair.id, self.data("Docs", max_size="huge"))
        self.assertEqual(self.store.get(pair.id), pair)

    def test_enabled_must_be_a_boolean(self):
        pair = self.store.create(self.data())
        for bad in ("yes", 1, None):
            with self.assertRaises(SetupError, msg=repr(bad)):
                self.store.set_enabled(pair.id, bad)

    def test_delete(self):
        keep = self.store.create(self.data("Keep", remote="onedrive:Keep"))
        gone = self.store.create(self.data("Gone", remote="onedrive:Gone"))
        self.store.delete(gone.id)
        self.assertEqual(self.store.all(), [keep])
        self.assertEqual(self.new_store().all(), [keep])

    def test_unknown_ids_raise_not_found(self):
        for action in (
            lambda: self.store.get("nope"),
            lambda: self.store.update("nope", self.data()),
            lambda: self.store.set_enabled("nope", True),
            lambda: self.store.delete("nope"),
        ):
            with self.assertRaises(PairNotFoundError):
                action()

    # --- reading files from disk ---

    def test_broken_entries_are_skipped_not_fatal(self):
        self.pairs_file.write_text(json.dumps({"pairs": [
            {"id": "aaaa1111", "name": "Good", "local_path": "/data/docs"},
            {"id": "bbbb2222", "name": "", "local_path": "/data/x"},          # no name
            {"id": "cccc3333", "name": "Bad size", "max_size": "huge"},       # invalid value
            "not an object",
        ]}))
        self.assertEqual([pair.name for pair in self.new_store().all()], ["Good"])

    def test_an_unreadable_file_means_no_pairs(self):
        self.pairs_file.write_text("this is not json")
        self.assertEqual(self.new_store().all(), [])

    def test_missing_or_duplicate_ids_are_replaced(self):
        self.pairs_file.write_text(json.dumps({"pairs": [
            {"id": "same", "name": "One"},
            {"id": "same", "name": "Two"},
            {"name": "Three"},
        ]}))
        ids = [pair.id for pair in self.new_store().all()]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids[0], "same")

    # --- converting the single setup of older versions ---

    def test_an_old_setup_file_becomes_the_first_pair(self):
        old_file = self.folder / "setup.json"
        old_file.write_text(json.dumps({
            "local_path": "/data/docs", "remote": "mycloud:", "max_size": "1G", "exclusions": ["*.iso"],
        }))

        store = self.new_store()
        (pair,) = store.all()
        self.assertEqual(pair.name, "Folder pair 1")
        self.assertEqual(pair.setup.remote, "mycloud:")
        self.assertEqual(pair.setup.exclusions, ("*.iso",))
        self.assertTrue(pair.enabled)

        # The conversion is saved at once (so the id stays the same) and the old file is left alone.
        self.assertTrue(self.pairs_file.exists())
        self.assertTrue(old_file.exists())
        self.assertEqual(self.new_store().all(), [pair])

    def test_the_even_older_settings_file_is_read_too(self):
        (self.folder / "settings.json").write_text(json.dumps({"remote": "mycloud:", "max_size": "1G"}))
        (pair,) = self.new_store().all()
        self.assertEqual(pair.setup.remote, "mycloud:")

    def test_the_pairs_file_wins_over_old_files(self):
        (self.folder / "setup.json").write_text(json.dumps({"remote": "mycloud:"}))
        self.store.create(self.data("Docs"))
        self.assertEqual([pair.name for pair in self.new_store().all()], ["Docs"])


if __name__ == "__main__":
    unittest.main()
