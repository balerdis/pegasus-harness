"""The flags, and the report they produce.

The rule the architecture sets is parity: the TUI must not be able to do
anything the flags cannot. That makes this the surface an agent drives, so its
output is a contract and not a convenience — every number in it has to be true,
including the uncomfortable ones.

**Real disk, mostly.** Every test in this module runs against a throwaway home
and the real `PosixFileSystem`, via `RealHomeTestCase`. The one exception is
`WriteRefusalTest`: a process that may not write on the home owner's behalf
— running as root, or a home belonging to somebody else — has no honest
real-disk equivalent short of actually being one of those, so those cases
stay on `FakeFileSystem`.

**Why detection is still half real.** Writing goes through the filesystem
port, which is now real, but detection does not: an adapter answers
``detect`` with ``shutil.which`` and a real ``is_dir`` check, so it looks at
the machine the tests run on no matter what the port is told. Rather than
paper over that, these tests give the runtime an empty ``PATH`` and rely on
the throwaway home's config directory being absent (or created by
``present()``) to drive detection deterministically. The mismatch is a known
wrinkle in the architecture, not something this module invents.
"""
from __future__ import annotations

import io
import json
import stat
import tempfile
import tomllib
import unittest
from unittest import mock
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pegasus
from fakes import FakeFileSystem
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import content as content_module
from pegasus.core import journal as journal_module
from pegasus.core import model_assignments as model_assignments_module
from pegasus.core import ownership
from pegasus.core.types import Environment, ModelAssignment
from pegasus.infra.journal_store_file import journal_path
from pegasus.infra.snapshot_store_file import snapshots_root
from platform_conditions import (
    fail_probe_once_it_exists,
    make_undeletable,
    make_unreadable,
    make_unwritable,
)
from real_home import RealHomeTestCase as _RealHomeTestCase
from recording_filesystem import RecordingFileSystem

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}


class RealHomeTestCase(_RealHomeTestCase):
    """The generic real-home base plus what only the CLI surface needs.

    The throwaway home and the real POSIX filesystem come from the shared
    base; everything below is specific to driving `cli.main` and to proving
    facts about what it did or did not do to the real disk underneath it.
    """

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

    def snapshot(self) -> dict[Path, bytes]:
        """Every real file under the throwaway home, keyed by path — the
        disk equivalent of the double's ``files`` dict, for tests that used
        to compare that dict before and after a run."""
        return {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()}

    def assert_no_artifacts_written(self) -> None:
        """No file landed under the CLI's own configuration directory."""
        self.assertEqual([path for path in self.layout().config_dir.rglob("*") if path.is_file()], [])

    def assert_disk_untouched(self) -> None:
        """Nothing this command could have written reached disk at all: no
        artifact, no journal, no snapshot generation."""
        self.assert_no_artifacts_written()
        self.assertFalse(journal_path(self.filesystem, self.home).exists())
        self.assertFalse(snapshots_root(self.filesystem, self.home).exists())

    def make_journal_unwritable(self) -> Callable[[], None]:
        """Make the directory holding the journal refuse a write — the
        honest equivalent of the double's ``fail_always.add(store().path)``:
        a real directory has no way to refuse one specific file while
        accepting everything else beside it, so this refuses the whole
        directory, which is what the journal store's own write goes through
        regardless.

        The snapshots directory is created first, same as
        `refuse_to_write_the_journal`: it shares this same parent, and a run
        that reaches the journal has already taken its preflight snapshot,
        which needs to create a fresh generation folder *inside* it. Locking
        the parent after that folder already exists leaves the ability to
        write inside it untouched, and only refuses a new entry directly in
        the parent — which is exactly the journal file.
        """
        snapshots_root(self.filesystem, self.home).mkdir(parents=True, exist_ok=True)
        return make_unwritable(self.store().path.parent)

    def refuse_to_write_the_journal(self) -> None:
        """Make the journal write fail with real permissions, and only it.

        The snapshots directory is created first and left writable, so the
        preflight snapshot still succeeds and the run actually reaches the
        journal — which is the whole point, since the report being tested is
        the one a journal failure produces after the artifacts are already
        placed.
        """
        snapshots_root(self.filesystem, self.home).mkdir(parents=True, exist_ok=True)
        data_dir = journal_path(self.filesystem, self.home).parent
        self.addCleanup(make_unwritable(data_dir))

    def refuse_to_probe_once_it_exists(self, path: Path) -> None:
        self.addCleanup(fail_probe_once_it_exists(path))


class FakeHomeTestCase(unittest.TestCase):
    """Only for what no real condition can produce.

    "Running as root" and "a home owned by someone else" are facts
    `PosixFileSystem` reads straight off the operating system —
    ``running_privileged`` from ``os.geteuid()``, ``owned_by_current_user``
    from the file's real owner — and neither can be faked from inside a test
    without actually being root, or actually being another user. Every other
    test in this module runs on real disk; these stay on the double because
    there is no honest way to move them.
    """

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
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())


class VersionTest(unittest.TestCase):
    def test_the_package_version_matches_the_project_metadata(self):
        """Two places holding one number is how a release starts lying about itself."""
        metadata = tomllib.loads(Path(__file__).resolve().parents[1].joinpath("pyproject.toml").read_text())
        self.assertEqual(pegasus.__version__, metadata["project"]["version"])


