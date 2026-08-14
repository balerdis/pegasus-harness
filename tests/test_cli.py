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

    def test_installing_twice_reports_every_artifact_as_skipped(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["created"], [])
        self.assertTrue(report["skipped"])
        self.assertTrue(all(item["reason"] == "collision" for item in report["skipped"]))

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
        self.assertEqual(report["preserved"], [])

    def test_reinstalling_keeps_the_date_pegasus_first_landed(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        later = cli.Runtime(
            filesystem=self.filesystem, home=self.home, now="2027-01-01T00:00:00+00:00",
            out=io.StringIO(), variables=NO_BINARY,
        )
        cli.main(["install", "--cli", CLI, "--json"], runtime=later)
        self.assertEqual(journal_module.install_for(self.store().load(), CLI).installed_at, AT)

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
        self.assertEqual(report["preserved"], [])
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

    def test_an_artifact_the_user_edited_is_reported_as_preserved(self):
        self.install()
        edited = next(e for e in self.installed_entries() if e.kind == "file")
        self.filesystem.files[edited.target] = b"the user rewrote this"
        _, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertIn(edited.id, report["preserved"])
        self.assertEqual(self.filesystem.files[edited.target], b"the user rewrote this")

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


if __name__ == "__main__":
    unittest.main()
