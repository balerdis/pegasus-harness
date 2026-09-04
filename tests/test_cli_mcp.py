"""`pegasus mcp grant|revoke|list`: MCP server keys the user administers.

Pegasus renders every agent with a deny-all baseline plus an allowlist of only
the servers it ships descriptors for. An agent's own permission block is
merged last by OpenCode, so a server the user installed and administers
themselves -- one Pegasus never heard of -- is a tool no agent can ever reach
unless something in this list names it. `mcp grant` is that lever: it records
the key on the installation's journal entry and reapplies the rendered
configuration so every agent's wildcard actually includes it.

Follows the same discipline as `test_cli_update.py`: real disk, a throwaway
home, and the double only where a real filesystem condition cannot be
produced.
"""
from __future__ import annotations

import io
import json
from dataclasses import replace

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import codecs, journal as journal_module, pointer
from pegasus.core.types import Codec, Environment
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

    def declare_own_mcp_server(self, key: str, value: dict | None = None) -> None:
        """What a user administering their own MCP server leaves behind in
        the CLI's own configuration -- a key under `/mcp` Pegasus never wrote."""
        layout = self.layout()
        document = codecs.loads(Codec.JSON, layout.settings_file.read_text(encoding="utf-8"))
        document = pointer.set_at(document, f"/mcp/{key}", value or {"type": "local", "command": ["jira-server"]})
        layout.settings_file.write_text(codecs.dumps(Codec.JSON, document), encoding="utf-8")

    def install(self, *extra) -> None:
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, *extra)
        self.assertEqual(code, 0)


class GrantTest(RealHomeTestCase):
    def test_grant_refuses_an_undeclared_key_and_names_what_is_available(self):
        self.install()
        self.declare_own_mcp_server("figma")
        code, report = self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("jira", report["error"])
        self.assertIn("figma", report["error"])

    def test_grant_refuses_when_nothing_is_declared(self):
        self.install()
        code, report = self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        self.assertNotEqual(code, 0)
        self.assertIn("jira", report["error"])

    def test_granting_a_declared_key_succeeds(self):
        self.install()
        self.declare_own_mcp_server("jira")
        code, report = self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        self.assertEqual(code, 0)
        self.assertEqual(report["action"], "grant")
        self.assertEqual(report["key"], "jira")
        self.assertIn("jira", report["granted"])

    def test_granting_persists_to_the_journal(self):
        self.install()
        self.declare_own_mcp_server("jira")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        self.assertIn("jira", self.installed().granted_mcp)

    def test_granting_reapplies_the_rendered_agent_permission(self):
        """The whole point: an agent's rendered `permission` block must
        actually carry the grant, not just the journal."""
        self.install()
        self.declare_own_mcp_server("jira")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        settings = self.settings()
        agents = settings.get("agent", {})
        self.assertTrue(agents, "expected at least one rendered agent")
        found_grant = any(
            entry.get("permission", {}).get("jira*") == "allow" for entry in agents.values()
        )
        self.assertTrue(found_grant, "no agent's rendered permission carries the jira grant")

    def test_grant_reports_a_restart_is_needed(self):
        self.install()
        self.declare_own_mcp_server("jira")
        code, report = self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        self.assertEqual(code, 0)
        self.assertTrue(report.get("activation"))

    def test_grant_without_an_installation_is_refused(self):
        self.present()
        code, report = self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_grant_with_an_unknown_cli_is_refused(self):
        code, report = self.run_cli("mcp", "grant", "--cli", "nonesuch", "jira")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_a_key_colliding_with_a_shipped_server_is_refused(self):
        self.install("--mcp", "context7")
        self.declare_own_mcp_server("context7")
        code, report = self.run_cli("mcp", "grant", "--cli", CLI, "context7")
        self.assertNotEqual(code, 0)
        self.assertIn("context7", report["error"])


class RevokeTest(RealHomeTestCase):
    def test_revoking_a_never_granted_key_reports_already_revoked_at_exit_0(self):
        self.install()
        code, report = self.run_cli("mcp", "revoke", "--cli", CLI, "jira")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "already-revoked")

    def test_revoking_a_granted_key_removes_it(self):
        self.install()
        self.declare_own_mcp_server("jira")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        code, report = self.run_cli("mcp", "revoke", "--cli", CLI, "jira")
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "revoked")
        self.assertNotIn("jira", self.installed().granted_mcp)

    def test_revoking_reapplies_the_rendered_permission(self):
        self.install()
        self.declare_own_mcp_server("jira")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        self.run_cli("mcp", "revoke", "--cli", CLI, "jira")
        settings = self.settings()
        agents = settings.get("agent", {})
        found_grant = any(
            entry.get("permission", {}).get("jira*") == "allow" for entry in agents.values()
        )
        self.assertFalse(found_grant, "revoked grant is still present in a rendered agent")

    def test_revoke_without_an_installation_is_refused(self):
        self.present()
        code, report = self.run_cli("mcp", "revoke", "--cli", CLI, "jira")
        self.assertNotEqual(code, 0)