class ArgumentTest(RealHomeTestCase):
    def test_no_command_without_a_terminal_is_an_error_rather_than_a_silent_success(self):
        """Asking for nothing at a terminal opens the menu, but piped or
        redirected there is no menu to show and nobody to read it — and a
        script that reached here by mistake needs to be told."""
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


class InstallTest(RealHomeTestCase):
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
        original = target.read_bytes()
        target.write_bytes(b"the user's own words\n")
        _, report = self.run_cli("install", "--cli", CLI)
        self.assertIn("system-prompt", [item["id"] for item in report["updated"]])
        self.assertEqual(target.read_bytes(), original)

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
        self.assert_disk_untouched()

    def test_installing_where_the_cli_is_absent_is_refused(self):
        """Installing into a CLI the user does not have would just leave litter."""
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assert_disk_untouched()

    # --- Refusing before doing ---

    def test_an_install_that_cannot_be_recorded_is_taken_back_out(self):
        """An installation nobody recorded is one nobody can uninstall."""
        self.present()
        self.addCleanup(self.make_journal_unwritable())
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["rolled_back"])
        left = [path for path in self.layout().config_dir.rglob("*") if path.is_file()]
        self.assertEqual(left, [self.layout().settings_file])

    def test_a_journal_that_cannot_be_read_stops_the_install_before_it_writes(self):
        """A journal we cannot read is one we cannot extend.

        Discovering that after placing the artifacts would leave them on disk
        with nothing recording them, and `doctor` would fail against the same
        unreadable journal — so there would be no way left to find out they are
        there. Reading is part of the preflight, not an afterthought.
        """
        self.present()
        self.store().path.parent.mkdir(parents=True, exist_ok=True)
        self.store().path.write_bytes(b"{ not json at all")
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assert_no_artifacts_written()

    def test_a_dry_run_also_refuses_an_unreadable_journal(self):
        self.present()
        self.store().path.parent.mkdir(parents=True, exist_ok=True)
        self.store().path.write_bytes(b"{ not json at all")
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
        self.addCleanup(self.make_journal_unwritable())
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
        placed = self.snapshot()
        owned = {entry.id for entry in self.installed_entries()}

        self.addCleanup(self.make_journal_unwritable())
        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        # Outside the snapshots, nothing moved: the first install's files are
        # exactly what is still there. A snapshot generation is allowed to have
        # appeared, because taking one is this run's own behaviour rather than a
        # mutation of the earlier install, and excluding only that leaves the
        # original claim — that a failed reinstall adds nothing else — intact.
        root = snapshots_root(self.filesystem, self.home)

        def outside_the_snapshots(files):
            return {path: content for path, content in files.items() if not path.is_relative_to(root)}

        self.assertEqual(outside_the_snapshots(self.snapshot()), outside_the_snapshots(placed))
        self.assertEqual({entry.id for entry in self.installed_entries()}, owned)
        self.assertFalse(report["rolled_back"], "nothing was placed, so nothing was rolled back")

    def test_a_failed_reinstall_leaves_the_installation_usable(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        restore_writable = self.make_journal_unwritable()
        self.addCleanup(restore_writable)
        self.run_cli("install", "--cli", CLI)

        restore_writable()
        _, report = self.run_cli("doctor")
        self.assertEqual(report["clis"][0]["missing"], [])
        self.assertEqual(report["clis"][0]["drifted"], [])

    def test_the_rollback_admits_the_settings_file_it_could_not_take_back(self):
        """The documented residue, said out loud instead of reported as a clean undo."""
        self.present()
        self.addCleanup(self.make_journal_unwritable())
        _, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(report["left_behind"], [str(self.layout().settings_file)])

    # The probe inside `existing = {... exists(path) ...}` has no test of its
    # own, deliberately. Nothing changes on disk between it and the probe
    # `plan` already made of the same documents, so no real condition can make
    # one fail and the other succeed — and both refuse before a single
    # artifact is placed, which is the same guarantee. `test_planner`'s
    # `fail_exists` cases cover the plan-time refusal; a second test here
    # would only be able to prove it by counting calls.


class WriteRefusalTest(FakeHomeTestCase):
    """The refusals `RealHomeTestCase` cannot produce: see `FakeHomeTestCase`'s
    docstring for why they stay on the double.

    Running as root and a home belonging to somebody else used to be two
    separate cases here. They are one answer now — the filesystem says this
    process may not write on the owner's behalf — so what is left to prove is
    that each command honours it before touching anything, not which of the
    two produced it.
    """

    def test_a_home_this_process_may_not_write_is_refused_before_a_single_artifact_is_written(self):
        self.present()
        self.filesystem.writable = False
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.filesystem.writes, [])

    def test_a_home_this_process_may_not_write_is_refused_before_anything_is_taken_back(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.filesystem.writable = False
        before = dict(self.filesystem.files)
        code, _ = self.run_cli("uninstall", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(self.filesystem.files, before)


class InstallModelAssignmentTest(RealHomeTestCase):
    """A stored preference reaching the rendered agent, and its soft-failure posture.

    `sdd-apply` is `CONFIGURABLE_AGENT` in `test_cli_models.py`, but this module
    never imports that one to stay independent of it -- the name is repeated
    here on purpose.
    """

    AGENT = "sdd-apply"

    def write_models_catalog(self, providers: dict) -> None:
        path = self.home / ".cache" / "opencode" / "models.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(providers), encoding="utf-8")

    def rendered_agent_value(self) -> dict:
        document = json.loads((self.layout().settings_file).read_text(encoding="utf-8"))
        return document["agent"][self.AGENT]

    def test_an_honoured_assignment_is_written_into_the_rendered_agent(self):
        self.present()
        self.write_models_catalog(
            {"anthropic": {"builtin": True, "models": {"claude-sonnet-5": {"tool_call": True}}}}
        )
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["model_warnings"], [])
        self.assertEqual(self.rendered_agent_value()["model"], "anthropic/claude-sonnet-5")

    def test_no_assignment_renders_exactly_what_it_renders_today(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.assertNotIn("model", self.rendered_agent_value())

    def test_an_effort_reaches_the_rendered_agent_as_this_clis_variant(self):
        self.present()
        self.write_models_catalog(
            {"anthropic": {"builtin": True, "models": {"claude-sonnet-5": {"tool_call": True, "reasoning": True}}}}
        )
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT,
            "--model", "anthropic/claude-sonnet-5", "--effort", "high",
        )
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["model_warnings"], [])
        value = self.rendered_agent_value()
        self.assertEqual(value["model"], "anthropic/claude-sonnet-5")
        self.assertEqual(value["variant"], "high")

    def test_no_effort_stored_renders_no_variant_key(self):
        self.present()
        self.write_models_catalog(
            {"anthropic": {"builtin": True, "models": {"claude-sonnet-5": {"tool_call": True}}}}
        )
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        self.run_cli("install", "--cli", CLI)
        self.assertNotIn("variant", self.rendered_agent_value())

    def test_an_unreachable_provider_does_not_break_the_install(self):
        self.present()
        # No models.json at all: no provider is reachable on this machine.
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertNotIn("model", self.rendered_agent_value())
        self.assertEqual(len(report["model_warnings"]), 1)
        self.assertIn(self.AGENT, report["model_warnings"][0])
        self.assertIn("anthropic", report["model_warnings"][0])

    def test_a_model_the_catalog_no_longer_lists_does_not_break_the_install(self):
        self.present()
        self.write_models_catalog(
            {"anthropic": {"builtin": True, "models": {"claude-sonnet-5": {"tool_call": True}}}}
        )
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT, "--model", "anthropic/retired-model",
        )
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertNotIn("model", self.rendered_agent_value())
        self.assertEqual(len(report["model_warnings"]), 1)
        self.assertIn("retired-model", report["model_warnings"][0])

    def test_an_agent_this_release_no_longer_ships_does_not_break_the_install(self):
        self.present()
        self.write_models_catalog(
            {"anthropic": {"builtin": True, "models": {"claude-sonnet-5": {"tool_call": True}}}}
        )
        store = cli.model_assignment_store(self.runtime())
        store.save(
            model_assignments_module.with_assignment(
                store.load(), CLI, "no-longer-shipped", ModelAssignment("anthropic", "claude-sonnet-5")
            )
        )
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(len(report["model_warnings"]), 1)
        self.assertIn("no-longer-shipped", report["model_warnings"][0])

    def test_the_catalog_digest_is_the_same_with_or_without_an_assignment(self):
        """Release identity must not move because of a fact about one machine."""
        self.present()
        self.run_cli("install", "--cli", CLI)
        without = journal_module.install_for(self.store().load(), CLI).release["catalog_digest"]

        self.write_models_catalog(
            {"anthropic": {"builtin": True, "models": {"claude-sonnet-5": {"tool_call": True}}}}
        )
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", self.AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        self.run_cli("install", "--cli", CLI)
        with_assignment = journal_module.install_for(self.store().load(), CLI).release["catalog_digest"]
        self.assertEqual(without, with_assignment)


