"""Persisting the ownership journal.

The store is the only thing between a correct journal and a home directory
Pegasus can no longer retire from cleanly, so its refusals matter as much as its
writes. Everything here runs against a fake filesystem: the store's job is
policy, and the port already proves the writing.
"""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from fakes import FakeFileSystem
from pegasus.core import journal as journal_module
from pegasus.core.journal import Install, Record
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import FileJournalStore, journal_path
from pegasus.ports.filesystem import FileSystemError
from pegasus.ports.journal_store import JournalStore, JournalStoreError

HOME = Path("/home/probe")
CONFIG = HOME / ".config" / "some-cli"
AT = "2026-08-14T00:00:00+00:00"
VERSION = "4.0.0"


def install() -> Install:
    return Install(
        cli="some-cli",
        installed_at=AT,
        config_dir=CONFIG,
        release={"version": VERSION, "content_digest": "sha256:" + "c" * 64},
        entries=(
            Record(
                id="skill:alpha",
                kind="file",
                target=CONFIG / "skills/alpha/SKILL.md",
                after_digest="sha256:" + "a" * 64,
                created_at=AT,
                mode="0644",
            ),
        ),
    )


def store(filesystem: FakeFileSystem) -> FileJournalStore:
    return FileJournalStore(filesystem, home=HOME, pegasus_version=VERSION)


class JournalPathTest(unittest.TestCase):
    def test_the_path_is_pure_arithmetic_on_the_home(self):
        self.assertEqual(
            journal_path(Path("/nonexistent/pegasus-probe")),
            Path("/nonexistent/pegasus-probe/.local/share/pegasus-harness/journal-v4.json"),
        )

    def test_the_v4_journal_does_not_share_a_name_with_the_v3_one(self):
        """v4 is a clean install next to v3, not a rewrite of its state."""
        self.assertNotIn("journal-v3", journal_path(HOME).name)