class StaleGrantDoesNotAbortAnUnrelatedInstallTest(RealHomeTestCase):
    """A grant carried forward from a previous install must never abort an
    unrelated `install` just because a fresh `--mcp` binding happens to reuse
    the same key string -- see `cli.install`'s own comment on
    `droppable_grants` and `content.grant_mcp`'s docstring for the reasoning.
    """

    def test_a_stale_grant_colliding_with_a_fresh_binding_is_dropped_not_aborted(self):
        self.install()
        self.declare_own_mcp_server("jira-mcp")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira-mcp")
        self.assertIn("jira-mcp", self.installed().granted_mcp)

        # An unrelated install binds a shipped server ("cbm") under the exact
        # key string the earlier grant used. Nothing about this asks to grant
        # or revoke anything -- it is a plain --mcp selection.
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=jira-mcp")
        self.assertEqual(code, 0, report)

    def test_the_dropped_key_is_not_claimed_by_the_journal(self):
        self.install()
        self.declare_own_mcp_server("jira-mcp")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira-mcp")
        self.run_cli("install", "--cli", CLI, "--mcp", "cbm=jira-mcp")
        self.assertNotIn("jira-mcp", self.installed().granted_mcp)

    def test_the_report_names_the_dropped_key(self):
        self.install()
        self.declare_own_mcp_server("jira-mcp")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira-mcp")
        _code, report = self.run_cli("install", "--cli", CLI, "--mcp", "cbm=jira-mcp")
        self.assertTrue(report.get("grant_warnings"))
        self.assertTrue(any("jira-mcp" in warning for warning in report["grant_warnings"]))

    def test_an_explicit_same_invocation_collision_still_raises(self):
        """A key named explicitly in the very call that also binds it is a
        real contradiction, not a leftover -- `mcp grant` itself must still
        refuse it."""
        self.install("--mcp", "cbm=jira-mcp")
        self.declare_own_mcp_server("jira-mcp")
        code, report = self.run_cli("mcp", "grant", "--cli", CLI, "jira-mcp")
        self.assertNotEqual(code, 0)
        self.assertIn("jira-mcp", report["error"])

    def test_update_after_a_drop_is_a_no_op(self):
        self.install()
        self.declare_own_mcp_server("jira-mcp")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira-mcp")
        self.run_cli("install", "--cli", CLI, "--mcp", "cbm=jira-mcp")
        self.assertNotIn("jira-mcp", self.installed().granted_mcp)
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0, report)
        self.assertNotIn("jira-mcp", self.installed().granted_mcp)
        self.assertFalse(report.get("grant_warnings"))


class ListTest(RealHomeTestCase):
    def test_list_shows_no_grants_and_no_available_keys_at_first(self):
        self.install()
        code, report = self.run_cli("mcp", "list", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["granted"], [])
        self.assertEqual(report["available"], [])

    def test_list_shows_a_declared_but_ungranted_key_as_available(self):
        self.install()
        self.declare_own_mcp_server("jira")
        code, report = self.run_cli("mcp", "list", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["granted"], [])
        self.assertIn("jira", report["available"])

    def test_list_moves_a_granted_key_out_of_available(self):
        self.install()
        self.declare_own_mcp_server("jira")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        code, report = self.run_cli("mcp", "list", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["granted"], ["jira"])
        self.assertNotIn("jira", report["available"])


class UpdateReappliesGrantsTest(RealHomeTestCase):
    def test_update_reapplies_the_recorded_grant_with_no_flags(self):
        self.install()
        self.declare_own_mcp_server("jira")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertIn("jira", self.installed().granted_mcp)
        settings = self.settings()
        agents = settings.get("agent", {})
        found_grant = any(
            entry.get("permission", {}).get("jira*") == "allow" for entry in agents.values()
        )
        self.assertTrue(found_grant, "update did not reapply the recorded grant")


class DoctorReportsGrantedTest(RealHomeTestCase):
    def test_doctor_reports_granted_keys_distinctly_from_bound(self):
        self.install()
        self.declare_own_mcp_server("jira")
        self.run_cli("mcp", "grant", "--cli", CLI, "jira")
        code, report = self.run_cli("doctor")
        self.assertEqual(code, 0)
        entry = next(item for item in report["clis"] if item["cli"] == CLI)
        self.assertIn("jira", entry["mcp_granted"])
        self.assertNotIn("jira", [b["id"] for b in entry.get("mcp_bound", [])])

    def test_doctor_reports_no_granted_keys_when_none_are_granted(self):
        self.install()
        code, report = self.run_cli("doctor")
        entry = next(item for item in report["clis"] if item["cli"] == CLI)
        self.assertEqual(entry["mcp_granted"], [])


class ProseTest(RealHomeTestCase):
    def test_grant_reads_as_prose(self):
        self.install()
        self.declare_own_mcp_server("jira")
        context = self.runtime()
        cli.main(["mcp", "grant", "--cli", CLI, "jira"], runtime=context)
        self.assertIn("jira", context.out.getvalue())

    def test_revoke_reads_as_prose(self):
        self.install()
        context = self.runtime()
        cli.main(["mcp", "revoke", "--cli", CLI, "jira"], runtime=context)
        self.assertIn("jira", context.out.getvalue())

    def test_list_reads_as_prose(self):
        self.install()
        context = self.runtime()
        cli.main(["mcp", "list", "--cli", CLI], runtime=context)
        out = context.out.getvalue()
        self.assertTrue(out.strip())

    def test_missing_subcommand_is_an_error(self):
        code, report = self.run_cli("mcp")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


if __name__ == "__main__":
    import unittest

    unittest.main()
