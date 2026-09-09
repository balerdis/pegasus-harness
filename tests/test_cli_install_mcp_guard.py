"""A bare `install` (no `--mcp`) against an installation that already has a
recorded MCP selection must refuse, not silently revoke it.

`install`'s own docstring says "silence about `--mcp` means select nothing,
because every `install` names its whole selection explicitly on the command
line" -- true and useful for a *first* install, but deadly for a *repeat*
one: an operator reinstalling for an unrelated reason (a new agent, a config
drift fix) who forgets to repeat `--mcp` was, before this guard, silently
telling Pegasus to tear down every MCP server, convention file and binding
it had recorded, with nothing on screen suggesting anything happened -- the
run still reports success, because from `install`'s point of view retiring
an unnamed server is not a failure, it is the documented contract working
exactly as designed.

`update` exists precisely to reapply a recorded selection with no flags, so
it must keep working through this guard unchanged -- it always calls
`install` with an explicit (possibly empty) `--mcp` reconstruction, never
with `mcp=None`, and this guard fires only on `mcp is None`.
"""
from __future__ import annotations

import io
import json

import pegasus
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=NO_BINARY
        )

    def layout(self):
        return available().get(CLI).layout(Environment(home=self.home))

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def store(self):
        return cli.journal_store(self.runtime())

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def installed(self):
        return journal_module.install_for(self.store().load(), CLI)

    def settings(self) -> dict:
        return json.loads(self.layout().settings_file.read_bytes())

    def snapshot(self) -> dict:
        return {path: path.read_bytes() for path in self.home.rglob("*") if path.is_file()}


class BareInstallOverARecordedSelectionTest(RealHomeTestCase):
    def test_is_refused(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        before = self.snapshot()
        before_journal = self.store().load()

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        # Nothing may change: no artifact, no journal, no snapshot entry --
        # the whole point of refusing before the preflight's first write.
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store().load(), before_journal)

    def test_names_the_recorded_selection(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")

        _, report = self.run_cli("install", "--cli", CLI)

        self.assertIn("context7", report["error"])

    def test_names_the_remedies(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")

        _, report = self.run_cli("install", "--cli", CLI)

        self.assertIn("update", report["error"])
        self.assertIn("--mcp", report["error"])
        self.assertIn("none", report["error"])

    def test_a_bound_server_also_counts_as_a_recorded_selection(self):
        """A binding writes no `/mcp/<id>` key -- `_mcp_entries` alone would
        see nothing here -- so the guard has to reuse the same
        classification `update` already draws, not just the configured-key
        half of it."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertNotEqual(code, 0)
        self.assertIn("cbm", report["error"])


class BareInstallDryRunOverARecordedSelectionTest(RealHomeTestCase):
    """The guard's whole purpose is to stop silent damage, and a dry run
    writes nothing -- so it must not refuse a dry run, only warn inside its
    report. Refusing the dry run too would take away the one command that
    lets a person ask "what would you retire?" before deciding anything,
    which is exactly how someone would go looking for this answer after
    hitting the real refusal once."""

    def test_still_reports_what_it_would_retire(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        before = self.snapshot()
        before_journal = self.store().load()

        code, report = self.run_cli("install", "--cli", CLI, "--dry-run")

        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "planned")
        self.assertEqual({item["id"] for item in report["retired"]}, {"mcp:context7", "mcp-convention:context7"})
        # Still a dry run: nothing changes just because this path is exempt
        # from the refusal.
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store().load(), before_journal)

    def test_carries_a_notice_that_a_real_run_would_refuse(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")

        _, report = self.run_cli("install", "--cli", CLI, "--dry-run")

        self.assertTrue(report.get("mcp_warnings"))
        notice = " ".join(report["mcp_warnings"])
        self.assertIn("context7", notice)
        self.assertIn("update", notice)
        self.assertIn("--mcp", notice)

    def test_a_bound_server_also_carries_the_notice(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")

        code, report = self.run_cli("install", "--cli", CLI, "--dry-run")

        self.assertEqual(code, 0)
        self.assertIn("cbm", " ".join(report["mcp_warnings"]))

    def test_a_first_install_dry_run_carries_no_notice(self):
        self.present()

        code, report = self.run_cli("install", "--cli", CLI, "--dry-run")

        self.assertEqual(code, 0)
        self.assertFalse(report.get("mcp_warnings"))

    def test_a_dry_run_over_a_recorded_empty_selection_carries_no_notice(self):
        self.present()
        self.run_cli("install", "--cli", CLI)

        code, report = self.run_cli("install", "--cli", CLI, "--dry-run")

        self.assertEqual(code, 0)
        self.assertFalse(report.get("mcp_warnings"))


class McpNoneTest(RealHomeTestCase):
    def test_revokes_the_recorded_selection_on_purpose(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")

        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "none")

        self.assertEqual(code, 0)
        self.assertNotIn("context7", self.settings().get("mcp", {}))
        self.assertNotIn("mcp:context7", {entry.id for entry in self.installed().entries})

    def test_cannot_be_combined_with_another_server(self):
        self.present()

        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "none", "--mcp", "cbm")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_cannot_be_combined_regardless_of_order(self):
        self.present()

        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "cbm", "--mcp", "none")

        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_writes_nothing_when_combined(self):
        self.present()
        before = self.snapshot()

        self.run_cli("install", "--cli", CLI, "--mcp", "none", "--mcp", "cbm")

        self.assertEqual(self.snapshot(), before)


class UnaffectedInstallsTest(RealHomeTestCase):
    def test_a_first_install_with_no_flags_still_works(self):
        self.present()

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertEqual(code, 0)

    def test_a_bare_reinstall_over_a_recorded_empty_selection_still_works(self):
        self.present()
        self.run_cli("install", "--cli", CLI)

        code, report = self.run_cli("install", "--cli", CLI)

        self.assertEqual(code, 0)


class UpdateStillWorksTest(RealHomeTestCase):
    """The single most important regression risk here: `update` reconstructs
    a selection and always passes it explicitly, so it must never trip the
    guard this change adds to a *bare* `install`."""

    def test_update_reapplies_a_recorded_mcp_selection(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")

        code, report = self.run_cli("update", "--cli", CLI)

        self.assertEqual(code, 0)
        self.assertIn("context7", self.settings().get("mcp", {}))

    def test_update_reapplies_a_bound_server(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")

        code, report = self.run_cli("update", "--cli", CLI)

        self.assertEqual(code, 0)

    def test_update_on_a_first_installs_empty_selection_still_works(self):
        self.present()
        self.run_cli("install", "--cli", CLI)

        code, report = self.run_cli("update", "--cli", CLI)

        self.assertEqual(code, 0)
