"""Installing the real content into a real directory, and taking it back out.

Everything else in this suite proves a decision. This proves the decisions
compose: the content core, an adapter, the planner, the POSIX filesystem and
the journal, run end to end against a temporary home with nothing faked.

It is the first test that would notice if the catalog and the journal disagreed
about a fingerprint, if an append were installed twice, or if uninstalling left
a home dirtier than it found it.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from pegasus.adapters import available
from pegasus.core import catalog as catalog_module
from pegasus.core import content as content_module
from pegasus.core import journal as journal_module
from pegasus.core import planner
from pegasus.core.types import Environment
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import FileJournalStore

AT = "2026-08-14T00:00:00+00:00"
VERSION = "4.0.0"


class InstallAndRetireTest(unittest.TestCase):
    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("Pegasus refuses to install as root, which is tested against the fake")
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.fs = PosixFileSystem()
        self.registry = available()
        self.cli = self.registry.ids()[0]
        self.adapter = self.registry.get(self.cli)
        self.environment = Environment(home=self.home)
        self.layout = self.adapter.layout(self.environment)
        self.artifacts = catalog_module.render(content_module.load(), self.adapter, self.environment)

    def install(self) -> planner.Applied:
        plan = planner.plan(self.fs, cli=self.cli, artifacts=self.artifacts)
        return planner.apply(self.fs, plan, at=AT)

    def files_under(self, root: Path) -> list[Path]:
        return sorted(path for path in root.rglob("*") if path.is_file())

    # --- Installing ---

    def test_an_empty_home_receives_every_artifact(self):
        plan = planner.plan(self.fs, cli=self.cli, artifacts=self.artifacts)
        self.assertEqual(len(plan.collisions), 0)
        self.assertEqual(len(plan.creations), len(self.artifacts))

    def test_installing_puts_the_files_on_disk(self):
        applied = self.install()
        self.assertEqual(len(applied.records), len(self.artifacts))
        self.assertTrue(self.files_under(self.layout.config_dir))

    def test_every_record_is_a_journal_the_core_accepts(self):
        applied = self.install()
        install = journal_module.Install(
            cli=self.cli,
            installed_at=AT,
            config_dir=self.layout.config_dir,
            release={"version": VERSION},
            entries=applied.records,
        )
        stored = journal_module.with_install(journal_module.empty(VERSION), install)
        store = FileJournalStore(self.fs, home=self.home, pegasus_version=VERSION)
        store.save(stored)
        self.assertEqual(store.load(), stored)

    def test_the_fingerprints_recorded_are_the_ones_the_catalog_publishes(self):
        """Catalog and journal must agree, or no uninstall ever recognises its own work."""
        applied = self.install()
        catalog = catalog_module.build(content_module.load(), self.adapter, self.environment)
        published = {entry.id: entry.digest for entry in catalog.entries}
        self.assertEqual({record.id: record.after_digest for record in applied.records}, published)

    def test_installing_twice_changes_nothing_the_second_time(self):
        """Every artifact is a collision the second time, including the appends."""
        self.install()
        before = {path: path.read_bytes() for path in self.files_under(self.layout.config_dir)}
        second = planner.plan(self.fs, cli=self.cli, artifacts=self.artifacts)
        self.assertEqual(len(second.creations), 0)
        applied = planner.apply(self.fs, second, at=AT)
        self.assertEqual(applied.records, ())
        self.assertEqual({path: path.read_bytes() for path in self.files_under(self.layout.config_dir)}, before)

    # --- Retiring ---

    def test_retiring_takes_back_everything_it_installed(self):
        applied = self.install()
        install = journal_module.Install(
            cli=self.cli, installed_at=AT, config_dir=self.layout.config_dir, release={}, entries=applied.records
        )
        retired = planner.retire(self.fs, install)
        self.assertEqual(len(retired.removed), len(applied.records))
        self.assertEqual(retired.preserved, ())

    def test_a_home_that_was_installed_and_retired_holds_nothing_of_ours(self):
        applied = self.install()
        install = journal_module.Install(
            cli=self.cli, installed_at=AT, config_dir=self.layout.config_dir, release={}, entries=applied.records
        )
        planner.retire(self.fs, install)
        leftovers = [path for path in self.files_under(self.layout.config_dir) if path.stat().st_size > 0]
        settings = self.layout.settings_file
        if settings is not None and settings.exists():
            leftovers = [path for path in leftovers if path != settings]
            self.assertEqual(settings.read_text(encoding="utf-8").strip(), "{}")
        self.assertEqual(leftovers, [])

    def test_a_file_the_user_edited_survives_the_uninstall(self):
        applied = self.install()
        edited = next(record for record in applied.records if record.kind == "file")
        edited.target.write_bytes(b"the user rewrote this")
        install = journal_module.Install(
            cli=self.cli, installed_at=AT, config_dir=self.layout.config_dir, release={}, entries=applied.records
        )
        retired = planner.retire(self.fs, install)
        self.assertIn(edited.id, retired.preserved)
        self.assertEqual(edited.target.read_bytes(), b"the user rewrote this")

    def test_a_key_the_user_added_survives_the_uninstall(self):
        settings = self.layout.settings_file
        if settings is None:
            self.skipTest("this adapter has no settings file")
        applied = self.install()
        document = settings.read_text(encoding="utf-8")
        settings.write_text(document.replace("{", '{\n  "theirs": "keep me",', 1), encoding="utf-8")
        install = journal_module.Install(
            cli=self.cli, installed_at=AT, config_dir=self.layout.config_dir, release={}, entries=applied.records
        )
        planner.retire(self.fs, install)
        self.assertIn("keep me", settings.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
