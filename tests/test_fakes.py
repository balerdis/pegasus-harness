"""The in-memory filesystem double's own contract.

Every store test that asserts on a directory's mode leans on
:class:`FakeFileSystem` to record what it was told honestly. These tests pin
that the double's ``make_dir`` behaves like the real filesystem's additive
contract: a directory that already exists keeps its mode, and parents created
along the way get the default rather than the mode that was asked for.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from pegasus.ports.filesystem import FileSystemError
from fakes import DEFAULT_DIR_MODE, DEFAULT_MODE, FakeFileSystem

ROOT = Path("/home/probe")


class FakeFileSystemMakeDirTest(unittest.TestCase):
    def test_make_dir_records_the_requested_mode(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT, mode=0o700)
        self.assertEqual(filesystem.mode_of(ROOT), 0o700)

    def test_make_dir_creates_the_whole_chain(self):
        filesystem = FakeFileSystem()
        target = ROOT / "a" / "b" / "c"
        filesystem.make_dir(target, mode=0o700)
        self.assertIn(ROOT, filesystem.directories)
        self.assertIn(ROOT / "a", filesystem.directories)
        self.assertIn(ROOT / "a" / "b", filesystem.directories)
        self.assertIn(target, filesystem.directories)

    def test_make_dir_applies_the_requested_mode_only_to_the_leaf(self):
        filesystem = FakeFileSystem()
        target = ROOT / "a" / "b" / "c"
        filesystem.make_dir(target, mode=0o700)
        self.assertEqual(filesystem.mode_of(target), 0o700)
        self.assertEqual(filesystem.mode_of(ROOT), DEFAULT_DIR_MODE)
        self.assertEqual(filesystem.mode_of(ROOT / "a"), DEFAULT_DIR_MODE)
        self.assertEqual(filesystem.mode_of(ROOT / "a" / "b"), DEFAULT_DIR_MODE)

    def test_make_dir_does_not_change_the_mode_of_a_directory_that_already_exists(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT, mode=0o755)
        filesystem.make_dir(ROOT, mode=0o700)
        self.assertEqual(filesystem.mode_of(ROOT), 0o755)

    def test_make_dir_does_not_widen_a_parent_created_by_an_earlier_call(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT / "a", mode=0o700)
        filesystem.make_dir(ROOT / "a" / "b", mode=0o700)
        self.assertEqual(filesystem.mode_of(ROOT / "a"), 0o700)
        self.assertEqual(filesystem.mode_of(ROOT / "a" / "b"), 0o700)

    def test_write_atomic_creates_the_parent_chain_at_the_default_mode(self):
        """Mirrors fs_posix.write_atomic, which creates missing parents itself."""
        filesystem = FakeFileSystem()
        target = ROOT / "a" / "b" / "note.txt"
        filesystem.write_atomic(target, b"hello")
        self.assertIn(target.parent, filesystem.directories)
        self.assertEqual(filesystem.mode_of(target.parent), DEFAULT_DIR_MODE)
        self.assertEqual(filesystem.mode_of(ROOT / "a"), DEFAULT_DIR_MODE)

    def test_write_atomic_does_not_widen_a_directory_made_explicitly_first(self):
        filesystem = FakeFileSystem()
        target = ROOT / "note.txt"
        filesystem.make_dir(ROOT, mode=0o700)
        filesystem.write_atomic(target, b"hello")
        self.assertEqual(filesystem.mode_of(ROOT), 0o700)


class FakeFileSystemModeForTest(unittest.TestCase):
    def test_an_executable_artifact_gets_a_program_mode(self):
        self.assertEqual(FakeFileSystem().mode_for(executable=True), 0o755)

    def test_a_non_executable_artifact_gets_the_default_mode(self):
        self.assertEqual(FakeFileSystem().mode_for(executable=False), DEFAULT_MODE)


class FakeFileSystemFailExistsTest(unittest.TestCase):
    """`exists` needed a failure hook before the data-loss scenario it caused
    could be written as a test at all — without one, "cannot tell" was
    literally inconstructible on the double."""

    def test_fail_exists_makes_the_next_call_raise(self):
        filesystem = FakeFileSystem(fail_exists={ROOT / "note.txt"})
        with self.assertRaises(FileSystemError):
            filesystem.exists(ROOT / "note.txt")

    def test_fail_exists_does_not_affect_other_paths(self):
        filesystem = FakeFileSystem(
            files={ROOT / "other.txt": b"hello"}, fail_exists={ROOT / "note.txt"}
        )
        self.assertTrue(filesystem.exists(ROOT / "other.txt"))


class FakeFileSystemMakeDirRemoveDirTest(unittest.TestCase):
    def test_remove_dir_refuses_a_path_that_is_a_file(self):
        """Mirrors fs_posix.remove_dir, where rmtree on a file raises.

        A double that quietly deletes the file instead would let a caller that
        aimed remove_dir at the wrong kind of path pass its tests and destroy
        data in production. The double is only useful while it fails where the
        real one fails.
        """
        filesystem = FakeFileSystem(files={ROOT / "note.txt": b"payload"})
        with self.assertRaises(FileSystemError):
            filesystem.remove_dir(ROOT / "note.txt")
        self.assertIn(ROOT / "note.txt", filesystem.files)


if __name__ == "__main__":
    unittest.main()
