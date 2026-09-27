"""`pegasus mcp grant`/`revoke` across every registered adapter -- derived
from `adapters.available()` rather than a hand-written CLI list, so a third
adapter this product ships later is exercised here without anyone having to
remember to add it.

Before this change, Claude Code's own `mcp grant` for a self-administered
(bound) server key recorded the key, reapplied, and reported
`"claudecode: granted <key> to every agent."` while writing nothing into any
agent file: no `mcpServers:` and no `disallowedTools:` change anywhere under
`~/.claude` -- only the journal and the generated
`delegation-capabilities.md` moved. The report claimed an effect the command
never had, the same class of false success `directory grant` already had
fixed for the same CLI (see `test_cli_directory_all_clis.py`).

`CliAdapter.mcp_grant_behavior()` -- `writes_per_agent_entry` -- is what
makes the report honest instead: OpenCode declares `True` (it writes each
granted agent's own `permission` entry), Claude Code declares `False` (its
own `mcpServers:`/`disallowedTools:` vocabulary has no per-agent place a
self-administered key ever lands). `cli.mcp_grant`/`cli.mcp_revoke` read
this fact off the adapter, never by comparing `adapter.id` against a
literal -- the same hexagonal rule `test_cli_directory_all_clis.py` already
guards for directory grants.

`figma` plays the same "user's own server" role `test_cli_mcp.py` already
uses throughout.
"""
from __future__ import annotations

import io
import json

from pegasus import cli
from pegasus.adapters import available
from pegasus.adapters.claudecode.manifest import CLI_ID as CLAUDECODE_CLI_ID
from pegasus.adapters.opencode.manifest import CLI_ID as OPENCODE_CLI_ID
from pegasus.core import codecs, pointer
from pegasus.core.types import Codec, Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
NO_BINARY = {"PATH": ""}


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO(), variables=NO_BINARY
        )

    def layout(self, cli_id: str):
        return available().get(cli_id).layout(Environment(home=self.home))

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def run_prose(self, *argv) -> tuple[int, str]:
        context = self.runtime()
        code = cli.main(list(argv), runtime=context)
        return code, context.out.getvalue()

    def install(self, cli_id: str) -> None:
        self.layout(cli_id).config_dir.mkdir(parents=True, exist_ok=True)
        code, _ = self.run_cli("install", "--cli", cli_id)
        self.assertEqual(code, 0)

    def declare_own_mcp_server(self, cli_id: str, key: str) -> None:
        """What a user administering their own MCP server leaves behind in
        the CLI's own configuration -- a key under `/mcp` Pegasus never
        wrote. Mirrors `test_cli_mcp.py`'s own fixture; `_declared_mcp_keys`
        reads this same shape off `layout.settings_file` for every adapter."""
        layout = self.layout(cli_id)
        document = codecs.loads(Codec.JSON, layout.settings_file.read_text(encoding="utf-8"))
        document = pointer.set_at(document, f"/mcp/{key}", {"type": "local", "command": ["figma-server"]})
        layout.settings_file.write_text(codecs.dumps(Codec.JSON, document), encoding="utf-8")


class GrantSucceedsForEveryRegisteredAdapterTest(RealHomeTestCase):
    def test_grant_records_the_key_for_every_adapter(self):
        for cli_id in available().ids():
            with self.subTest(cli=cli_id):
                self.install(cli_id)
                key = f"{cli_id}-figma"
                self.declare_own_mcp_server(cli_id, key)
                code, report = self.run_cli("mcp", "grant", "--cli", cli_id, key)
                self.assertEqual(code, 0, report)
                self.assertEqual(report["action"], "grant")
                self.assertIn(key, report["granted"])

    def test_revoke_is_a_no_op_at_exit_0_for_every_adapter_that_never_granted(self):
        for cli_id in available().ids():
            with self.subTest(cli=cli_id):
                self.install(cli_id)
                code, report = self.run_cli("mcp", "revoke", "--cli", cli_id, f"{cli_id}-never-granted")
                self.assertEqual(code, 0, report)
                self.assertEqual(report["status"], "already-revoked")


