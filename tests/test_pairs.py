"""!
@file test_pairs.py
@brief Unit tests for folder pairs: how pairs relate to each other and the store that keeps the list.

No server and no rclone are involved.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.errors import PairNotFoundError, SetupError
from backend.pair_relations import (
    RelationKind,
    automatic_exclusions,
    find_conflict,
    lies_inside,
    relate,
)
from backend.pairs import FolderPairStore
from backend.setup import PairSetup


def pair(local, remote):
    """!
    @brief Build a PairSetup from a local folder and a remote.
    @param local The local folder path.
    @param remote The remote folder, e.g. "onedrive:Docs".
    @return The new setup.
    """
    return PairSetup(local_path=local, remote=remote)


OUTER = pair("/data/docs", "onedrive:Docs")


class RelationTests(unittest.TestCase):
    """!
    @brief Tests for how two pair setups relate (same, nested, unrelated).

    A shared name PREFIX is not nesting. Nesting is detected both ways round, as the
    same relation seen from the inner pair. Sharing only the remote folder or only
    the local folder is a conflict too.
    """
    def kind(self, first, second):
        """!
        @brief Get the relation kind of two setups.
        @param first The first setup.
        @param second The second setup.
        @return The RelationKind of ``relate(first, second)``.
        """
        return relate(first, second).kind

    def test_unrelated_pairs_are_separate(self):
        self.assertIs(self.kind(OUTER, pair("/data/music", "onedrive:Music")), RelationKind.SEPARATE)
        self.assertIs(self.kind(OUTER, pair("/data/docs2", "onedrive:Docs2")), RelationKind.SEPARATE)

    def test_different_remotes_are_separate_clouds(self):
        self.assertIs(self.kind(pair("/a", "onedrive:"), pair("/b", "work:")), RelationKind.SEPARATE)

    def test_a_pair_with_an_unset_local_folder_relates_to_nothing(self):
        self.assertIs(self.kind(OUTER, pair("", "onedrive:Docs")), RelationKind.SEPARATE)
        self.assertIs(self.kind(pair("", "onedrive:"), pair("", "onedrive:")), RelationKind.SEPARATE)

    def test_the_same_folders_conflict(self):
        self.assertIs(self.kind(OUTER, pair("/data/docs/", "onedrive:docs")), RelationKind.CONFLICT)
        self.assertIn("same local folder", relate(OUTER, OUTER).reason)

    def test_nesting_at_the_same_position_is_nested(self):
        inner = pair("/data/docs/photos/2020", "onedrive:docs/Photos/2020")
        relation = relate(OUTER, inner)
        self.assertIs(relation.kind, RelationKind.NESTED)
        self.assertFalse(relation.first_is_inner)
        self.assertEqual(relation.inner_folder, ("photos", "2020"))
        self.assertTrue(relate(inner, OUTER).first_is_inner)

    def test_the_whole_drive_contains_every_folder(self):
        self.assertIs(self.kind(pair("/data", "onedrive:"), OUTER), RelationKind.NESTED)

    def test_a_different_position_on_each_side_conflicts(self):
        reason = find_conflict(OUTER, pair("/data/docs/photos", "onedrive:Docs/Pictures"))
        self.assertIn("Both must match", reason)

    def test_touching_on_one_side_only_conflicts(self):
        self.assertIn("remote folders overlap", find_conflict(OUTER, pair("/data/other", "onedrive:Docs")))
        self.assertIn("remote folders overlap", find_conflict(OUTER, pair("/data/other", "onedrive:Docs/Sub")))
        self.assertIn("local folders overlap", find_conflict(OUTER, pair("/data/docs", "onedrive:Other")))
        self.assertIn("local folders overlap", find_conflict(OUTER, pair("/data/docs/sub", "onedrive:Other")))

    def test_one_side_the_same_and_the_other_nested_conflicts(self):
        self.assertIsNotNone(find_conflict(OUTER, pair("/data/docs", "onedrive:Docs/Sub")))
        self.assertIsNotNone(find_conflict(OUTER, pair("/data/docs/sub", "onedrive:Docs")))

    def test_opposite_nesting_conflicts(self):
        self.assertIn("opposite directions", find_conflict(OUTER, pair("/data", "onedrive:Docs/Sub")))

    def test_trailing_slashes_dots_and_case_of_the_remote_are_ignored(self):
        inner = pair("/data/docs/../docs/photos/", "ONEDRIVE:Docs/PHOTOS".replace("ONEDRIVE", "onedrive"))
        self.assertIs(self.kind(OUTER, inner), RelationKind.NESTED)

    @unittest.skipIf(os.name == "nt", "symlinks need extra rights on Windows")
    def test_a_symlink_counts_as_the_folder_it_points_to(self):
        with tempfile.TemporaryDirectory() as folder:
            real = Path(folder) / "real"
            (real / "inside").mkdir(parents=True)
            link = Path(folder) / "link"
            link.symlink_to(real)
            self.assertIsNotNone(find_conflict(pair(str(link), "onedrive:A"), pair(str(real), "onedrive:A")))
            self.assertTrue(lies_inside(pair(str(real / "inside"), "onedrive:A/inside"), pair(str(link), "onedrive:A")))


class AutomaticExclusionTests(unittest.TestCase):
    """!
    @brief Tests for the exclusions an outer pair gets for its inner pairs.

    The top pair skips both inner folders (rclone would otherwise sync them), the
    middle one skips only the deepest.
    """
    def test_the_outer_pair_skips_each_inner_folder(self):
        others = [pair("/data/docs/photos", "onedrive:Docs/Photos"),
                  pair("/data/docs/work/old", "onedrive:docs/work/old"),
                  pair("/data/music", "onedrive:Music")]
        self.assertEqual(automatic_exclusions(OUTER, others), ("/photos/", "/work/old/"))

    def test_the_inner_pair_skips_nothing(self):
        inner = pair("/data/docs/photos", "onedrive:Docs/Photos")
        self.assertEqual(automatic_exclusions(inner, [OUTER]), ())

    def test_the_result_does_not_depend_on_the_order_of_the_pairs(self):
        a, b = pair("/data/docs/b", "onedrive:Docs/b"), pair("/data/docs/a", "onedrive:Docs/a")
        self.assertEqual(automatic_exclusions(OUTER, [a, b]), automatic_exclusions(OUTER, [b, a]))

    def test_special_characters_in_folder_names_are_escaped(self):
        inner = pair("/data/docs/a[1]*", "onedrive:Docs/a[1]*")
        self.assertEqual(automatic_exclusions(OUTER, [inner]), ("/a\\[1\\]\\*/",))

    def test_a_pair_in_the_middle_is_both_outer_and_inner(self):
        middle = pair("/data/docs/work", "onedrive:Docs/work")
        deepest = pair("/data/docs/work/old", "onedrive:Docs/work/old")
        self.assertEqual(automatic_exclusions(OUTER, [middle, deepest]), ("/work/", "/work/old/"))
        self.assertEqual(automatic_exclusions(middle, [OUTER, deepest]), ("/old/",))


class FolderPairStoreTests(unittest.TestCase):
    """!
    @brief Tests for the store that keeps the list of pairs in pairs.json.

    The tests cover create/read, validation, clashing folders (the error says WHICH
    pair it clashes with; a pair never clashes with itself, so keeping its own name
    when saving is fine), update/switch/delete, reading damaged files from disk
    (no name, invalid value, no remote chosen) and converting the single setup of
    older versions. That conversion is saved at once, so the id stays the same, and
    the old file is left alone.
    """
    def setUp(self):
        """!
        @brief Create a temporary folder and an empty store in it.
        """
        self._folder = tempfile.TemporaryDirectory()
        self.addCleanup(self._folder.cleanup)
        self.folder = Path(self._folder.name)
        self.pairs_file = self.folder / "pairs.json"
        self.store = self.new_store()

    def new_store(self):
        """!
        @brief Open a store on the test pairs file, as the app does at start-up.
        @return A new FolderPairStore.
        """
        return FolderPairStore(
            self.pairs_file,
            legacy_paths=[self.folder / "setup.json", self.folder / "settings.json"],
        )

    @staticmethod
    def data(name="Docs", **overrides):
        """!
        @brief Build the dictionary the UI sends for a new pair.
        @param name The pair name; also used for the folder names.
        @param overrides Fields that replace the defaults.
        @return The pair data.
        """
        data = {"name": name, "local_path": f"/data/{name}", "remote": f"onedrive:{name}"}
        data.update(overrides)
        return data

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

    def test_invalid_names_are_rejected(self):
        for bad in ("", "   ", "x" * 41, "two\nlines", None, 5):
            with self.assertRaises(SetupError, msg=repr(bad)):
                self.store.create(self.data(bad))
        self.assertEqual(self.store.all(), [])

    def test_names_must_be_unique_ignoring_case(self):
        first = self.store.create(self.data("Docs"))
        with self.assertRaises(SetupError):
            self.store.create(self.data("docs"))
        self.store.update(first.id, self.data("DOCS"))

    def test_invalid_setup_values_are_rejected(self):
        for bad in ({"max_size": "huge"}, {"remote": "nocolon"}, {"local_path": "relative/path"}):
            with self.assertRaises(SetupError, msg=str(bad)):
                self.store.create(self.data(**bad))

    def test_clashing_pairs_are_refused_and_nested_ones_are_fine(self):
        self.store.create(self.data("Docs"))
        for clash in (self.data("Same", local_path="/data/Docs", remote="onedrive:Docs"),
                      self.data("Other local", local_path="/data/elsewhere", remote="onedrive:Docs"),
                      self.data("Other remote", local_path="/data/Docs", remote="onedrive:elsewhere"),
                      self.data("Shifted", local_path="/data/Docs/a", remote="onedrive:Docs/b")):
            with self.assertRaises(SetupError, msg=clash["name"]) as caught:
                self.store.create(clash)
            self.assertIn("'Docs'", str(caught.exception))
        self.assertEqual([pair.name for pair in self.store.all()], ["Docs"])

        self.store.create(self.data("Inner", local_path="/data/Docs/a", remote="onedrive:Docs/a"))
        self.assertEqual(len(self.store.all()), 2)

    def test_an_update_may_not_clash_but_may_keep_its_own_folders(self):
        first = self.store.create(self.data("A"))
        second = self.store.create(self.data("B"))
        self.store.update(first.id, self.data("A", max_size="2G"))
        with self.assertRaises(SetupError):
            self.store.update(second.id, self.data("B", local_path="/data/A", remote="onedrive:A"))
        self.assertEqual(self.store.get(second.id).setup.local_path, "/data/B")

    def test_switched_off_pairs_still_count(self):
        first = self.store.create(self.data("A"))
        self.store.set_enabled(first.id, False)
        with self.assertRaises(SetupError):
            self.store.create(self.data("B", local_path="/data/A", remote="onedrive:A"))

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
        keep = self.store.create(self.data("Keep"))
        gone = self.store.create(self.data("Gone"))
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

    def test_broken_entries_are_skipped_not_fatal(self):
        self.pairs_file.write_text(json.dumps({"pairs": [
            {"id": "aaaa1111", "name": "Good", "local_path": "/data/docs", "remote": "mycloud:"},
            {"id": "bbbb2222", "name": "", "local_path": "/data/x", "remote": "mycloud:x"},
            {"id": "cccc3333", "name": "Bad size", "remote": "mycloud:y", "max_size": "huge"},
            {"id": "dddd4444", "name": "No remote", "local_path": "/data/z"},
            "not an object",
        ]}))
        self.assertEqual([pair.name for pair in self.new_store().all()], ["Good"])

    def test_an_unreadable_file_means_no_pairs(self):
        self.pairs_file.write_text("this is not json")
        self.assertEqual(self.new_store().all(), [])

    def test_missing_or_duplicate_ids_are_replaced(self):
        self.pairs_file.write_text(json.dumps({"pairs": [
            {"id": "same", "name": "One", "remote": "mycloud:One"},
            {"id": "same", "name": "Two", "remote": "mycloud:Two"},
            {"name": "Three", "remote": "mycloud:Three"},
        ]}))
        ids = [pair.id for pair in self.new_store().all()]
        self.assertEqual(len(set(ids)), 3)
        self.assertEqual(ids[0], "same")

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
