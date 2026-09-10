"""Tests for the filesystem wrapper that records write and removal order."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pegasus.ports.filesystem import FileSystem
from recording_filesystem import RecordingFileSystem


class RecordingFileSystemTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.fs = RecordingFileSystem()

    def test_it_satisfies_the_port(self):
        self.assertIsInstance(self.fs, FileSystem)

    def test_a_write_reaches_real_disk(self):
        target = self.root / "note.txt"
        self.fs.write_atomic(target, b"hello")
        self.assertEqual(target.read_bytes(), b"hello")

    def test_writes_are_recorded_in_call_order(self):
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        self.fs.write_atomic(second, b"second")
        self.fs.write_atomic(first, b"first")
        self.assertEqual(self.fs.writes, [second, first])

    def test_removals_are_recorded_in_call_order_and_reach_real_disk(self):
        first = self.root / "first.txt"
        second = self.root / "second.txt"
        first.write_bytes(b"")
        second.write_bytes(b"")
        self.fs.remove(second)
        self.fs.remove(first)
        self.assertEqual(self.fs.removals, [second, first])
        self.assertFalse(first.exists() or second.exists())

    def test_is_symlink_reaches_real_disk(self):
        destination = self.root / "destination"
        destination.mkdir()
        link = self.root / "link"
        link.symlink_to(destination)
        self.assertTrue(self.fs.is_symlink(link))
        self.assertFalse(self.fs.is_symlink(destination))

    def test_remove_empty_dir_is_recorded_and_reaches_real_disk(self):
        target = self.root / "empty"
        target.mkdir()
        self.assertTrue(self.fs.remove_empty_dir(target))
        self.assertFalse(target.exists())
        self.assertEqual(self.fs.removals, [target])

    def test_remove_empty_dir_order_is_recorded_alongside_other_removals(self):
        first = self.root / "first"
        second = self.root / "second.txt"
        first.mkdir()
        second.write_bytes(b"")
        self.fs.remove(second)
        self.fs.remove_empty_dir(first)
        self.assertEqual(self.fs.removals, [second, first])


if __name__ == "__main__":
    unittest.main()