class InstallMcpTest(RealHomeTestCase):
    """`--mcp` is the whole point of this unit: nothing installs unless named."""

    def settings(self) -> dict:
        return json.loads(self.layout().settings_file.read_bytes())

    def convention_path(self, server_id: str) -> Path:
        # Derived, not spelled out: the core owns where a convention lands, and a
        # second copy of that layout here would drift the first time it moves.
        return self.layout().skills_dir / content_module.mcp_convention_path(server_id)

    def tools_of(self, agent_name: str) -> dict:
        return self.settings()["agent"][agent_name]["tools"]

    def test_choosing_context7_places_its_key_and_its_convention_file(self):
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.assertEqual(code, 0)
        self.assertIn("context7", self.settings()["mcp"])
        self.assertTrue(self.filesystem.exists(self.convention_path("context7")))

    def test_choosing_context7_grants_it_to_the_agents_that_declare_it(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.assertEqual(
            self.tools_of("sdd-apply"),
            {
                "*": False,
                "read": True,
                "write": True,
                "edit": True,
                "bash": True,
                "grep": True,
                "glob": True,
                "context7*": True,
            },
        )

    def test_choosing_nothing_places_no_server_and_no_grant(self):
        self.present()
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertNotIn("mcp", self.settings())
        self.assertFalse(self.filesystem.exists(self.convention_path("context7")))
        self.assertEqual(
            self.tools_of("sdd-apply"),
            {
                "*": False,
                "read": True,
                "write": True,
                "edit": True,
                "bash": True,
                "grep": True,
                "glob": True,
            },
        )

    def test_choosing_nothing_ships_no_engram_memory_protocol_anywhere(self):
        """The memory protocol now lives entirely in engram's own convention
        body: naming no server must leave no trace of it, neither as a
        convention file nor inlined into the shipped system prompt."""
        self.present()
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertNotIn("mcp", self.settings())
        self.assertFalse(self.filesystem.exists(self.convention_path("engram")))
        prompt_text = self.layout().system_prompt_file.read_text(encoding="utf-8")
        self.assertNotIn("Engram Persistent Memory", prompt_text)
        self.assertNotIn("PROACTIVE SAVE TRIGGERS", prompt_text)
        self.assertNotIn("Session Close Protocol", prompt_text)
        self.assertNotIn("mem_search", prompt_text)
        self.assertNotIn("mem_context", prompt_text)
        # The delivery guarantee is not engram-specific, so it ships either way,
        # `mem_save` and friends included as its own worked example.
        self.assertIn("DELIVERY GUARANTEE", prompt_text)

    def test_binding_a_server_writes_no_key_and_fetches_nothing(self):
        """The whole point, end to end: an installation that already runs the
        server gets the contract without a second definition beside its own,
        and without a download this machine never asked for. `--dry-run`
        answers both at once -- the plan names every artifact, and a fetch
        that were going to happen would show as a dependency to materialize.
        """
        self.present()
        code, report = self.run_cli(
            "install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp", "--dry-run"
        )
        self.assertEqual(code, 0)
        planned = {item["id"] for group in ("created", "updated") for item in report[group]}
        self.assertIn("mcp-convention:cbm", planned)
        self.assertNotIn("mcp:cbm", planned)
        self.assertNotIn("dependency:cbm", planned)

    def test_a_bound_server_grants_its_tools_under_the_key_the_runtime_resolves(self):
        """A grant spelled `cbm*` would match nothing in an installation whose
        server is called something else -- the tools would be silently absent,
        which is the failure this feature exists to prevent."""
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")
        self.assertEqual(code, 0)
        tools = self.tools_of("sdd-apply")
        self.assertIs(tools.get("codebase-memory-mcp*"), True)
        self.assertNotIn("cbm*", tools)

    def test_a_bound_server_leaves_the_settings_mcp_map_untouched(self):
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")
        self.assertEqual(code, 0)
        self.assertNotIn("cbm", self.settings().get("mcp", {}))

    def test_a_malformed_binding_is_refused_with_the_value_quoted(self):
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=")
        self.assertEqual(code, 1)
        self.assertIn("cbm=", json.dumps(report))

    def test_choosing_engram_plans_its_key_and_its_convention_file(self):
        """`download` servers materialize real dependencies on a real install,
        which this test suite must never trigger over the network. `--dry-run`
        computes the same plan without fetching anything, which is exactly
        what proves the convention travels with the server once it is named."""
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "engram", "--dry-run")
        self.assertEqual(code, 0)
        created_ids = {item["id"] for item in report["created"]}
        self.assertIn("mcp:engram", created_ids)
        self.assertIn("mcp-convention:engram", created_ids)

    def test_choosing_engram_ships_the_delivery_guarantee_too(self):
        """Selecting a server changes what conventions ship; it must never
        change whether the universal system prompt ships."""
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "engram", "--dry-run")
        self.assertEqual(code, 0)
        created_ids = {item["id"] for item in report["created"]}
        self.assertIn("system-prompt", created_ids)

    def test_an_unknown_server_id_fails_cleanly_and_places_nothing(self):
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "bogus")
        self.assertEqual(code, cli.FAILED)
        self.assertEqual(report["status"], "failed")
        self.assertIn("bogus", report["error"])
        self.assert_disk_untouched()

    def test_the_flag_is_repeatable(self):
        """No second shipped server exists yet, so this proves append semantics
        the only way available: naming the same id twice still selects it once,
        rather than the second `--mcp` silently replacing the first."""
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "context7", "--mcp", "context7")
        self.assertEqual(code, 0)
        self.assertIn("context7", self.settings()["mcp"])

    def test_reinstalling_without_the_server_takes_its_key_and_file_back_out(self):
        """A server chosen once and then left unnamed on the next install should
        not stay behind as an orphan: this is the case the unit exists to prove
        one way or the other."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.assertIn("context7", self.settings()["mcp"])
        self.assertTrue(self.filesystem.exists(self.convention_path("context7")))

        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertNotIn("context7", self.settings().get("mcp", {}))
        self.assertFalse(self.filesystem.exists(self.convention_path("context7")))

    def test_a_dry_run_of_reinstalling_without_the_server_reports_what_it_would_retire(self):
        """A `--dry-run` that omits `--mcp` is about to retire two entries, and
        saying `updated 5, unchanged 101` without naming them would be lying by
        omission about what this run is going to do."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        before = self.snapshot()

        code, report = self.run_cli("install", "--cli", CLI, "--dry-run")

        self.assertEqual(code, 0)
        self.assertEqual({item["id"] for item in report["retired"]}, {"mcp:context7", "mcp-convention:context7"})
        self.assertEqual(self.snapshot(), before)

    def test_reinstalling_without_the_server_reports_what_it_retired(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertEqual(code, 0)
        self.assertEqual({item["id"] for item in report["retired"]}, {"mcp:context7", "mcp-convention:context7"})

    def test_the_snapshot_of_a_retiring_reinstall_covers_what_it_is_about_to_retire(self):
        """`context7-convention.md` shares no address with anything else this run
        touches, so nothing else would ever put it in the snapshot. Without this,
        a `restore` after this reinstall gives back the key but not the file."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        convention = self.convention_path("context7")

        self.run_cli("install", "--cli", CLI)

        self.assertFalse(self.filesystem.exists(convention))

        code, report = self.run_cli("restore", "2")

        self.assertEqual(code, 0)
        self.assertIn("context7", self.settings()["mcp"])
        self.assertTrue(self.filesystem.exists(convention))

    def test_a_reinstall_that_cannot_be_recorded_reports_what_it_already_retired(self):
        """Retiring runs before the journal is saved, so a journal failure here
        leaves at least the convention file gone, unrecorded and un-rolled-back
        — `unplace` has no way to recreate a file it never wrote. The settings
        document happens to come back whole, because it was also touched by an
        update this run made and rolled back; the file has no such luck, which
        is exactly the asymmetry the report has to admit."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        convention = self.convention_path("context7")
        self.addCleanup(self.make_journal_unwritable())

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("mcp:context7", report["retired"])
        self.assertIn("mcp-convention:context7", report["retired"])
        self.assertFalse(self.filesystem.exists(convention))

    def test_a_reinstall_whose_retirement_fails_reports_honestly_and_rolls_back_this_runs_placements(self):
        """`retire` runs before `store.save`, in its own `try` now: a failure
        here used to propagate straight to `main`'s generic handler, which has
        no report payload for it, so `_prose` printed "Nothing was changed"
        while this run's own placement — the settings document, updated to
        drop the context7 tool grant — sat on disk, unrecorded. That is the
        same class of problem `_unrecordable` exists to prevent for a
        journal-save failure, and it gets the same treatment: this run's own
        placement comes back out, and the report says so rather than lying
        about a clean nothing-happened."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        convention = self.convention_path("context7")
        self.addCleanup(make_undeletable(convention))

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["rolled_back"])
        self.assertIn("retiring", report["error"])
        self.assertNotIn("journal could not be written", report["error"])
        self.assertNotIn("Nothing was changed", cli._prose(report))
        # The removal that failed never happened, and this run's own update to
        # the settings document was taken back out along with it.
        self.assertTrue(self.filesystem.exists(convention))

    # The companion of the journal-write case — a probe that fails inside the
    # handler already reporting a retirement failure — lives in
    # `SecondaryFaultTest`, against a real home. Both conditions it needs are
    # permissions, and the double has none.


class InstallUnaccountedRetirementTest(RealHomeTestCase):
    """A retiring reinstall can meet a journal entry it cannot account for: an
    appended list item whose recorded digest matches nothing currently
    present. The user having deleted it and the user having edited it beyond
    recognition are physically indistinguishable, so it must not be reported,
    or treated, as a removal — see `Retired.unaccounted`'s docstring."""

    def inject_unaccounted_entry(self) -> None:
        """A journal entry no render will ever ask for again, pointing at a
        real appended list (`/plugin/-`, always non-empty after an install) so
        it has survivors to be ambiguous among, with a digest that matches
        none of them."""
        store = self.store()
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        template = next(entry for entry in install.entries if entry.id == "own:notifier-plugin")
        fantasma = replace(template, id="own:fantasma", after_digest="sha256:" + "0" * 64)
        store.save(journal_module.with_install(journal, replace(install, entries=install.entries + (fantasma,))))

    def test_an_unaccounted_entry_is_not_reported_as_retired(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.inject_unaccounted_entry()

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertEqual(code, 0)
        self.assertNotIn("own:fantasma", {item["id"] for item in report["retired"]})
        self.assertIn("own:fantasma", report["unaccounted"])

    def test_an_unaccounted_entry_keeps_its_record_in_the_journal(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.inject_unaccounted_entry()

        self.run_cli("install", "--cli", CLI)

        self.assertIn("own:fantasma", {entry.id for entry in self.installed_entries()})

    def test_the_unaccounted_entry_does_not_stop_genuinely_removed_entries_from_being_retired(self):
        """`mcp:context7` and `mcp-convention:context7` are addressable, not
        appended, so they are unconditionally removed in the same run that
        leaves `own:fantasma` unaccounted for right next to them."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.inject_unaccounted_entry()

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertEqual(code, 0)
        self.assertEqual({item["id"] for item in report["retired"]}, {"mcp:context7", "mcp-convention:context7"})
        owned = {entry.id for entry in self.installed_entries()}
        self.assertNotIn("mcp:context7", owned)
        self.assertNotIn("mcp-convention:context7", owned)
        self.assertIn("own:fantasma", owned)

    def test_the_prose_says_what_could_not_be_accounted_for_too(self):
        """`_prose` promises the same facts as the document, never a subset of
        them, and `uninstall`'s branch already keeps that promise. A person who
        does not pass `--json` has no other way to learn that an entry was left
        behind rather than retired."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.inject_unaccounted_entry()

        code, out = self.run_prose("install", "--cli", CLI)

        self.assertEqual(code, 0)
        self.assertIn("own:fantasma", out)


class SecondaryFaultTest(RealHomeTestCase):
    """A probe that fails inside a handler already reporting another failure.

    Both of these place their artifacts, hit a real failure, and then — while
    building the report for it — cannot determine the state of a document they
    have to mention. The specific report has to survive that second fault;
    letting it escape would replace the one message a user reads when
    something already went wrong with `main`'s generic one, and lose the
    rollback accounting with it.

    Neither condition is injected. The directory that refuses the write really
    refuses it, and the file that cannot be probed really cannot be, because
    `apply` created it after the run had already decided it was absent.
    """

    def convention(self) -> Path:
        return self.layout().skills_dir / content_module.mcp_convention_path("context7")

    def test_a_journal_write_failure_still_reports_specifically(self):
        self.present()
        settings = self.layout().settings_file
        self.refuse_to_write_the_journal()
        self.refuse_to_probe_once_it_exists(settings)

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("journal could not be written", report["error"])
        self.assertIn("rolled_back", report)

    def test_a_retirement_failure_still_reports_specifically(self):
        """The other `try` that computes `left_behind`, around `retire`.

        The settings document is removed between the two runs so this run
        creates it again — which is what makes it absent when the run first
        probes it and present when the handler probes it a second time.
        """
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        settings = self.layout().settings_file
        settings.unlink()
        # The convention file cannot be removed, which is what makes retiring fail.
        self.addCleanup(make_undeletable(self.convention()))
        self.refuse_to_probe_once_it_exists(settings)

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("retiring", report["error"])
        self.assertNotIn("journal could not be written", report["error"])
        self.assertTrue(self.convention().exists())


class UninstallTest(RealHomeTestCase):
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
        edited.target.write_bytes(b"the user rewrote this")
        _, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertIn(edited.id, report["removed"])
        self.assertFalse(edited.target.exists())


class DoctorTest(RealHomeTestCase):
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

    def claim_a_dependency_tree(self, target: Path) -> None:
        """Put a record for a materialized dependency into the journal.

        Nothing materializes one yet, so the record is written by hand — but
        the kind is real, and `doctor` reads whatever the journal claims.
        """
        store = self.store()
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        claimed = journal_module.Record(
            id="dependency:probe",
            kind="dependency-tree",
            target=target,
            after_digest=ownership.digest_of_bytes(b"whatever the archive hashed to"),
            created_at=AT,
        )
        grown = replace(install, entries=(*install.entries, claimed))
        store.save(journal_module.with_install(journal, grown))

    def test_doctor_reports_a_dependency_tree_that_is_there_as_healthy(self):
        """A tree that is present is healthy, not undeterminable.

        The digest a tree carries names what was materialized, not what is on
        disk now, so being there is the whole of what can be checked. Read as
        a configuration document instead — which is what happens to any kind
        the reader does not know — a directory refuses to be read at all, and
        the entry lands in `unreadable`: a report that Pegasus could not tell,
        about something it can tell perfectly well.
        """
        self.install()
        tree = self.home / "deps" / "probe" / "1.0.0"
        tree.mkdir(parents=True)
        self.claim_a_dependency_tree(tree)

        code, report = self.run_cli("doctor")

        self.assertEqual(code, 0)
        entry = report["clis"][0]
        self.assertNotIn("dependency:probe", entry["unreadable"])
        self.assertNotIn("dependency:probe", entry["drifted"])
        self.assertNotIn("dependency:probe", entry["missing"])

    def test_doctor_reports_a_dependency_tree_that_is_gone_as_missing(self):
        self.install()
        self.claim_a_dependency_tree(self.home / "deps" / "probe" / "1.0.0")

        _, report = self.run_cli("doctor")

        self.assertIn("dependency:probe", report["clis"][0]["missing"])

    def test_doctor_names_an_artifact_the_user_edited(self):
        self.install()
        edited = next(e for e in self.installed_entries() if e.kind == "file")
        edited.target.write_bytes(b"changed by hand")
        _, report = self.run_cli("doctor")
        self.assertEqual(report["clis"][0]["drifted"], [edited.id])

    def test_doctor_names_an_artifact_that_went_missing(self):
        self.install()
        gone = next(e for e in self.installed_entries() if e.kind == "file")
        gone.target.unlink()
        _, report = self.run_cli("doctor")
        self.assertEqual(report["clis"][0]["missing"], [gone.id])

    def test_doctor_notices_a_configuration_key_the_user_removed(self):
        self.install()
        key = next(e for e in self.installed_entries() if e.kind == "config-key" and not e.pointer.endswith("/-"))
        document = json.loads(key.target.read_bytes())
        del document["agent" if "agent" in key.pointer else key.pointer.strip("/").split("/")[0]]
        key.target.write_bytes(json.dumps(document).encode("utf-8"))
        _, report = self.run_cli("doctor")
        self.assertIn(key.id, report["clis"][0]["missing"])

    def test_doctor_names_an_artifact_whose_state_could_not_be_determined(self):
        """An entry `exists` cannot probe is neither missing nor drifted —
        claiming either would be inventing a fact doctor could not check."""
        self.install()
        unreadable = next(e for e in self.installed_entries() if e.kind == "file")
        self.refuse_to_probe_once_it_exists(unreadable.target)
        _, report = self.run_cli("doctor")
        entry = report["clis"][0]
        self.assertEqual(entry["unreadable"], [unreadable.id])
        self.assertNotIn(unreadable.id, entry["missing"])
        self.assertNotIn(unreadable.id, entry["drifted"])

    def test_doctor_does_not_abort_the_whole_report_over_one_unreadable_entry(self):
        self.install()
        entries = self.installed_entries()
        unreadable = next(e for e in entries if e.kind == "file")
        self.refuse_to_probe_once_it_exists(unreadable.target)
        code, report = self.run_cli("doctor")
        self.assertEqual(code, 0)
        self.assertEqual(report["clis"][0]["artifacts"], len(entries))

    def test_doctor_prose_mentions_what_could_not_be_determined(self):
        self.install()
        unreadable = next(e for e in self.installed_entries() if e.kind == "file")
        self.refuse_to_probe_once_it_exists(unreadable.target)
        _, report = self.run_cli("doctor")
        self.assertIn(unreadable.id, cli._prose(report))

    def test_doctor_never_writes(self):
        self.install()
        before = self.snapshot()
        self.run_cli("doctor")
        self.assertEqual(self.snapshot(), before)

    def test_doctor_reports_a_damaged_journal_instead_of_pretending_nothing_is_installed(self):
        self.install()
        self.store().path.write_bytes(b"{ not json")
        code, report = self.run_cli("doctor")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class SnapshotTest(RealHomeTestCase):
    """Order matters for one test here — a snapshot must reach disk before
    the first artifact it protects — and mtimes are too coarse to prove
    that on real disk, so this class runs on `RecordingFileSystem` instead
    of the bare port. Every other test in it still asserts on real disk
    state; the recorder only adds bookkeeping around the same real writes.
    """

    def setUp(self):
        super().setUp()
        self.filesystem = RecordingFileSystem()

    def snapshots(self):
        return cli.snapshot_store(self.runtime())

    def test_a_dry_run_writes_no_snapshot(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--dry-run")
        self.assertEqual(self.filesystem.list_dir(snapshots_root(self.filesystem, self.home)), [])

    def test_installing_writes_a_snapshot_before_the_first_artifact_reaches_disk(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        snapshot_index = next(
            i for i, path in enumerate(self.filesystem.writes) if path.is_relative_to(snapshots_root(self.filesystem, self.home))
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
        before_content = self.store().path.read_bytes()
        before_mode = stat.S_IMODE(self.store().path.stat().st_mode)

        self.run_cli("install", "--cli", CLI)

        manifest = self.snapshots().read(2)
        entry = next(e for e in manifest.entries if e.path == self.store().path)
        self.assertTrue(entry.existed)
        self.assertEqual(entry.mode, f"{before_mode:04o}")
        blob_path = self.snapshots().root / "000002" / entry.blob
        self.assertEqual(blob_path.read_bytes(), before_content)

    def test_uninstalling_writes_a_snapshot_too(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.run_cli("uninstall", "--cli", CLI)
        manifest = self.snapshots().read(2)
        self.assertTrue(manifest.entries)

    def test_when_the_snapshot_store_refuses_install_writes_nothing(self):
        self.present()
        root = snapshots_root(self.filesystem, self.home)
        root.mkdir(parents=True, exist_ok=True)
        restore = make_unreadable(root)
        self.addCleanup(restore)

        code, report = self.run_cli("install", "--cli", CLI)

        restore()
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assert_no_artifacts_written()
        self.assertFalse(journal_path(self.filesystem, self.home).exists())
        self.assertEqual(self.filesystem.list_dir(root), [])

    def test_a_path_the_snapshot_cannot_probe_refuses_the_install_before_writing_anything(self):
        """The acceptance test for the whole unit, at the command a person
        actually runs.

        Measured on real disk before this fix: `exists` swallowed `EACCES`
        for an unreadable directory and answered `False`, so a snapshot
        recorded files that were really there as absent, and `restore` later
        deleted them while reporting success. `install` must refuse before a
        single byte reaches disk instead — not merely produce a snapshot
        that lies."""
        self.present()
        unreadable = self.layout().settings_file
        restore = make_unreadable(unreadable.parent)
        self.addCleanup(restore)

        code, report = self.run_cli("install", "--cli", CLI)

        restore()
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assert_no_artifacts_written()
        self.assertEqual(self.filesystem.list_dir(snapshots_root(self.filesystem, self.home)), [])

    def test_when_the_snapshot_store_refuses_uninstall_removes_nothing(self):
        """The way out needs the same guard as the way in.

        Uninstalling deletes what the journal claims, so a run that cannot
        capture first is a run that would destroy the only copy. Nothing is
        removed and the journal still records the install, which is what lets
        the user try again once whatever refused the snapshot is fixed.
        """
        self.present()
        self.run_cli("install", "--cli", CLI)
        surviving = self.snapshot()
        restore = make_unreadable(snapshots_root(self.filesystem, self.home))
        self.addCleanup(restore)

        code, report = self.run_cli("uninstall", "--cli", CLI)

        restore()
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.snapshot(), surviving)
        self.assertIsNotNone(self.installed_entries())

    def test_generation_numbers_advance_across_successive_commands(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.run_cli("uninstall", "--cli", CLI)
        self.assertIsNotNone(self.snapshots().read(1))
        self.assertIsNotNone(self.snapshots().read(2))


class RestoreTest(RealHomeTestCase):
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
        self.assertEqual(target.read_bytes(), b"hand-edited by the user")
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
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
        self.addCleanup(self.make_journal_unwritable())

        code, report = self.run_cli("restore", "2")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn(str(target), report["written"])
        self.assertNotIn("Nothing was changed", cli._prose(report))

    def test_restoring_an_entry_recorded_as_absent_removes_the_path(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        target = self.layout().system_prompt_file
        self.assertTrue(target.exists())

        code, report = self.run_cli("restore", "1")

        self.assertEqual(code, 0)
        self.assertFalse(target.exists())
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
        before = self.snapshot()
        restore = make_unreadable(snapshots_root(self.filesystem, self.home))
        self.addCleanup(restore)

        code, report = self.run_cli("restore")

        restore()
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.snapshot(), before)

    def test_restoring_an_unreadable_generation_is_refused(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        self.filesystem.make_dir(snapshots_root(self.filesystem, self.home) / "000002")

        code, report = self.run_cli("restore", "2")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_restoring_with_nothing_ever_installed_is_refused(self):
        self.present()
        code, report = self.run_cli("restore")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class RetentionTest(RealHomeTestCase):
    def snapshots(self):
        return cli.snapshot_store(self.runtime())

    def test_a_sixth_generation_deletes_the_first_and_five_remain(self):
        self.present()
        for _ in range(6):
            self.run_cli("install", "--cli", CLI)
        self.assertEqual(self.snapshots().readable_generations(), [2, 3, 4, 5, 6])

    def test_retention_run_twice_does_not_fail(self):
        self.present()
        for _ in range(6):
            self.run_cli("install", "--cli", CLI)
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["retention"]["failed"], [])


class RetentionOnTheDoubleTest(FakeHomeTestCase):
    """One retention failure real permissions cannot reproduce.

    Making generation 1's removal fail while leaving generation 6's own
    creation unaffected needs the two to answer to different permissions,
    but both are a write to the very same parent directory — `snapshots/` —
    on a real POSIX filesystem, so no chmod can separate them. Locking that
    directory to block the removal blocks the new generation's own folder
    too, which fails the run before retention ever runs, for a different
    reason than the one this test exists to prove. The double can still tell
    the two apart, so this one test stays on it rather than being weakened
    into asserting something else.
    """

    def snapshots(self):
        return cli.snapshot_store(self.runtime())

    def test_a_retention_failure_leaves_the_command_successful_and_is_still_reported(self):
        self.present()
        for _ in range(5):
            self.run_cli("install", "--cli", CLI)
        self.filesystem.fail_remove_dir.add(snapshots_root(self.filesystem, self.home) / "000001")

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "installed")
        self.assertTrue(report["retention"]["failed"])
        self.assertIn(1, self.snapshots().readable_generations())


class HumanOutputTest(RealHomeTestCase):
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
        self.addCleanup(self.make_journal_unwritable())
        context = self.runtime()
        cli.main(["install", "--cli", CLI], runtime=context)
        self.assertNotIn("Nothing was changed", context.out.getvalue())


class ActivationTest(RealHomeTestCase):
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


class TerminalTest(unittest.TestCase):
    """Whether there is a person at a screen, which is what decides whether
    asking for nothing shows a menu or a usage line."""

    def test_a_closed_stream_is_nobody_rather_than_an_exception(self):
        """`isatty` raises on a closed file, and that is an answer, not a
        failure: a run whose input is gone has no one to show a menu to."""
        closed = io.StringIO()
        closed.close()
        with mock.patch.object(cli.sys, "stdin", closed), mock.patch.object(cli.sys, "stdout", closed):
            self.assertFalse(cli._attached_to_a_terminal())

    def test_a_redirected_output_is_not_a_terminal_even_with_a_real_stdin(self):
        both = [_Stream(True), _Stream(False)]
        with mock.patch.object(cli.sys, "stdin", both[0]), mock.patch.object(cli.sys, "stdout", both[1]):
            self.assertFalse(cli._attached_to_a_terminal())

    def test_both_ends_at_a_terminal_is_a_person(self):
        with mock.patch.object(cli.sys, "stdin", _Stream(True)), mock.patch.object(
            cli.sys, "stdout", _Stream(True)
        ):
            self.assertTrue(cli._attached_to_a_terminal())


class _Stream:
    def __init__(self, terminal: bool):
        self._terminal = terminal

    def isatty(self) -> bool:
        return self._terminal
