"""Persisting a snapshot generation.

Everything here runs against a fake filesystem: the store's job is policy —
numbering generations, writing blobs before the manifest, refusing the wrong
writer — and the port already proves the writing.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from fakes import FakeFileSystem
from pegasus.core.snapshot import Entry, Manifest, SnapshotError
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import DATA_DIR, DATA_DIR_MODE
from pegasus.infra.snapshot_store_file import (
    MANIFEST_FILENAME,
    FileSnapshotStore,
    capture_paths,
    snapshots_root,
)
from pegasus.ports.filesystem import FileSystemError
from pegasus.ports.snapshot_store import Capture, SnapshotStore, SnapshotStoreError

HOME = Path("/home/probe")
TARGET = HOME / ".config" / "some-cli" / "settings.json"
OTHER = HOME / ".config" / "some-cli" / "other.json"
AT = "2026-08-14T00:00:00+00:00"


def store(filesystem: FakeFileSystem) -> FileSnapshotStore:
    return FileSnapshotStore(filesystem, home=HOME)


def one_capture(**overrides) -> Capture:
    fields = dict(path=TARGET, existed=True, mode="0644", content=b"hand-edited")
    fields.update(overrides)
    return Capture(**fields)


class SnapshotsRootTest(unittest.TestCase):
    def test_the_root_hangs_off_the_same_directory_as_the_journal(self):
        """Derived from the journal's own location, not a restated literal."""
        self.assertEqual(snapshots_root(HOME), HOME / DATA_DIR / "snapshots")


class CapturePathsTest(unittest.TestCase):
    def test_a_file_that_cannot_be_read_fails_as_a_snapshot_failure(self):
        """Capturing is the snapshot's own job, so its failures wear its own name.

        A caller guarding a snapshot catches this store's error; letting the
        filesystem's own type through would slip past that guard and reach the
        user as a message about a file, with no word on whether the command it
        was protecting went ahead anyway.
        """

        class Unreadable(FakeFileSystem):
            def read_bytes(self, path: Path) -> bytes:
                raise FileSystemError(f"refusing to read {path}: injected failure")

        filesystem = Unreadable(files={TARGET: b"whatever"})
        with self.assertRaises(SnapshotStoreError):
            capture_paths(filesystem, [TARGET])

    def test_a_path_that_cannot_be_probed_fails_the_capture_rather_than_being_recorded_as_absent(self):
        """The acceptance test for the whole unit.

        Measured on real disk before this fix: a directory in mode 000 made
        `exists` swallow `EACCES` and answer `False`, so a snapshot recorded
        sixteen files that were actually there as ``existed=False``, and a
        later `restore` deleted all sixteen and reported `exit=0`. Capturing
        must refuse before writing a manifest that lies this way — not
        record the entry as absent, and not silently drop it either.
        """
        filesystem = FakeFileSystem(files={TARGET: b"still here"}, fail_exists={TARGET})
        with self.assertRaises(SnapshotStoreError):
            capture_paths(filesystem, [TARGET])


