"""`pegasus mcp grant`/`revoke` across every registered adapter -- derived
from `adapters.available()` rather than a hand-written CLI list, so a third
adapter this product ships later is exercised here without anyone having to
remember to add it.

Before 7.3.3, Claude Code's own `mcp grant` for a self-administered (bound)
server key recorded the key, reapplied, and reported `"claudecode: granted
<key> to every agent."` while writing nothing into any agent file: no
`mcpServers:` and no `disallowedTools:` change anywhere under `~/.claude` --
only the journal and the generated `delegation-capabilities.md` moved. The
report claimed an effect the command never had, the same class of false
success `directory grant` already had fixed for the same CLI (see
`test_cli_directory_all_clis.py`). Measured on 2026-09-27 with a throwaway
Claude Code user: a sub-agent with no `mcpServers:` entry for a
user-configured server never reached its tools, before or after the grant --
`core.catalog.render` built the `mcp` tuple `render_agent` received entirely
from `item.optional_mcp`, never `item.granted_mcp`.

7.3.3 closes the gap: `core.catalog._mcp_for_agent` folds `item.granted_mcp`
in alongside `item.optional_mcp`, as a bound-reference descriptor (see
`test_catalog.py::RenderAgentGrantedMcpTest`), so a granted key now reaches
every agent's own `mcpServers:` frontmatter, the session identity's own
`tools:` included (`test_claudecode_adapter.py::SessionIdentityMcpToolsTest`).

`CliAdapter.mcp_grant_behavior()` -- `writes_per_agent_entry` -- is what
makes the report honest: both adapters now declare `True` (OpenCode writes
each granted agent's own `permission` entry; Claude Code writes each granted
agent's own `mcpServers:` entry). `cli.mcp_grant`/`cli.mcp_revoke` read this
fact off the adapter, never by comparing `adapter.id` against a literal --
the same hexagonal rule `test_cli_directory_all_clis.py` already guards for
directory grants.

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
    """Both adapters now declare `writes_per_agent_entry=True`: each writes
    every granted agent's own per-agent entry (OpenCode's `permission`,
    Claude Code's `mcpServers:`), so both reports keep the plain "granted ...
    to every agent" wording -- `test_cli_mcp.py` already covers OpenCode's
    end to end, this covers Claude Code's."""

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

    def test_claudecode_grant_report_no_longer_discloses_a_gap(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        code, report = self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertEqual(code, 0, report)
        self.assertTrue(report["writes_per_agent_entry"])
        self.assertFalse(report.get("grant_warnings"))

    def test_claudecode_grant_prose_says_granted_to_every_agent(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        _, output = self.run_prose("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertIn("granted figma to every agent", output)
        self.assertNotIn("nothing was written to any agent file", output)

    def test_claudecode_revoke_prose_says_revoked(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        _, output = self.run_prose("mcp", "revoke", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertIn("revoked figma", output)
        self.assertNotIn("nothing was written to any agent file", output)

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


class ClaudeCodeGrantWritesIntoEveryAgentFileTest(RealHomeTestCase):
    """The fix for the gap the class name above used to certify: every agent
    file now carries a bare `mcpServers:` reference to the granted key, the
    same bound-reference shape `_mcp_servers_field` already writes for a
    shipped server bound to a user-administered key -- proven here by
    reading the real, on-disk bytes an install actually produced, not an
    intermediate shape."""

    def test_grant_writes_the_key_into_every_agent_file(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        layout = self.layout(CLAUDECODE_CLI_ID)
        code, report = self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertEqual(code, 0, report)
        agent_files = sorted(layout.agents_dir.glob("*.md"))
        self.assertTrue(agent_files)
        for path in agent_files:
            content = path.read_bytes()
            self.assertIn(b"mcpServers:", content, f"{path.name} carries no mcpServers: entry")
            self.assertIn(b'"figma"', content, f"{path.name} does not reference the granted key")

    def test_the_session_identity_agent_also_gets_the_server_level_tool(self):
        """Fix 1's `mcp__<key>` server-level tool entry, threaded through the
        same grant, for whichever agent `settings.json`'s `agent` key names."""
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        layout = self.layout(CLAUDECODE_CLI_ID)
        code, report = self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertEqual(code, 0, report)
        document = codecs.loads(Codec.JSON, layout.settings_file.read_text(encoding="utf-8"))
        orchestrator_name = pointer.get_at(document, "/agent")
        content = (layout.agents_dir / f"{orchestrator_name}.md").read_bytes()
        self.assertIn(b"mcp__figma", content)
        self.assertIn(b"ToolSearch", content)

    def test_revoke_removes_the_key_from_every_agent_file(self):
        self.install(CLAUDECODE_CLI_ID)
        self.declare_own_mcp_server(CLAUDECODE_CLI_ID, "figma")
        self.run_cli("mcp", "grant", "--cli", CLAUDECODE_CLI_ID, "figma")
        layout = self.layout(CLAUDECODE_CLI_ID)
        code, report = self.run_cli("mcp", "revoke", "--cli", CLAUDECODE_CLI_ID, "figma")
        self.assertEqual(code, 0, report)
        for path in sorted(layout.agents_dir.glob("*.md")):
            content = path.read_bytes()
            self.assertNotIn(b'"figma"', content, f"{path.name} still references the revoked key")


class OpenCodeRenderIsByteIdenticalAcrossTheCatalogChangeTest(RealHomeTestCase):
    """The brief's own hard requirement: threading `item.granted_mcp` through
    `core.catalog._mcp_for_agent` (the fix for Claude Code) must produce
    *exactly* the same OpenCode bytes as before that change -- OpenCode's own
    `render_agent` ignores the `mcp` parameter entirely and reads `item.
    granted_mcp` straight off the `Agent` it already has (see its own
    docstring), so enlarging that tuple must be inert for this CLI.

    Proven two ways: at the render call itself (`render_agent` produces
    identical bytes whether `mcp` is empty or carries the new descriptors),
    and at the integration level, by literally reinstating the pre-fix
    `_mcp_for_agent` (shipped servers only, the exact code this function
    replaced) and diffing a full OpenCode install's on-disk bytes against
    one built with the real, current implementation.
    """

    def test_render_agent_is_the_same_regardless_of_the_mcp_tuple(self):
        from dataclasses import replace as _replace

        from pegasus.adapters import opencode
        from pegasus.core.content import Agent, AgentMode, Distribution, Mcp

        adapter = opencode.Adapter()
        layout = adapter.layout(Environment(home=self.home))
        agent = Agent(
            name="probe-agent",
            description="d",
            body="body",
            mode=AgentMode.SUBAGENT,
            source=__import__("pathlib").PurePosixPath("agents/probe-agent.md"),
            granted_mcp=("figma",),
        )
        descriptor = Mcp(
            name="figma",
            description="d",
            body="b",
            distribution=Distribution.REMOTE,
            endpoint="",
            source=__import__("pathlib").PurePosixPath("mcp/figma-granted"),
            bound_to="figma",
        )
        without = adapter.render_agent(layout, agent, mcp=())
        with_descriptor = adapter.render_agent(layout, agent, mcp=(descriptor,))
        self.assertEqual(
            [(a.path, a.content) for a in without if hasattr(a, "content")],
            [(a.path, a.content) for a in with_descriptor if hasattr(a, "content")],
        )

    def test_a_full_install_is_byte_identical_to_the_pre_fix_catalog(self):
        from unittest import mock

        from pegasus.core import catalog as catalog_module

        def pre_fix_mcp_for_agent(item, mcp_by_key):
            """The exact body `core.catalog._mcp_for_agent` replaced: only
            `item.optional_mcp`, resolved against the shipped descriptors,
            with `item.granted_mcp` never consulted at all."""
            return tuple(mcp_by_key[key] for key in item.optional_mcp if key in mcp_by_key)

        self.install(OPENCODE_CLI_ID)
        self.declare_own_mcp_server(OPENCODE_CLI_ID, "figma")
        code, _ = self.run_cli("mcp", "grant", "--cli", OPENCODE_CLI_ID, "figma")
        self.assertEqual(code, 0)
        layout = self.layout(OPENCODE_CLI_ID)
        after_fix = {
            str(path.relative_to(layout.config_dir)): path.read_bytes()
            for path in layout.config_dir.rglob("*")
            if path.is_file()
        }

        # Rebuild the same install from scratch with the pre-fix function
        # reinstated, in a second, disposable real home.
        second_home = self.filesystem_home_for_pre_fix_rebuild()
        with mock.patch.object(catalog_module, "_mcp_for_agent", pre_fix_mcp_for_agent):
            runtime = cli.Runtime(
                filesystem=self.filesystem,
                home=second_home,
                now=AT,
                out=io.StringIO(),
                variables=NO_BINARY,
            )
            pre_fix_layout = available().get(OPENCODE_CLI_ID).layout(Environment(home=second_home))
            pre_fix_layout.config_dir.mkdir(parents=True, exist_ok=True)
            code = cli.main(["install", "--cli", OPENCODE_CLI_ID, "--json"], runtime=runtime)
            self.assertEqual(code, 0)
            document = codecs.loads(
                Codec.JSON, pre_fix_layout.settings_file.read_text(encoding="utf-8")
            )
            document = pointer.set_at(
                document, "/mcp/figma", {"type": "local", "command": ["figma-server"]}
            )
            pre_fix_layout.settings_file.write_text(codecs.dumps(Codec.JSON, document), encoding="utf-8")
            code = cli.main(
                ["mcp", "grant", "--cli", OPENCODE_CLI_ID, "figma", "--json"], runtime=runtime
            )
            self.assertEqual(code, 0)
            # Content, not just structure: the two homes have different
            # absolute paths, and this install's own permission scoping names
            # its skills directory by that absolute path, so the second
            # home's own path is normalised back to the first's before the
            # comparison -- the one difference this rebuild is expected to
            # produce, and it has nothing to do with `_mcp_for_agent`.
            pre_fix = {
                str(path.relative_to(pre_fix_layout.config_dir)): path.read_bytes().replace(
                    str(second_home).encode("utf-8"), str(self.home).encode("utf-8")
                )
                for path in pre_fix_layout.config_dir.rglob("*")
                if path.is_file()
            }
        self.assertEqual(after_fix, pre_fix)

    def filesystem_home_for_pre_fix_rebuild(self):
        second_home = self.home.parent / (self.home.name + "-pre-fix")
        second_home.mkdir(parents=True, exist_ok=True)
        return second_home


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