class ReportTextIsHonestPerAdapterTest(RealHomeTestCase):
    """OpenCode's report keeps its existing wording -- `test_cli_mcp.py`
    already covers it end to end. Claude Code's report must no longer claim
    `granted` without disclosing that nothing was written to any agent
    file, and that reachability depends on how the server is configured in
    Claude Code itself."""

    def test_opencode_report_says_granted_to_every_agent(self):
        self.install(OPENCODE_CLI_ID)
        self.declare_own_mcp_server(OPENCODE_CLI_ID, "figma")
        _, output = self.run_prose("mcp", "grant", "--cli", OPENCODE_CLI_ID, "figma")
        self.assertIn("granted figma to every agent", output)

    def test_opencode_revoke_says_revoked(self):
        self.install(OPENCODE_CLI_ID)
        self.declare_own_mcp_server(OPENCODE_CLI_ID, "figma")
        self.run_cli("mcp", "grant", "--cli", OPENCODE_CLI_ID, "figma")
        _, output = self.run_prose("mcp", "revoke", "--cli", OPENCODE_CLI_ID, "figma")
        self.assertIn("revoked figma", output)

    def test_claudecode_grant_report_discloses_no_per_agent_write(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        code, report = self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertEqual(code, 0, report)
        self.assertFalse(report["writes_per_agent_entry"])
        self.assertTrue(report["grant_warnings"])
        self.assertIn("figma", report["grant_warnings"][0])

    def test_claudecode_grant_prose_is_honest(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        _, output = self.run_prose("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertIn("recorded figma", output)
        self.assertIn("nothing was written to any agent file", output)
        self.assertIn("claudecode", output)
        self.assertIn("configured in", output)
        self.assertNotIn("granted figma to every agent", output)

    def test_claudecode_revoke_prose_is_honest(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        _, output = self.run_prose("mcp", "revoke", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertIn("figma", output)
        self.assertIn("removed from the record", output)
        self.assertIn("nothing was written to any agent file", output)
        self.assertNotIn("revoked figma", output)

    def test_the_report_text_is_derived_from_each_adapters_declared_behavior(self):
        """The load-bearing guard: build the expected sentence purely from
        `adapter.mcp_grant_behavior()` -- never from `adapter.id` -- for
        every registered adapter, and check the real report/prose matches.
        A future adapter registered with a different id, or a different
        `writes_per_agent_entry`, is covered by this loop without anyone
        adding a branch for it."""
        for cli_id in available().ids():
            with self.subTest(cli=cli_id):
                self.install(cli_id)
                key = f"{cli_id}-derived"
                self.declare_own_mcp_server(cli_id, key)
                behavior = available().get(cli_id).mcp_grant_behavior()
                code, report = self.run_cli("mcp", "grant", "--cli", cli_id, key)
                self.assertEqual(code, 0, report)
                self.assertEqual(report["writes_per_agent_entry"], behavior.writes_per_agent_entry)
                prose_key = f"{cli_id}-derived-prose"
                self.declare_own_mcp_server(cli_id, prose_key)
                _, output = self.run_prose("mcp", "grant", "--cli", cli_id, prose_key)
                if behavior.writes_per_agent_entry:
                    self.assertIn("to every agent", output)
                else:
                    self.assertIn("nothing was written to any agent file", output)


class ClaudeCodeGrantWritesNothingButTheJournalAndDelegationCapabilitiesTest(RealHomeTestCase):
    def test_grant_changes_nothing_else_under_the_claude_config_dir(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        layout = self.layout(CLAUDECODE_CLI_ID)
        before = {
            str(path.relative_to(layout.config_dir)): path.read_bytes()
            for path in layout.config_dir.rglob("*")
            if path.is_file()
        }
        code, report = self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertEqual(code, 0, report)
        after = {
            str(path.relative_to(layout.config_dir)): path.read_bytes()
            for path in layout.config_dir.rglob("*")
            if path.is_file()
        }
        changed = {
            name for name in set(before) | set(after) if before.get(name) != after.get(name)
        }
        self.assertEqual(
            changed,
            {"skills/_shared/delegation-capabilities.md"},
            f"a dormant grant must change nothing else under {layout.config_dir}, got {changed}",
        )
        self.assertNoMcpServersOrDisallowedToolsChanged(before, after)

    def assertNoMcpServersOrDisallowedToolsChanged(self, before: dict, after: dict) -> None:
        for name, content in after.items():
            if not name.endswith(".md") or name == "skills/_shared/delegation-capabilities.md":
                continue
            self.assertEqual(before.get(name), content, f"{name} changed but should not have")
            self.assertNotIn(b"mcpServers:", content)


class NoAdapterIdComparisonDrivesTheReportTest(RealHomeTestCase):
    """Static guard, mirroring `test_cli_directory_all_clis.py`'s own: every
    fact `mcp_grant`/`mcp_revoke` report about what a grant actually does
    must come from the adapter's own declared `McpGrantBehavior`, never from
    comparing `adapter.id` against a literal."""

    def test_mcp_grant_never_compares_adapter_id(self):
        import inspect

        source = inspect.getsource(cli.mcp_grant)
        self.assertIn("mcp_grant_behavior", source)
        self.assertNotIn("adapter.id ==", source)
        self.assertNotIn("adapter.id !=", source)
        self.assertNotIn("CLAUDECODE_CLI_ID", source)
        self.assertNotIn("OPENCODE_CLI_ID", source)

    def test_mcp_revoke_never_compares_adapter_id(self):
        import inspect

        source = inspect.getsource(cli.mcp_revoke)
        self.assertIn("mcp_grant_behavior", source)
        self.assertNotIn("adapter.id ==", source)
        self.assertNotIn("adapter.id !=", source)
        self.assertNotIn("CLAUDECODE_CLI_ID", source)
        self.assertNotIn("OPENCODE_CLI_ID", source)

    def test_mcp_prose_never_compares_adapter_id(self):
        import inspect

        source = inspect.getsource(cli._mcp_prose)
        self.assertNotIn("adapter.id ==", source)
        self.assertNotIn("adapter.id !=", source)
        self.assertNotIn("CLAUDECODE_CLI_ID", source)
        self.assertNotIn("OPENCODE_CLI_ID", source)
        self.assertNotIn("'claudecode'", source)
        self.assertNotIn('"claudecode"', source)


if __name__ == "__main__":
    import unittest

    unittest.main()
