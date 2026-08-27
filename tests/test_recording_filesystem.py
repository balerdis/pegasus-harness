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


if __name__ == "__main__":
    unittest.main()
