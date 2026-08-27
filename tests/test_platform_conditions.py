"""Tests proving each platform condition is real, not merely plausible."""
from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path

from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.ports.filesystem import FileSystemError
from platform_conditions import (
    fail_next_removal_once,
    fail_next_write_once,
    fail_probe_once_it_exists,
    make_undeletable,
    make_unreadable,
    make_unwritable,
)


@unittest.skipIf(os.geteuid() == 0, "root is not refused by permission bits")
class PlatformConditionsTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fs = PosixFileSystem()
        self.pristine_replace = os.replace

    def test_make_unreadable_blocks_reading_a_file(self):
        target = self.root / "note.txt"
        target.write_bytes(b"secret")
        self.addCleanup(make_unreadable(target))
        with self.assertRaises(FileSystemError):
            self.fs.read_bytes(target)

    def test_make_unreadable_restores_the_exact_mode_it_found(self):
        """Not merely a readable one: a restore that widened a private file
        would leave the test green and the file exposed."""
        target = self.root / "note.txt"
        target.write_bytes(b"secret")
        target.chmod(0o600)
        restore = make_unreadable(target)
        restore()
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_make_unwritable_blocks_a_new_file_written_into_the_directory(self):
        target = self.root / "locked"
        target.mkdir()
        self.addCleanup(make_unwritable(target))
        with self.assertRaises(FileSystemError):
            self.fs.write_atomic(target / "note.txt", b"hello")

    def test_make_undeletable_blocks_removing_the_file(self):
        target = self.root / "holder" / "note.txt"
        target.parent.mkdir()
        target.write_bytes(b"hello")
        self.addCleanup(make_undeletable(target))
        with self.assertRaises(FileSystemError):
            self.fs.remove(target)

    def test_fail_next_write_once_fails_the_first_write_and_lets_the_second_through(self):
        target = self.root / "note.txt"
        self.addCleanup(fail_next_write_once(target))
        with self.assertRaises(FileSystemError):
            self.fs.write_atomic(target, b"first")
        self.fs.write_atomic(target, b"second")
        self.assertEqual(target.read_bytes(), b"second")

    def test_fail_next_removal_once_fails_the_first_removal_and_lets_the_second_through(self):
        target = self.root / "note.txt"
        target.write_bytes(b"hello")
        self.addCleanup(fail_next_removal_once(target))
        with self.assertRaises(FileSystemError):
            self.fs.remove(target)
        self.fs.remove(target)
        self.assertFalse(target.exists())

    def test_fail_probe_once_it_exists_lets_the_first_absence_through(self):
        target = self.root / "note.txt"
        self.addCleanup(fail_probe_once_it_exists(target))
        self.assertFalse(self.fs.exists(target))

    def test_fail_probe_once_it_exists_fails_once_the_path_is_really_there(self):
        target = self.root / "note.txt"
        target.write_bytes(b"hello")
        self.addCleanup(fail_probe_once_it_exists(target))
        with self.assertRaises(FileSystemError):
            self.fs.exists(target)

    def test_fail_probe_once_it_exists_keeps_failing_and_is_not_spent_by_the_first_probe(self):
        """The condition is the state of the disk, not a turn in a queue.

        A version that fired once and then stood down would pass every other
        test here, and would move the failure somewhere else the moment an
        unrelated probe was added upstream of the one under test. Asking
        twice is what tells the two implementations apart.
        """
        target = self.root / "note.txt"
        target.write_bytes(b"hello")
        self.addCleanup(fail_probe_once_it_exists(target))
        with self.assertRaises(FileSystemError):
            self.fs.exists(target)
        with self.assertRaises(FileSystemError):
            self.fs.exists(target)

    def test_undoing_two_conditions_in_reverse_leaves_the_system_call_pristine(self):
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        restore_first = fail_next_write_once(first)
        restore_second = fail_next_write_once(second)
        restore_second()
        restore_first()
        self.assertIs(os.replace, self.pristine_replace)

    def test_undoing_two_conditions_out_of_order_is_refused_instead_of_leaking(self):
        """The failure lands on the test that caused it, not on a later one.

        Restoring the inner condition first would discard the outer patch and
        then put the inner one back, leaving the system call replaced for
        every test that ran afterwards — a green suite with one unrelated
        test failing much later.
        """
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        restore_first = fail_next_write_once(first)
        restore_second = fail_next_write_once(second)
        with self.assertRaises(RuntimeError):
            restore_first()
        restore_second()
        restore_first()
        self.assertIs(os.replace, self.pristine_replace)


if __name__ == "__main__":
    unittest.main()
