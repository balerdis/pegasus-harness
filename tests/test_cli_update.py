"""`pegasus update`: reapply an installation's own selection, with no flags.

A bare reinstall retires every MCP server not named on `--mcp` again, so
updating an existing installation used to mean remembering and repeating the
exact `--mcp` selection it was given the first time -- and a bound server's
selection cannot even be recovered from the rendered configuration, since a
binding writes no `/mcp/<id>` key there. `update` reads the recorded
installation instead and reapplies exactly that.
"""
from __future__ import annotations

import io
import json
from dataclasses import replace

import pegasus
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import content as content_module
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


class UpdateReapplyTest(RealHomeTestCase):
    def test_the_report_names_update_as_its_command(self):
        self.present()
        self.run_cli("install", "--cli", CLI)
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["command"], "update")
        self.assertEqual(report["schema"], cli.SCHEMA)

    def test_a_bound_server_is_reapplied_and_not_retired(self):
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")
        self.assertEqual(code, 0)
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(self.installed().mcp_bindings, {"cbm": "codebase-memory-mcp"})
        # A retired binding would show up here, since the convention id is
        # only ever placed while its server is still selected.
        self.assertFalse(
            any(item["id"] == "mcp-convention:cbm" for item in report.get("retired", []))
        )
        self.assertNotIn("cbm", self.settings().get("mcp", {}))

    def test_a_configured_non_bound_server_is_kept(self):
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        self.assertEqual(code, 0)
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertIn("context7", self.settings().get("mcp", {}))
        self.assertFalse(
            any(item["id"] == "mcp:context7" for item in report.get("retired", []))
        )

    def test_dry_run_reports_the_plan_without_writing_anything(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "context7")
        before = self.snapshot()
        code, report = self.run_cli("update", "--cli", CLI, "--dry-run")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "planned")
        self.assertEqual(self.snapshot(), before)

    def test_nothing_installed_is_refused_and_names_install(self):
        self.present()
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("install", report["error"])

    def test_an_unbound_recorded_key_is_refused_rather_than_guessed(self):
        """An install predating `mcp_bindings` has a bound convention with no
        recorded key. Reapplying without it would retire the very binding
        `update` exists to preserve, which is worse than refusing.
        """
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")
        self.assertEqual(code, 0)
        store = self.store()
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        store.save(journal_module.with_install(journal, replace(install, mcp_bindings={})))

        code, report = self.run_cli("update", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("cbm", report["error"])
        self.assertIn(f"pegasus install --cli {CLI} --mcp cbm=<key>", report["error"])
        self.assertIn("update", report["error"])

    def test_the_refusal_tells_the_person_to_replace_the_placeholder(self):
        """Copied verbatim -- a very common habit -- `--mcp cbm=<key>` bounces
        off `parse_mcp_choice`'s cryptic rejection of the literal string
        `<key>`. The refusal must say, in plain words, to replace it before
        running the command, using the same source `doctor`'s matching line
        uses so the two can never drift apart on how they explain it.
        """
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp")
        self.assertEqual(code, 0)
        store = self.store()
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        store.save(journal_module.with_install(journal, replace(install, mcp_bindings={})))

        code, report = self.run_cli("update", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertEqual(report["error"], cli._unresolved_bindings_message(CLI, ["cbm"]))
        self.assertIn(cli.mcp_placeholder_instruction(), report["error"])
        self.assertIn("<key>", cli.mcp_placeholder_instruction())

    def test_the_refusal_names_every_affected_id(self):
        self.present()
        code, _ = self.run_cli(
            "install", "--cli", CLI, "--mcp", "cbm=codebase-memory-mcp", "--mcp", "context7=my-context7"
        )
        self.assertEqual(code, 0)
        store = self.store()
        journal = store.load()
        install = journal_module.install_for(journal, CLI)
        store.save(journal_module.with_install(journal, replace(install, mcp_bindings={})))

        code, report = self.run_cli("update", "--cli", CLI)
        self.assertNotEqual(code, 0)
        self.assertIn(
            f"pegasus install --cli {CLI} --mcp cbm=<key> --mcp context7=<key>", report["error"]
        )