class FileJournalStoreTest(unittest.TestCase):
    def test_the_file_store_satisfies_the_port(self):
        self.assertIsInstance(store(FakeFileSystem()), JournalStore)

    # --- Loading ---

    def test_loading_without_a_file_yields_an_empty_journal(self):
        loaded = store(FakeFileSystem()).load()
        self.assertEqual(loaded, journal_module.empty(VERSION))

    def test_loading_does_not_create_the_file(self):
        filesystem = FakeFileSystem()
        store(filesystem).load()
        self.assertEqual(filesystem.files, {})

    def test_a_saved_journal_loads_back_unchanged(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        original = journal_module.with_install(journal_module.empty(VERSION), install())
        subject.save(original)
        self.assertEqual(subject.load(), original)

    def test_unreadable_json_is_refused_rather_than_treated_as_empty(self):
        """Silently starting over would orphan everything already installed."""
        filesystem = FakeFileSystem(files={journal_path(HOME): b"{ not json"})
        with self.assertRaises(JournalStoreError):
            store(filesystem).load()

    def test_a_journal_the_core_rejects_is_refused(self):
        payload = json.dumps({"schema": "pegasus-harness/journal/v3", "pegasus_version": VERSION}).encode("utf-8")
        filesystem = FakeFileSystem(files={journal_path(HOME): payload})
        with self.assertRaises(JournalStoreError):
            store(filesystem).load()

    def test_a_journal_holding_a_target_outside_the_home_is_refused(self):
        """The core enforces containment; the store must not swallow that refusal."""
        payload = json.loads(json.dumps(journal_module.to_dict(
            journal_module.with_install(journal_module.empty(VERSION), install())
        )))
        payload["installs"][0]["entries"][0]["target"] = "/etc/passwd"
        filesystem = FakeFileSystem(files={journal_path(HOME): json.dumps(payload).encode("utf-8")})
        with self.assertRaises(JournalStoreError):
            store(filesystem).load()

    def test_a_filesystem_failure_while_reading_surfaces_as_a_store_error(self):
        class Unreadable(FakeFileSystem):
            def exists(self, path: Path) -> bool:
                return True

            def read_bytes(self, path: Path) -> bytes:
                raise FileSystemError("permission denied")

        with self.assertRaises(JournalStoreError):
            store(Unreadable()).load()

    # --- Saving ---

    def test_saving_writes_to_the_journal_path(self):
        filesystem = FakeFileSystem()
        store(filesystem).save(journal_module.empty(VERSION))
        self.assertIn(journal_path(HOME), filesystem.files)

    def test_saving_keeps_the_journal_private_to_its_owner(self):
        filesystem = FakeFileSystem()
        store(filesystem).save(journal_module.empty(VERSION))
        self.assertEqual(filesystem.modes[journal_path(HOME)], 0o600)

    def test_saving_creates_the_data_directory_first(self):
        filesystem = FakeFileSystem()
        store(filesystem).save(journal_module.empty(VERSION))
        self.assertIn(journal_path(HOME).parent, filesystem.directories)

    def test_the_written_file_is_readable_json_ending_in_a_newline(self):
        filesystem = FakeFileSystem()
        store(filesystem).save(journal_module.with_install(journal_module.empty(VERSION), install()))
        written = filesystem.files[journal_path(HOME)].decode("utf-8")
        self.assertTrue(written.endswith("\n"))
        self.assertEqual(json.loads(written)["schema"], journal_module.SCHEMA)

    def test_root_must_not_write_the_journal(self):
        filesystem = FakeFileSystem(privileged=True)
        with self.assertRaises(JournalStoreError):
            store(filesystem).save(journal_module.empty(VERSION))
        self.assertEqual(filesystem.files, {})

    def test_a_home_owned_by_someone_else_must_not_be_written_to(self):
        filesystem = FakeFileSystem(owner=False)
        with self.assertRaises(JournalStoreError):
            store(filesystem).save(journal_module.empty(VERSION))
        self.assertEqual(filesystem.files, {})

    def test_a_filesystem_failure_while_writing_surfaces_as_a_store_error(self):
        class Unwritable(FakeFileSystem):
            def write_atomic(self, path: Path, content: bytes, *, mode: int = 0o644) -> None:
                raise FileSystemError("no space left on device")

        with self.assertRaises(JournalStoreError):
            store(Unwritable()).save(journal_module.empty(VERSION))

    def test_a_journal_recording_a_target_outside_the_home_is_never_written(self):
        """Containment is checked on the way out too, not only on the way in."""
        outside = Install(
            cli="some-cli",
            installed_at=AT,
            config_dir=CONFIG,
            release={},
            entries=(
                Record(
                    id="skill:alpha",
                    kind="file",
                    target=Path("/etc/passwd"),
                    after_digest="sha256:" + "a" * 64,
                    created_at=AT,
                ),
            ),
        )
        filesystem = FakeFileSystem()
        with self.assertRaises(JournalStoreError):
            store(filesystem).save(journal_module.with_install(journal_module.empty(VERSION), outside))
        self.assertEqual(filesystem.files, {})

    def test_saving_twice_replaces_rather_than_appends(self):
        filesystem = FakeFileSystem()
        subject = store(filesystem)
        subject.save(journal_module.with_install(journal_module.empty(VERSION), install()))
        subject.save(journal_module.empty(VERSION))
        self.assertEqual(subject.load(), journal_module.empty(VERSION))


class FileJournalStoreOnRealDiskTest(unittest.TestCase):
    """The fake proves the policy; this proves the two halves actually compose."""

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("the store refuses to write as root, which is the behaviour under test elsewhere")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.store = FileJournalStore(PosixFileSystem(), home=self.home, pegasus_version=VERSION)

    def real_install(self) -> Install:
        config = self.home / ".config" / "some-cli"
        return Install(
            cli="some-cli",
            installed_at=AT,
            config_dir=config,
            release={"version": VERSION},
            entries=(
                Record(
                    id="skill:alpha",
                    kind="file",
                    target=config / "skills/alpha/SKILL.md",
                    after_digest="sha256:" + "a" * 64,
                    created_at=AT,
                    mode="0644",
                ),
            ),
        )

    def test_an_absent_journal_reads_as_empty_without_creating_anything(self):
        self.assertEqual(self.store.load(), journal_module.empty(VERSION))
        self.assertFalse(journal_path(self.home).exists())

    def test_a_journal_survives_a_round_trip_through_the_real_filesystem(self):
        original = journal_module.with_install(journal_module.empty(VERSION), self.real_install())
        self.store.save(original)
        self.assertEqual(self.store.load(), original)

    def test_the_stored_file_is_private_and_leaves_no_partial_behind(self):
        self.store.save(journal_module.empty(VERSION))
        stored = journal_path(self.home)
        self.assertEqual(stat.S_IMODE(stored.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(stored.parent.stat().st_mode), 0o700)
        self.assertEqual([item.name for item in stored.parent.iterdir()], [stored.name])


if __name__ == "__main__":
    unittest.main()
