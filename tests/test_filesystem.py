"""The filesystem port and its POSIX implementation.

These tests exercise a real directory on purpose. Atomic writing is a claim about
what the operating system does, and a fake cannot falsify it.
"""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.ports.filesystem import FileSystem, FileSystemError


class PosixFileSystemTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fs = PosixFileSystem()

    def leftovers(self, folder: Path) -> list[str]:
        return sorted(item.name for item in folder.iterdir() if item.name.startswith("."))

    # --- The port ---

    def test_the_posix_implementation_satisfies_the_port(self):
        self.assertIsInstance(self.fs, FileSystem)

    # --- Writing ---

    def test_write_atomic_creates_the_file_with_its_content(self):
        target = self.root / "note.txt"
        self.fs.write_atomic(target, b"hello")
        self.assertEqual(target.read_bytes(), b"hello")

    def test_write_atomic_creates_missing_parent_directories(self):
        target = self.root / "deep" / "nested" / "note.txt"
        self.fs.write_atomic(target, b"hello")
        self.assertEqual(target.read_bytes(), b"hello")

    def test_write_atomic_applies_the_requested_mode(self):
        target = self.root / "private.txt"
        self.fs.write_atomic(target, b"secret", mode=0o600)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_write_atomic_replaces_existing_content(self):
        target = self.root / "note.txt"
        self.fs.write_atomic(target, b"first")
        self.fs.write_atomic(target, b"second")
        self.assertEqual(target.read_bytes(), b"second")

    def test_write_atomic_leaves_no_partial_file_behind(self):
        self.fs.write_atomic(self.root / "note.txt", b"hello")
        self.assertEqual(self.leftovers(self.root), [])

    def test_a_failed_replace_preserves_the_previous_content(self):
        """Atomic means the reader sees the old file or the new one, never a stump."""
        target = self.root / "note.txt"
        self.fs.write_atomic(target, b"first")

        def explode(*args, **kwargs):
            raise OSError("no space left on device")

        original = os.replace
        os.replace = explode
        try:
            with self.assertRaises(FileSystemError):
                self.fs.write_atomic(target, b"second")
        finally:
            os.replace = original

        self.assertEqual(target.read_bytes(), b"first")
        self.assertEqual(self.leftovers(self.root), [])

    def test_writing_over_a_directory_raises_the_port_error(self):
        target = self.root / "occupied"
        target.mkdir()
        with self.assertRaises(FileSystemError):
            self.fs.write_atomic(target, b"hello")

    # --- Reading ---

    def test_read_bytes_returns_what_was_written(self):
        target = self.root / "note.txt"
        target.write_bytes(b"hello")
        self.assertEqual(self.fs.read_bytes(target), b"hello")

    def test_reading_a_missing_file_raises_the_port_error(self):
        with self.assertRaises(FileSystemError):
            self.fs.read_bytes(self.root / "absent.txt")

    def test_exists_reports_files_and_directories(self):
        (self.root / "note.txt").write_bytes(b"")
        self.assertTrue(self.fs.exists(self.root / "note.txt"))
        self.assertTrue(self.fs.exists(self.root))
        self.assertFalse(self.fs.exists(self.root / "absent.txt"))

    # --- Removing ---

    def test_remove_deletes_the_file(self):
        target = self.root / "note.txt"
        target.write_bytes(b"hello")
        self.fs.remove(target)
        self.assertFalse(target.exists())

    def test_removing_an_absent_file_is_not_an_error(self):
        """Retiring an artifact the user already deleted is success, not failure."""
        self.fs.remove(self.root / "absent.txt")

    def test_removing_a_directory_raises_the_port_error(self):
        target = self.root / "folder"
        target.mkdir()
        with self.assertRaises(FileSystemError):
            self.fs.remove(target)

    # --- Directories ---

    def test_make_dir_creates_the_whole_chain(self):
        target = self.root / "one" / "two" / "three"
        self.fs.make_dir(target)
        self.assertTrue(target.is_dir())

    def test_make_dir_applies_the_requested_mode(self):
        target = self.root / "private"
        self.fs.make_dir(target, mode=0o700)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)

    def test_make_dir_is_idempotent(self):
        target = self.root / "folder"
        self.fs.make_dir(target)
        self.fs.make_dir(target)
        self.assertTrue(target.is_dir())

    def test_make_dir_does_not_change_the_mode_of_a_directory_that_already_exists(self):
        """The mode applies on creation only. A caller asking for 0700 on an
        existing directory gets whatever it already had, and hardening it would
        mean mutating something this installation did not create."""
        target = self.root / "inherited"
        target.mkdir(mode=0o755)
        self.fs.make_dir(target, mode=0o700)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o755)

    def test_make_dir_over_a_file_raises_the_port_error(self):
        target = self.root / "note.txt"
        target.write_bytes(b"")
        with self.assertRaises(FileSystemError):
            self.fs.make_dir(target)

    def test_mode_of_reports_the_permission_bits(self):
        target = self.root / "note.txt"
        target.write_bytes(b"")
        target.chmod(0o640)
        self.assertEqual(self.fs.mode_of(target), 0o640)

    def test_mode_of_a_missing_path_is_none(self):
        self.assertIsNone(self.fs.mode_of(self.root / "absent.txt"))

    def test_a_users_file_keeps_its_permissions_when_rewritten_with_its_own_mode(self):
        """Writing into a configuration file must not change who can read it."""
        target = self.root / "settings.json"
        target.write_bytes(b"{}")
        target.chmod(0o600)
        self.fs.write_atomic(target, b'{"a": 1}', mode=self.fs.mode_of(target))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    # --- Who is running ---

    def test_a_directory_this_process_created_is_owned_by_this_user(self):
        self.assertTrue(self.fs.owned_by_current_user(self.root))

    def test_ownership_of_a_missing_path_is_false_rather_than_an_error(self):
        self.assertFalse(self.fs.owned_by_current_user(self.root / "absent"))

    def test_running_privileged_answers_for_the_current_process(self):
        self.assertEqual(self.fs.running_privileged(), os.geteuid() == 0)


if __name__ == "__main__":
    unittest.main()
