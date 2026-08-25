"""The flags, and the report they produce.

The rule the architecture sets is parity: the TUI must not be able to do
anything the flags cannot. That makes this the surface an agent drives, so its
output is a contract and not a convenience — every number in it has to be true,
including the uncomfortable ones.

**Why the home here is half real.** Writing goes through the filesystem port and
is faked, but detection does not: an adapter answers ``detect`` with
``shutil.which`` and a real ``is_dir`` check, so it looks at the machine the
tests run on no matter what the port is told. Rather than paper over that, these
tests give the runtime an empty ``PATH`` and a real empty directory to find or
not find, which is the only way to drive detection deterministically today. The
mismatch is a known wrinkle in the architecture, not something this module
invents.
"""
from __future__ import annotations

import io
import json
import tempfile
import tomllib
import unittest
from pathlib import Path

import pegasus
from fakes import FakeFileSystem
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core.types import Environment
from pegasus.infra.snapshot_store_file import snapshots_root

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}


class CommandTestCase(unittest.TestCase):
    """A home the adapter can be told is there, or told is not."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = Path(self.directory.name)
        self.filesystem = FakeFileSystem()

    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=NO_BINARY
        )

    def layout(self):
        return available().get(CLI).layout(Environment(home=self.home))

    def present(self) -> None:
        """Make the adapter find the CLI's configuration directory."""
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def store(self):
        return cli.journal_store(self.runtime())

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def run_prose(self, *argv) -> tuple[int, str]:
        context = self.runtime()
        code = cli.main(list(argv), runtime=context)
        return code, context.out.getvalue()

    def installed_entries(self):
        return journal_module.install_for(self.store().load(), CLI).entries



class VersionTest(unittest.TestCase):
    def test_the_package_version_matches_the_project_metadata(self):
        """Two places holding one number is how a release starts lying about itself."""
        metadata = tomllib.loads(Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text())
        self.assertEqual(pegasus.__version__, metadata["project"]["version"])


class ArgumentTest(CommandTestCase):
    def test_no_command_is_an_error_rather_than_a_silent_success(self):
        self.assertNotEqual(cli.main([], runtime=self.runtime()), 0)

    def test_an_unknown_cli_is_refused_and_named(self):
        code, report = self.run_cli("install", "--cli", "nonesuch")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("nonesuch", report["error"])

    def test_json_is_honoured_on_either_side_of_the_subcommand(self):
        """A flag that silently does nothing is worse than one that is rejected."""
        self.present()
        for argv in (["doctor", "--json"], ["--json", "doctor"]):
            with self.subTest(argv=argv):
                context = self.runtime()
                cli.main(argv, runtime=context)
                self.assertEqual(json.loads(context.out.getvalue())["command"], "doctor")

    def test_every_report_declares_its_schema_and_command(self):
        self.present()
        for argv in (("doctor",), ("install", "--cli", CLI), ("uninstall", "--cli", CLI)):
            with self.subTest(argv=argv):
                _, report = self.run_cli(*argv)
                self.assertEqual(report["schema"], cli.SCHEMA)
                self.assertEqual(report["command"], argv[0])