class FileSnapshotStoreTest(unittest.TestCase):
    def test_the_file_store_satisfies_the_port(self):
        self.assertIsInstance(store(FakeFileSystem()), SnapshotStore)

    # --- Writability ---

    def test_ensure_writable_passes_when_saving_would_work(self):
        store(FakeFileSystem()).ensure_writable()

    def test_ensure_writable_refuses_a_home_that_is_not_writable_on_behalf_of_its_owner(self):
        with self.assertRaises(SnapshotStoreError):
            store(FakeFileSystem(writable=False)).ensure_writable()

    def test_ensure_writable_writes_nothing_of_its_own(self):
        filesystem = FakeFileSystem()
        store(filesystem).ensure_writable()
        self.assertEqual(filesystem.writes, [])

    def test_saving_into_a_home_that_is_not_writable_on_behalf_of_its_owner_is_refused(self):
        filesystem = FakeFileSystem(writable=False)
        with self.assertRaises(SnapshotStoreError):
            store(filesystem).save([one_capture()], taken_at=AT)
        self.assertEqual(filesystem.files, {})

    # --- Numbering ---

    def test_the_first_generation_of_an_empty_store_is_one(self):
        self.assertEqual(store(FakeFileSystem()).save([one_capture()], taken_at=AT), 1)

    def test_the_next_generation_is_the_highest_existing_plus_one(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save([one_capture()], taken_at=AT)
        subject.save([one_capture()], taken_at=AT)
        self.assertEqual(subject.save([one_capture()], taken_at=AT), 3)

    def test_a_folder_without_a_manifest_still_takes_its_number_out_of_circulation(self):
        """Numbering counts folders, not manifests.

        A folder with no manifest is a save that died before it finished, and
        its bytes are still someone's file. Handing its number to the next save
        would write a fresh generation on top of a half-written one and mix two
        captures in a single folder, so a number is spent the moment a folder
        claims it. Reading still demands a manifest: an unfinished generation
        occupies its number without ever being restorable.
        """
        root = snapshots_root(HOME)
        filesystem = FakeFileSystem()
        filesystem.make_dir(root / "000001")
        filesystem.files[root / "000001" / "0001.blob"] = b"leftover"
        self.assertEqual(store(filesystem).save([one_capture()], taken_at=AT), 2)

    def test_a_folder_whose_name_is_not_a_plain_number_is_not_a_generation(self):
        """Numbering only recognises what this store itself would have written.

        Some characters are digits to `str.isdigit` and not to `int` — the
        superscript two among them — so trusting the first to guarantee the
        second turns a stray folder into a crash. Anything that is not a plain
        ASCII number is simply not one of ours, and is skipped the same way a
        folder called after a person would be.
        """
        filesystem = FakeFileSystem()
        filesystem.make_dir(snapshots_root(HOME) / "\u00b2")
        self.assertEqual(store(filesystem).save([one_capture()], taken_at=AT), 1)

    def test_a_root_that_cannot_be_listed_is_reported_as_a_store_failure(self):
        """A save that cannot count what is already there fails as this store's
        own error, never as the filesystem's: a caller that catches the store's
        error type would otherwise miss it entirely."""
        root = snapshots_root(HOME)
        filesystem = FakeFileSystem(fail_list={root})
        with self.assertRaises(SnapshotStoreError):
            store(filesystem).save([one_capture()], taken_at=AT)

    # --- Writing order and content ---

    def test_saving_writes_the_manifest_last(self):
        order: list[Path] = []

        class Recording(FakeFileSystem):
            def write_atomic(self, path: Path, content: bytes, *, mode: int = 0o644) -> None:
                order.append(path)
                super().write_atomic(path, content, mode=mode)

        store(Recording()).save([one_capture()], taken_at=AT)
        self.assertTrue(order)
        self.assertEqual(order[-1].name, "manifest.json")

    def test_saving_writes_a_blob_for_an_existing_file(self):
        filesystem = FakeFileSystem()
        generation = store(filesystem).save([one_capture(content=b"hand-edited")], taken_at=AT)
        folder = snapshots_root(HOME) / f"{generation:06d}"
        blobs = [content for path, content in filesystem.files.items() if path.parent == folder and path.suffix == ".blob"]
        self.assertIn(b"hand-edited", blobs)

    def test_saving_writes_no_blob_for_an_absent_file(self):
        filesystem = FakeFileSystem()
        generation = store(filesystem).save([one_capture(existed=False, mode=None, content=None)], taken_at=AT)
        folder = snapshots_root(HOME) / f"{generation:06d}"
        blobs = [path for path in filesystem.files if path.parent == folder and path.suffix == ".blob"]
        self.assertEqual(blobs, [])

    def test_saving_captures_the_journal_alongside_the_other_files(self):
        """The journal is just another address to the store; nothing special-cases it."""
        filesystem = FakeFileSystem()
        journal_capture = one_capture(path=HOME / DATA_DIR / "journal-v4.json", content=b"{}")
        generation = store(filesystem).save([one_capture(), journal_capture], taken_at=AT)
        manifest = store(filesystem).read(generation)
        paths = {entry.path for entry in manifest.entries}
        self.assertIn(journal_capture.path, paths)

    # --- Reading ---

    def test_reading_returns_what_was_saved(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        generation = subject.save([one_capture(), one_capture(path=OTHER, existed=False, mode=None, content=None)], taken_at=AT)
        manifest = subject.read(generation)
        self.assertIsInstance(manifest, Manifest)
        paths = {entry.path: entry for entry in manifest.entries}
        self.assertTrue(paths[TARGET].existed)
        self.assertFalse(paths[OTHER].existed)

    def test_reading_a_generation_that_does_not_exist_raises(self):
        with self.assertRaises(SnapshotStoreError):
            store(FakeFileSystem()).read(1)

    def test_reading_a_generation_whose_manifest_existence_cannot_be_told_raises(self):
        """`read`'s own `exists` call is unguarded, but it is called only from
        `restore`'s own `try/except SnapshotStoreError` in `cli.py`, and the
        raw `FileSystemError` this raises is still caught by `main`'s generic
        handler one level up — refusing cleanly, never proceeding as if the
        generation were simply missing."""
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        generation = subject.save([one_capture()], taken_at=AT)
        manifest_path = snapshots_root(HOME) / f"{generation:06d}" / MANIFEST_FILENAME
        filesystem.fail_exists.add(manifest_path)
        with self.assertRaises(FileSystemError):
            subject.read(generation)

    def test_reading_a_generation_with_a_corrupt_manifest_raises(self):
        filesystem = FakeFileSystem()
        folder = snapshots_root(HOME) / "000001"
        filesystem.make_dir(folder)
        filesystem.files[folder / "manifest.json"] = b"{ not json"
        with self.assertRaises(SnapshotStoreError):
            store(filesystem).read(1)

    def test_reading_a_generation_whose_manifest_is_structurally_invalid_raises(self):
        filesystem = FakeFileSystem()
        folder = snapshots_root(HOME) / "000001"
        filesystem.make_dir(folder)
        filesystem.files[folder / "manifest.json"] = json.dumps({"taken_at": ""}).encode("utf-8")
        with self.assertRaises(SnapshotStoreError):
            store(filesystem).read(1)

    # --- The asymmetric failure posture: the signature property of this store ---

    def test_a_corrupt_old_generation_does_not_prevent_writing_a_new_one(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        folder = snapshots_root(HOME) / "000001"
        filesystem.make_dir(folder)
        filesystem.files[folder / "manifest.json"] = b"{ not json"

        generation = subject.save([one_capture()], taken_at=AT)

        self.assertEqual(generation, 2)
        manifest = subject.read(generation)
        self.assertTrue(manifest.entries)

    def test_a_corrupt_old_generation_still_raises_when_read_directly(self):
        """Writing tolerates the damage; reading that generation back does not."""
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        folder = snapshots_root(HOME) / "000001"
        filesystem.make_dir(folder)
        filesystem.files[folder / "manifest.json"] = b"{ not json"

        subject.save([one_capture()], taken_at=AT)

        with self.assertRaises(SnapshotStoreError):
            subject.read(1)

    # --- Directory privacy ---

    def test_saving_creates_every_directory_level_at_the_journals_mode(self):
        """Whichever store creates the shared data directory first must leave it
        as private as the journal store does; the two must never disagree."""
        filesystem = FakeFileSystem()
        generation = store(filesystem).save([one_capture()], taken_at=AT)
        data_dir = HOME / DATA_DIR
        root = snapshots_root(HOME)
        folder = root / f"{generation:06d}"
        self.assertEqual(filesystem.mode_of(data_dir), DATA_DIR_MODE)
        self.assertEqual(filesystem.mode_of(root), DATA_DIR_MODE)
        self.assertEqual(filesystem.mode_of(folder), DATA_DIR_MODE)

    # --- Invalid captures ---

    def test_an_invalid_capture_is_refused_as_a_store_error(self):
        """A core validation failure must not leak past the store's own error type."""
        invalid = one_capture(existed=True, mode=None)
        with self.assertRaises(SnapshotStoreError):
            store(FakeFileSystem()).save([invalid], taken_at=AT)

    def test_a_capture_claiming_existence_without_content_is_refused(self):
        unread = one_capture(existed=True, content=None)
        filesystem = FakeFileSystem()
        with self.assertRaises(SnapshotStoreError):
            store(filesystem).save([unread], taken_at=AT)
        self.assertEqual(filesystem.files, {})


    # --- The generation-number reuse gap (pinned, not fixed) ---

    def test_a_dead_generation_keeps_its_bytes_and_never_shares_its_folder(self):
        """A save that died after its blobs and before its manifest stays put.

        Its folder still holds bytes that belonged to the user, so the next
        save must not write into it: sharing the folder would overwrite the
        blobs whose index the new capture happens to reuse and strand the rest
        alongside a manifest that never mentions them. Spending the number
        instead leaves the dead attempt whole and untouched, and costs only a
        gap in the sequence.
        """
        filesystem = FakeFileSystem()
        dead_folder = snapshots_root(HOME) / "000001"
        filesystem.make_dir(dead_folder)
        dead_blob_one = dead_folder / "0001.blob"
        dead_blob_two = dead_folder / "0002.blob"
        filesystem.files[dead_blob_one] = b"dead-attempt-file-one"
        filesystem.files[dead_blob_two] = b"dead-attempt-file-two"

        generation = store(filesystem).save([one_capture()], taken_at=AT)

        self.assertEqual(generation, 2)
        self.assertIn(snapshots_root(HOME) / "000002" / "manifest.json", filesystem.files)
        self.assertNotIn(dead_folder / "manifest.json", filesystem.files)
        self.assertEqual(filesystem.files[dead_blob_one], b"dead-attempt-file-one")
        self.assertEqual(filesystem.files[dead_blob_two], b"dead-attempt-file-two")

    def test_a_dead_generation_is_still_not_readable(self):
        """Spending its number does not make an unfinished generation real."""
        filesystem = FakeFileSystem()
        filesystem.make_dir(snapshots_root(HOME) / "000001")
        with self.assertRaises(SnapshotStoreError):
            store(filesystem).read(1)

    # --- Listing readable generations, for restore ---

    def test_readable_generations_lists_every_finished_generation_in_order(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save([one_capture()], taken_at=AT)
        subject.save([one_capture()], taken_at=AT)
        subject.save([one_capture()], taken_at=AT)
        self.assertEqual(subject.readable_generations(), [1, 2, 3])

    def test_readable_generations_excludes_a_folder_without_a_manifest(self):
        """An unfinished write holds its number but is not offered as readable."""
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save([one_capture()], taken_at=AT)
        filesystem.make_dir(snapshots_root(HOME) / "000002")
        self.assertEqual(subject.readable_generations(), [1])

    def test_readable_generations_is_empty_for_a_fresh_store(self):
        self.assertEqual(store(FakeFileSystem()).readable_generations(), [])

    def test_readable_generations_skips_a_generation_it_cannot_probe_and_still_finds_a_newer_one(self):
        """One old, unreadable generation folder must not make `restore`
        blind to every generation, including a good, newer one — that would
        be an availability regression stacked on top of the correctness bug
        `exists` used to have."""
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save([one_capture()], taken_at=AT)
        subject.save([one_capture()], taken_at=AT)
        unreadable_manifest = snapshots_root(HOME) / "000001" / MANIFEST_FILENAME
        filesystem.fail_exists.add(unreadable_manifest)

        self.assertEqual(subject.readable_generations(), [2])
        self.assertEqual(subject.most_recent_readable(), 2)

    def test_most_recent_readable_is_the_highest_readable_generation(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save([one_capture()], taken_at=AT)
        subject.save([one_capture()], taken_at=AT)
        self.assertEqual(subject.most_recent_readable(), 2)

    def test_most_recent_readable_skips_a_trailing_unfinished_generation(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save([one_capture()], taken_at=AT)
        filesystem.make_dir(snapshots_root(HOME) / "000002")
        self.assertEqual(subject.most_recent_readable(), 1)

    def test_most_recent_readable_is_none_for_a_fresh_store(self):
        self.assertIsNone(store(FakeFileSystem()).most_recent_readable())

    # --- Reading a blob back, for restore ---

    def test_read_blob_returns_the_bytes_written_for_that_entry(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        generation = subject.save([one_capture(content=b"hand-edited")], taken_at=AT)
        manifest = subject.read(generation)
        entry = manifest.entries[0]
        self.assertEqual(subject.read_blob(generation, entry.blob), b"hand-edited")

    def test_read_blob_of_a_missing_generation_raises_the_store_error(self):
        with self.assertRaises(SnapshotStoreError):
            store(FakeFileSystem()).read_blob(1, "0001.blob")

    # --- Retention ---

    def test_retain_removes_generations_beyond_the_kept_count(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        for _ in range(6):
            subject.save([one_capture()], taken_at=AT)

        outcome = subject.retain(keep=5)

        self.assertEqual(outcome.removed, (1,))
        self.assertEqual(outcome.failed, ())
        self.assertEqual(subject.readable_generations(), [2, 3, 4, 5, 6])

    def test_retain_deletes_the_folder_and_its_contents(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        for _ in range(6):
            subject.save([one_capture()], taken_at=AT)

        subject.retain(keep=5)

        folder = snapshots_root(HOME) / "000001"
        self.assertEqual(filesystem.list_dir(folder), [])
        self.assertFalse(filesystem.exists(folder))

    def test_retain_does_nothing_when_within_the_kept_count(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save([one_capture()], taken_at=AT)
        subject.save([one_capture()], taken_at=AT)

        outcome = subject.retain(keep=5)

        self.assertEqual(outcome.removed, ())
        self.assertEqual(subject.readable_generations(), [1, 2])

    def test_retain_run_twice_does_not_fail(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        for _ in range(6):
            subject.save([one_capture()], taken_at=AT)

        subject.retain(keep=5)
        second = subject.retain(keep=5)

        self.assertEqual(second.removed, ())
        self.assertEqual(second.failed, ())

    def test_a_retention_failure_is_reported_rather_than_raised(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        for _ in range(6):
            subject.save([one_capture()], taken_at=AT)
        filesystem.fail_remove_dir.add(snapshots_root(HOME) / "000001")

        outcome = subject.retain(keep=5)

        self.assertEqual(outcome.removed, ())
        self.assertEqual(len(outcome.failed), 1)
        # The generation survives: a failed retention is untidy, not destructive.
        self.assertIn(1, subject.readable_generations())


class FileSnapshotStoreOnRealDiskTest(unittest.TestCase):
    """The fake proves the policy; this proves the modes actually land on disk."""

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("the store refuses to write as root, which is the behaviour under test elsewhere")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.store = FileSnapshotStore(PosixFileSystem(), home=self.home)

    def test_every_directory_level_is_private_even_when_created_from_scratch(self):
        """The snapshot store is routinely the first thing to create the shared
        data directory on a fresh machine, so it alone must not leave it wide
        open while blobs are written underneath it."""
        generation = self.store.save([one_capture()], taken_at=AT)
        data_dir = self.home / DATA_DIR
        root = snapshots_root(self.home)
        folder = root / f"{generation:06d}"
        for created in (data_dir, root, folder):
            self.assertEqual(stat.S_IMODE(created.stat().st_mode), DATA_DIR_MODE, created)


if __name__ == "__main__":
    unittest.main()
