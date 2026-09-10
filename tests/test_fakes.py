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


class FakeFileSystemIsWritableTest(unittest.TestCase):
    def test_a_path_not_named_unwritable_is_writable_by_default(self):
        filesystem = FakeFileSystem()
        self.assertTrue(filesystem.is_writable(ROOT / "pegasus"))

    def test_a_path_named_unwritable_answers_false(self):
        target = ROOT / "pegasus"
        filesystem = FakeFileSystem(unwritable={target})
        self.assertFalse(filesystem.is_writable(target))


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

    def test_make_dir_reports_every_directory_it_actually_created(self):
        """Mirrors `PosixFileSystemTest`'s own version of this: the fake must
        report the same thing the real filesystem does, since a caller that
        relies on this to know what it may later take back cannot afford the
        two disagreeing. `ROOT` is created first, the same way the real
        test's tempdir already exists before the call under test, so what is
        asserted is exactly the *new* directories this one call made."""
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT, mode=0o755)
        target = ROOT / "a" / "b" / "c"
        created = filesystem.make_dir(target, mode=0o700)
        self.assertEqual(created, (ROOT / "a", ROOT / "a" / "b", target))

    def test_make_dir_reports_nothing_when_the_directory_already_existed(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT, mode=0o755)
        self.assertEqual(filesystem.make_dir(ROOT, mode=0o700), ())

    def test_make_dir_reports_only_the_missing_ancestors_not_the_ones_already_there(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT / "existing", mode=0o755)
        target = ROOT / "existing" / "new-child" / "leaf"
        created = filesystem.make_dir(target)
        self.assertEqual(created, (ROOT / "existing" / "new-child", target))


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


class FakeFileSystemIsSymlinkTest(unittest.TestCase):
    def test_a_path_not_named_a_symlink_is_not_one(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT / "plain")
        self.assertFalse(filesystem.is_symlink(ROOT / "plain"))

    def test_an_absent_path_is_not_a_symlink(self):
        filesystem = FakeFileSystem()
        self.assertFalse(filesystem.is_symlink(ROOT / "absent"))

    def test_a_path_named_in_symlinks_is_one(self):
        target = ROOT / "link"
        filesystem = FakeFileSystem(symlinks={target})
        self.assertTrue(filesystem.is_symlink(target))

    def test_fail_is_symlink_makes_the_call_raise(self):
        target = ROOT / "mystery"
        filesystem = FakeFileSystem(fail_is_symlink={target})
        with self.assertRaises(FileSystemError):
            filesystem.is_symlink(target)


class FakeFileSystemRemoveEmptyDirTest(unittest.TestCase):
    def test_removes_an_empty_directory_and_reports_it_gone(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT / "empty")
        self.assertTrue(filesystem.remove_empty_dir(ROOT / "empty"))
        self.assertNotIn(ROOT / "empty", filesystem.directories)

    def test_an_already_absent_directory_reports_gone_without_error(self):
        filesystem = FakeFileSystem()
        self.assertTrue(filesystem.remove_empty_dir(ROOT / "absent"))

    def test_a_directory_holding_a_file_reports_false_and_removes_nothing(self):
        filesystem = FakeFileSystem()
        filesystem.write_atomic(ROOT / "occupied" / "note.txt", b"hello")
        self.assertFalse(filesystem.remove_empty_dir(ROOT / "occupied"))
        self.assertIn(ROOT / "occupied" / "note.txt", filesystem.files)
        self.assertIn(ROOT / "occupied", filesystem.directories)

    def test_a_directory_holding_an_empty_subdirectory_reports_false(self):
        filesystem = FakeFileSystem()
        filesystem.make_dir(ROOT / "parent" / "child")
        self.assertFalse(filesystem.remove_empty_dir(ROOT / "parent"))
        self.assertIn(ROOT / "parent", filesystem.directories)

    def test_a_file_target_raises_rather_than_answering_false(self):
        filesystem = FakeFileSystem(files={ROOT / "note.txt": b"payload"})
        with self.assertRaises(FileSystemError):
            filesystem.remove_empty_dir(ROOT / "note.txt")
        self.assertIn(ROOT / "note.txt", filesystem.files)

    def test_fail_remove_empty_dir_makes_the_call_raise(self):
        target = ROOT / "empty"
        filesystem = FakeFileSystem(fail_remove_empty_dir={target})
        filesystem.make_dir(target)
        with self.assertRaises(FileSystemError):
            filesystem.remove_empty_dir(target)
        self.assertIn(target, filesystem.directories)

    def test_a_symlink_raises_rather_than_answering_true(self):
        """The mirror of `PosixFileSystemTest.test_remove_empty_dir_on_a_symlink_raises_the_port_error`:
        the real `os.rmdir` never follows a symlink, even one pointing at a
        directory, and reports `ENOTDIR` -- translated by the real
        implementation into `FileSystemError`, the same way a plain file
        already is here. The double used to skip `self.symlinks` entirely for
        this call, so a path it declared a symlink silently answered `True`
        instead -- claiming a removal that never happened, and a caller
        (`_prune_empty_directories`) that trusted it could tell a symlinked
        ancestor apart from a genuinely gone directory only against the real
        filesystem, never against this one."""
        target = ROOT / "link"
        filesystem = FakeFileSystem(symlinks={target})
        with self.assertRaises(FileSystemError):
            filesystem.remove_empty_dir(target)
        self.assertIn(target, filesystem.symlinks)


if __name__ == "__main__":
    unittest.main()