class InstallTest(CommandTestCase):
    def test_installing_into_a_clean_home_reports_what_it_created(self):
        self.present()
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "installed")
        self.assertTrue(report["created"])
        self.assertEqual(report["skipped"], [])

    def test_installing_writes_the_journal(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.assertIsNotNone(journal_module.install_for(self.store().load(), CLI))

    def test_the_journal_records_the_release_that_placed_the_artifacts(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        install = journal_module.install_for(self.store().load(), CLI)
        self.assertEqual(install.release["version"], pegasus.__version__)
        self.assertTrue(install.release["catalog_digest"].startswith("sha256:"))
        self.assertEqual(install.installed_at, AT)

    def test_reinstalling_does_not_erase_what_the_journal_already_owned(self):
        """The second run creates nothing — everything it wants is its own work
        from the first run. Writing that empty result over the journal would
        orphan all 84 artifacts permanently, with nothing left to prove they
        were ever ours."""
        self.present()
        self.run_cli("install", "--cli", CLI)
        owned = {entry.id for entry in self.installed_entries()}
        self.assertTrue(owned)
        self.run_cli("install", "--cli", CLI)
        self.assertEqual({entry.id for entry in self.installed_entries()}, owned)

    def test_what_was_installed_can_still_be_taken_back_after_reinstalling(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.run_cli("install", "--cli", CLI)
        _, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertTrue(report["removed"])

    def test_reinstalling_keeps_the_date_pegasus_first_landed(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        later = cli.Runtime(
            filesystem=self.filesystem, home=self.home, now="2027-01-01T00:00:00+00:00",
            out=io.StringIO(), variables=NO_BINARY,
        )
        cli.main(["install", "--cli", CLI, "--json"], runtime=later)
        self.assertEqual(journal_module.install_for(self.store().load(), CLI).installed_at, AT)

    def test_reinstalling_the_same_payload_reports_no_work(self):
        """The second run is not a wall of collisions any more; it is a no-op."""
        self.present()
        self.run_cli("install", "--cli", CLI)
        _, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(report["created"], [])
        self.assertEqual(report["updated"], [])
        self.assertEqual(report["skipped"], [])
        self.assertTrue(report["unchanged"])

    def test_a_file_the_user_edited_is_overwritten_by_a_reinstall(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        target = self.layout().system_prompt_file
        original = self.filesystem.files[target]
        self.filesystem.files[target] = b"the user's own words\n"
        _, report = self.run_cli("install", "--cli", CLI)
        self.assertIn("system-prompt", [item["id"] for item in report["updated"]])
        self.assertEqual(self.filesystem.files[target], original)

    def test_the_prose_names_what_it_updated(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        code, out = self.run_prose("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertIn("updated 0", out)
        self.assertIn("already current", out)

    def test_a_dry_run_reports_the_plan_and_touches_nothing(self):
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "planned")
        self.assertTrue(report["created"])
        self.assertEqual(self.filesystem.writes, [])

    def test_installing_where_the_cli_is_absent_is_refused(self):
        """Installing into a CLI the user does not have would just leave litter."""
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.filesystem.writes, [])

    # --- Refusing before doing ---

    def test_root_is_refused_before_a_single_artifact_is_written(self):
        self.present()
        self.filesystem.privileged = True
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.filesystem.writes, [])

    def test_a_home_owned_by_someone_else_is_refused_before_writing(self):
        self.present()
        self.filesystem.owner = False
        code, _ = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.filesystem.writes, [])

    def test_an_install_that_cannot_be_recorded_is_taken_back_out(self):
        """An installation nobody recorded is one nobody can uninstall."""
        self.present()
        self.filesystem.fail_always.add(self.store().path)
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["rolled_back"])
        left = [path for path in self.filesystem.files if path.is_relative_to(self.layout().config_dir)]
        self.assertEqual(left, [self.layout().settings_file])

    def test_a_journal_that_cannot_be_read_stops_the_install_before_it_writes(self):
        """A journal we cannot read is one we cannot extend.

        Discovering that after placing the artifacts would leave them on disk
        with nothing recording them, and `doctor` would fail against the same
        unreadable journal — so there would be no way left to find out they are
        there. Reading is part of the preflight, not an afterthought.
        """
        self.present()
        self.filesystem.files[self.store().path] = b"{ not json at all"
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.filesystem.writes, [])

    def test_a_dry_run_also_refuses_an_unreadable_journal(self):
        self.present()
        self.filesystem.files[self.store().path] = b"{ not json at all"
        code, _ = self.run_cli("install", "--cli", CLI, "--dry-run")
        self.assertNotEqual(code, 0)

    def test_a_report_says_how_much_this_run_placed(self):
        """`rolled_back: false` alone reads as "the rollback failed" to something
        that only checks the flag. The count says which it was."""
        self.present()
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["placed"], len(report["created"]))

    def test_a_failed_reinstall_reports_that_it_placed_nothing(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.filesystem.fail_always.add(self.store().path)
        _, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(report["placed"], 0)
        self.assertFalse(report["rolled_back"])

    def test_a_failed_reinstall_does_not_take_the_working_install_with_it(self):
        """The rollback undoes this run, never what earlier runs already owned.

        A second install creates nothing, so there is nothing to undo. Rolling
        back the accumulated view instead would delete a working installation
        while the journal — never written, because saving is what failed — goes
        on claiming all of it is there. That is worse than the orphaned files
        this command was fixed to prevent: the same lie, pointing the other way.
        """
        self.present()
        self.run_cli("install", "--cli", CLI)
        placed = dict(self.filesystem.files)
        owned = {entry.id for entry in self.installed_entries()}

        self.filesystem.fail_always.add(self.store().path)
        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        # Outside the snapshots, nothing moved: the first install's files are
        # exactly what is still there. A snapshot generation is allowed to have
        # appeared, because taking one is this run's own behaviour rather than a
        # mutation of the earlier install, and excluding only that leaves the
        # original claim — that a failed reinstall adds nothing else — intact.
        root = snapshots_root(self.home)

        def outside_the_snapshots(files):
            return {path: content for path, content in files.items() if not path.is_relative_to(root)}

        self.assertEqual(outside_the_snapshots(self.filesystem.files), outside_the_snapshots(placed))
        self.assertEqual({entry.id for entry in self.installed_entries()}, owned)
        self.assertFalse(report["rolled_back"], "nothing was placed, so nothing was rolled back")

    def test_a_failed_reinstall_leaves_the_installation_usable(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.filesystem.fail_always.add(self.store().path)
        self.run_cli("install", "--cli", CLI)

        self.filesystem.fail_always.clear()
        _, report = self.run_cli("doctor")
        self.assertEqual(report["clis"][0]["missing"], [])
        self.assertEqual(report["clis"][0]["drifted"], [])

    def test_the_rollback_admits_the_settings_file_it_could_not_take_back(self):
        """The documented residue, said out loud instead of reported as a clean undo."""
        self.present()
        self.filesystem.fail_always.add(self.store().path)
        _, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(report["left_behind"], [str(self.layout().settings_file)])


class UninstallTest(CommandTestCase):
    def install(self):
        self.present()
        self.run_cli("install", "--cli", CLI)

    def test_uninstalling_reports_what_it_took_back(self):
        self.install()
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "uninstalled")
        self.assertTrue(report["removed"])
        self.assertEqual(report["unaccounted"], [])

    def test_uninstalling_forgets_the_install_in_the_journal(self):
        self.install()
        self.run_cli("uninstall", "--cli", CLI)
        self.assertIsNone(journal_module.install_for(self.store().load(), CLI))

    def test_uninstalling_what_was_never_installed_says_so(self):
        self.present()
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_an_artifact_the_user_edited_is_removed_too(self):
        self.install()
        edited = next(e for e in self.installed_entries() if e.kind == "file")
        self.filesystem.files[edited.target] = b"the user rewrote this"
        _, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertIn(edited.id, report["removed"])
        self.assertNotIn(edited.target, self.filesystem.files)

    def test_root_is_refused_before_anything_is_taken_back(self):
        self.install()
        self.filesystem.privileged = True
        before = dict(self.filesystem.files)
        code, _ = self.run_cli("uninstall", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.filesystem.files, before)


class DoctorTest(CommandTestCase):
    def install(self):
        self.present()
        self.run_cli("install", "--cli", CLI)

    def test_doctor_lists_every_supported_cli(self):
        _, report = self.run_cli("doctor")
        self.assertEqual([entry["cli"] for entry in report["clis"]], list(available().ids()))

    def test_doctor_reports_a_clean_home_as_not_installed(self):
        self.present()
        _, report = self.run_cli("doctor")
        self.assertFalse(report["clis"][0]["pegasus_installed"])

    def test_doctor_reports_an_absent_cli_as_undetected(self):
        _, report = self.run_cli("doctor")
        self.assertFalse(report["clis"][0]["detected"])

    def test_doctor_counts_what_is_installed_and_finds_no_drift(self):
        self.install()
        _, report = self.run_cli("doctor")
        entry = report["clis"][0]
        self.assertTrue(entry["pegasus_installed"])
        self.assertGreater(entry["artifacts"], 0)
        self.assertEqual(entry["drifted"], [])
        self.assertEqual(entry["missing"], [])

    def test_doctor_names_an_artifact_the_user_edited(self):
        self.install()
        edited = next(e for e in self.installed_entries() if e.kind == "file")
        self.filesystem.files[edited.target] = b"changed by hand"
        _, report = self.run_cli("doctor")
        self.assertEqual(report["clis"][0]["drifted"], [edited.id])

    def test_doctor_names_an_artifact_that_went_missing(self):
        self.install()
        gone = next(e for e in self.installed_entries() if e.kind == "file")
        del self.filesystem.files[gone.target]
        _, report = self.run_cli("doctor")
        self.assertEqual(report["clis"][0]["missing"], [gone.id])

    def test_doctor_notices_a_configuration_key_the_user_removed(self):
        self.install()
        key = next(e for e in self.installed_entries() if e.kind == "config-key" and not e.pointer.endswith("/-"))
        document = json.loads(self.filesystem.files[key.target])
        del document["agent" if "agent" in key.pointer else key.pointer.strip("/").split("/")[0]]
        self.filesystem.files[key.target] = json.dumps(document).encode("utf-8")
        _, report = self.run_cli("doctor")
        self.assertIn(key.id, report["clis"][0]["missing"])

    def test_doctor_never_writes(self):
        self.install()
        self.filesystem.writes.clear()
        self.run_cli("doctor")
        self.assertEqual(self.filesystem.writes, [])

    def test_doctor_reports_a_damaged_journal_instead_of_pretending_nothing_is_installed(self):
        self.install()
        self.filesystem.files[self.store().path] = b"{ not json"
        code, report = self.run_cli("doctor")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class SnapshotTest(CommandTestCase):
    def snapshots(self):
        return cli.snapshot_store(self.runtime())

    def test_a_dry_run_writes_no_snapshot(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--dry-run")
        self.assertEqual(self.filesystem.list_dir(snapshots_root(self.home)), [])

    def test_installing_writes_a_snapshot_before_the_first_artifact_reaches_disk(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        snapshot_index = next(
            i for i, path in enumerate(self.filesystem.writes) if path.is_relative_to(snapshots_root(self.home))
        )
        artifact_index = next(
            i for i, path in enumerate(self.filesystem.writes) if path.is_relative_to(self.layout().config_dir)
        )
        self.assertLess(snapshot_index, artifact_index)

    def test_the_snapshot_of_an_install_contains_the_journals_path(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        manifest = self.snapshots().read(1)
        self.assertIn(self.store().path, {entry.path for entry in manifest.entries})

    def test_a_newly_created_file_is_captured_as_not_having_existed(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        manifest = self.snapshots().read(1)
        entry = next(e for e in manifest.entries if e.path == self.layout().system_prompt_file)
        self.assertFalse(entry.existed)
        self.assertIsNone(entry.mode)
        self.assertIsNone(entry.blob)

    def test_a_file_that_existed_before_is_captured_with_its_previous_bytes_and_mode(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        before_content = self.filesystem.files[self.store().path]
        before_mode = self.filesystem.modes[self.store().path]

        self.run_cli("install", "--cli", CLI)

        manifest = self.snapshots().read(2)
        entry = next(e for e in manifest.entries if e.path == self.store().path)
        self.assertTrue(entry.existed)
        self.assertEqual(entry.mode, f"{before_mode:04o}")
        blob_path = self.snapshots().root / "000002" / entry.blob
        self.assertEqual(self.filesystem.files[blob_path], before_content)

    def test_uninstalling_writes_a_snapshot_too(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.run_cli("uninstall", "--cli", CLI)
        manifest = self.snapshots().read(2)
        self.assertTrue(manifest.entries)

    def test_when_the_snapshot_store_refuses_install_writes_nothing(self):
        self.present()
        self.filesystem.fail_list.add(snapshots_root(self.home))
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.filesystem.writes, [])

    def test_when_the_snapshot_store_refuses_uninstall_removes_nothing(self):
        """The way out needs the same guard as the way in.

        Uninstalling deletes what the journal claims, so a run that cannot
        capture first is a run that would destroy the only copy. Nothing is
        removed and the journal still records the install, which is what lets
        the user try again once whatever refused the snapshot is fixed.
        """
        self.present()
        self.run_cli("install", "--cli", CLI)
        surviving = dict(self.filesystem.files)
        self.filesystem.fail_list.add(snapshots_root(self.home))

        code, report = self.run_cli("uninstall", "--cli", CLI)

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.filesystem.files, surviving)
        self.assertIsNotNone(self.installed_entries())

    def test_generation_numbers_advance_across_successive_commands(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.run_cli("uninstall", "--cli", CLI)
        self.assertIsNotNone(self.snapshots().read(1))
        self.assertIsNotNone(self.snapshots().read(2))


class RestoreTest(CommandTestCase):
    def snapshots(self):
        return cli.snapshot_store(self.runtime())

    def test_restoring_returns_a_files_previous_bytes_and_mode_exactly(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        target = self.layout().system_prompt_file
        self.filesystem.write_atomic(target, b"hand-edited by the user", mode=0o600)
        # Installing again overwrites the hand edit without asking, but not
        # before this second snapshot captures it.
        self.run_cli("install", "--cli", CLI)

        code, report = self.run_cli("restore", "2")

        self.assertEqual(code, 0)
        self.assertEqual(self.filesystem.files[target], b"hand-edited by the user")
        self.assertEqual(self.filesystem.modes[target], 0o600)
        self.assertIn(str(target), report["written"])

    def test_a_restore_that_fails_partway_says_what_it_already_changed(self):
        """A command that wrote something must never report that it wrote nothing.

        Restoring touches one address at a time, so a failure in the middle
        leaves some of them already back at their previous contents. Reporting
        that as "nothing was changed" would send the user looking for a problem
        somewhere else, and would tell an agent that the filesystem is in a
        state it is not in.
        """
        self.present()
        self.run_cli("install", "--cli", CLI)
        target = self.layout().system_prompt_file
        self.filesystem.write_atomic(target, b"hand-edited by the user", mode=0o600)
        self.run_cli("install", "--cli", CLI)
        # The journal sorts after the prompt file, so the prompt is already back
        # by the time this refusal lands.
        self.filesystem.fail_always.add(cli.journal_store(self.runtime()).path)

        code, report = self.run_cli("restore", "2")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn(str(target), report["written"])
        self.assertNotIn("Nothing was changed", cli._prose(report))

    def test_restoring_an_entry_recorded_as_absent_removes_the_path(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        target = self.layout().system_prompt_file
        self.assertIn(target, self.filesystem.files)

        code, report = self.run_cli("restore", "1")

        self.assertEqual(code, 0)
        self.assertNotIn(target, self.filesystem.files)
        self.assertIn(str(target), report["removed"])

    def test_restoring_with_no_argument_picks_the_most_recent_readable_generation(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.run_cli("install", "--cli", CLI)

        code, report = self.run_cli("restore")

        self.assertEqual(code, 0)
        self.assertEqual(report["generation"], 2)

    def test_restore_resolves_its_target_before_taking_its_own_snapshot(self):
        """The trap: resolving "most recent" after the new snapshot is taken
        would make restore recover its own copy of the present."""
        self.present()
        self.run_cli("install", "--cli", CLI)

        code, report = self.run_cli("restore")

        self.assertEqual(code, 0)
        self.assertEqual(report["generation"], 1)

    def test_restore_takes_its_own_snapshot(self):
        self.present()
        self.run_cli("install", "--cli", CLI)

        self.run_cli("restore")

        self.assertEqual(self.snapshots().readable_generations(), [1, 2])

    def test_when_the_snapshot_store_refuses_restore_writes_nothing(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        before = dict(self.filesystem.files)
        self.filesystem.fail_list.add(snapshots_root(self.home))

        code, report = self.run_cli("restore")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.filesystem.files, before)

    def test_restoring_an_unreadable_generation_is_refused(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.filesystem.make_dir(snapshots_root(self.home) / "000002")

        code, report = self.run_cli("restore", "2")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_restoring_with_nothing_ever_installed_is_refused(self):
        self.present()
        code, report = self.run_cli("restore")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class RetentionTest(CommandTestCase):
    def snapshots(self):
        return cli.snapshot_store(self.runtime())

    def test_a_sixth_generation_deletes_the_first_and_five_remain(self):
        self.present()
        for _ in range(6):
            self.run_cli("install", "--cli", CLI)
        self.assertEqual(self.snapshots().readable_generations(), [2, 3, 4, 5, 6])

    def test_a_retention_failure_leaves_the_command_successful_and_is_still_reported(self):
        self.present()
        for _ in range(5):
            self.run_cli("install", "--cli", CLI)
        self.filesystem.fail_remove_dir.add(snapshots_root(self.home) / "000001")

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "installed")
        self.assertTrue(report["retention"]["failed"])
        self.assertIn(1, self.snapshots().readable_generations())

    def test_retention_run_twice_does_not_fail(self):
        self.present()
        for _ in range(6):
            self.run_cli("install", "--cli", CLI)
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["retention"]["failed"], [])


class HumanOutputTest(CommandTestCase):
    def test_without_json_the_output_is_prose_and_not_a_document(self):
        self.present()
        context = self.runtime()
        code = cli.main(["doctor"], runtime=context)
        written = context.out.getvalue()
        self.assertEqual(code, 0)
        self.assertTrue(written.strip())
        with self.assertRaises(json.JSONDecodeError):
            json.loads(written)

    def test_a_failure_says_what_went_wrong_in_prose_too(self):
        self.present()
        context = self.runtime()
        code = cli.main(["uninstall", "--cli", CLI], runtime=context)
        self.assertNotEqual(code, 0)
        self.assertIn(CLI, context.out.getvalue())

    def test_prose_does_not_claim_nothing_changed_when_something_was_left_behind(self):
        self.present()
        self.filesystem.fail_always.add(self.store().path)
        context = self.runtime()
        cli.main(["install", "--cli", CLI], runtime=context)
        self.assertNotIn("Nothing was changed", context.out.getvalue())


class ActivationTest(CommandTestCase):
    """Writing the files is not the same as the CLI having read them.

    A CLI that loads its configuration once, at startup, keeps running on what it
    read before the install. Reporting success without saying so leaves the user
    looking at an installation that is on disk and inert.
    """

    def test_install_reports_what_is_left_for_the_user_to_do(self):
        self.present()
        _, report = self.run_cli("install", "--cli", CLI)
        self.assertTrue(report["activation"], "the adapter contributed no activation step")

    def test_a_dry_run_says_it_too_because_it_is_the_same_installation(self):
        self.present()
        _, report = self.run_cli("install", "--cli", CLI, "--dry-run")
        self.assertTrue(report["activation"])

    def test_uninstall_says_it_as_well(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        _, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertTrue(report["activation"])

    def test_doctor_says_it_too_because_that_is_why_people_run_doctor(self):
        """An unread configuration is exactly what makes an install look inert."""
        self.present()
        self.run_cli("install", "--cli", CLI)
        _, report = self.run_cli("doctor")
        self.assertTrue(report["clis"][0]["activation"])

    def test_doctor_stays_quiet_when_pegasus_is_not_installed(self):
        self.present()
        _, report = self.run_cli("doctor")
        self.assertNotIn("activation", report["clis"][0])

    def test_the_prose_carries_it_because_prose_is_never_a_subset(self):
        self.present()
        context = self.runtime()
        cli.main(["install", "--cli", CLI], runtime=context)
        written = context.out.getvalue()
        for step in available().get(CLI).activation_steps():
            self.assertIn(step, written)


if __name__ == "__main__":
    unittest.main()
