"""Persisting per-agent model preferences.

Mirrors `test_journal_store.py`'s discipline for the sibling store: the
policy under test is the store's, not the filesystem's, so everything here
runs against a fake.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from fakes import FakeFileSystem
from pegasus.core import model_assignments as model_assignments_module
from pegasus.core.types import ModelAssignment
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.model_assignment_store_file import FileModelAssignmentStore, model_assignment_path
from pegasus.ports.filesystem import FileSystemError
from pegasus.ports.model_assignment_store import ModelAssignmentStore, ModelAssignmentStoreError

HOME = Path("/home/probe")
ASSIGNMENT = ModelAssignment(provider_id="anthropic", model_id="claude-sonnet-5", effort="high")


def store(filesystem: FakeFileSystem) -> FileModelAssignmentStore:
    return FileModelAssignmentStore(filesystem, home=HOME)


class ModelAssignmentPathTest(unittest.TestCase):
    def test_the_path_is_arithmetic_on_the_filesystems_own_data_dir(self):
        filesystem = FakeFileSystem()
        self.assertEqual(
            model_assignment_path(filesystem, HOME),
            filesystem.data_dir(HOME) / "model-assignments-v1.json",
        )

    def test_the_path_does_not_collide_with_the_journal(self):
        filesystem = FakeFileSystem()
        from pegasus.infra.journal_store_file import journal_path

        self.assertNotEqual(model_assignment_path(filesystem, HOME), journal_path(filesystem, HOME))


class FileModelAssignmentStoreTest(unittest.TestCase):
    def test_the_file_store_satisfies_the_port(self):
        self.assertIsInstance(store(FakeFileSystem()), ModelAssignmentStore)

    # --- Loading ---

    def test_loading_without_a_file_yields_an_empty_set(self):
        self.assertEqual(store(FakeFileSystem()).load(), model_assignments_module.empty())

    def test_loading_does_not_create_the_file(self):
        filesystem = FakeFileSystem()
        store(filesystem).load()
        self.assertEqual(filesystem.files, {})

    def test_a_saved_assignment_loads_back_unchanged(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        original = model_assignments_module.with_assignment(
            model_assignments_module.empty(), "opencode", "sdd-apply", ASSIGNMENT
        )
        subject.save(original)
        self.assertEqual(subject.load(), original)

    def test_unreadable_json_is_refused_rather_than_treated_as_empty(self):
        filesystem = FakeFileSystem(files={model_assignment_path(FakeFileSystem(), HOME): b"{ not json"})
        with self.assertRaises(ModelAssignmentStoreError):
            store(filesystem).load()

    def test_a_document_the_core_rejects_is_refused(self):
        payload = json.dumps({"schema": "wrong", "assignments": []}).encode("utf-8")
        filesystem = FakeFileSystem(files={model_assignment_path(FakeFileSystem(), HOME): payload})
        with self.assertRaises(ModelAssignmentStoreError):
            store(filesystem).load()

    def test_a_filesystem_failure_while_reading_surfaces_as_a_store_error(self):
        class Unreadable(FakeFileSystem):
            def exists(self, path: Path) -> bool:
                return True

            def read_bytes(self, path: Path) -> bytes:
                raise FileSystemError("permission denied")

        with self.assertRaises(ModelAssignmentStoreError):
            store(Unreadable()).load()

    # --- Saving ---

    def test_saving_writes_to_the_assignment_path(self):
        filesystem = FakeFileSystem()
        store(filesystem).save(model_assignments_module.empty())
        self.assertIn(model_assignment_path(FakeFileSystem(), HOME), filesystem.files)

    def test_saving_keeps_the_file_private_to_its_owner(self):
        filesystem = FakeFileSystem()
        store(filesystem).save(model_assignments_module.empty())
        self.assertEqual(filesystem.modes[model_assignment_path(FakeFileSystem(), HOME)], 0o600)

    def test_saving_creates_the_data_directory_with_the_journals_own_mode(self):
        filesystem = FakeFileSystem()
        store(filesystem).save(model_assignments_module.empty())
        path = model_assignment_path(FakeFileSystem(), HOME)
        self.assertIn(path.parent, filesystem.directories)
        self.assertEqual(filesystem.directory_modes[path.parent], 0o700)

    def test_the_written_file_is_readable_json_ending_in_a_newline(self):
        filesystem = FakeFileSystem()
        assignments = model_assignments_module.with_assignment(
            model_assignments_module.empty(), "opencode", "sdd-apply", ASSIGNMENT
        )
        store(filesystem).save(assignments)
        written = filesystem.files[model_assignment_path(FakeFileSystem(), HOME)].decode("utf-8")
        self.assertTrue(written.endswith("\n"))
        self.assertEqual(json.loads(written)["schema"], model_assignments_module.SCHEMA)

    def test_a_home_that_is_not_writable_on_behalf_of_its_owner_must_not_get_a_file(self):
        filesystem = FakeFileSystem(writable=False)
        with self.assertRaises(ModelAssignmentStoreError):
            store(filesystem).save(model_assignments_module.empty())
        self.assertEqual(filesystem.files, {})

    def test_a_filesystem_failure_while_writing_surfaces_as_a_store_error(self):
        class Unwritable(FakeFileSystem):
            def write_atomic(self, path: Path, content: bytes, *, mode: int = 0o644) -> None:
                raise FileSystemError("no space left on device")

        with self.assertRaises(ModelAssignmentStoreError):
            store(Unwritable()).save(model_assignments_module.empty())


class FileModelAssignmentStoreOnRealDiskTest(unittest.TestCase):
    """The fake proves the policy; this proves the two halves actually compose."""

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("the store refuses to write as root, which is the behaviour under test elsewhere")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.filesystem = PosixFileSystem(product_id="pegasus-harness")
        self.store = FileModelAssignmentStore(self.filesystem, home=self.home)

    def test_an_absent_file_reads_as_empty_without_creating_anything(self):
        self.assertEqual(self.store.load(), model_assignments_module.empty())
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())

    def test_assignments_survive_a_round_trip_through_the_real_filesystem(self):
        original = model_assignments_module.with_assignment(
            model_assignments_module.empty(), "opencode", "sdd-apply", ASSIGNMENT
        )
        self.store.save(original)
        self.assertEqual(self.store.load(), original)

    def test_the_stored_file_and_its_directory_are_private(self):
        self.store.save(model_assignments_module.empty())
        stored = model_assignment_path(self.filesystem, self.home)
        self.assertEqual(stat.S_IMODE(stored.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(stored.parent.stat().st_mode), 0o700)
