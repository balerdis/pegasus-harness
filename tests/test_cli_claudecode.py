"""The engine driving the `claudecode` adapter, not just its renderer.

`tests/test_build_catalog.py::test_works_for_every_registered_cli_not_just_the_default`
already proves every agent, command and skill renders through `claudecode`'s
`render.py`. What no test proved, before this file, is that the ENGINE --
`install`, `doctor`, `uninstall`, drift detection -- ever runs against this
adapter at all: every end-to-end suite (`test_installation.py`, most of
`test_cli.py`) is pinned to `CLI = "opencode"`, on purpose, because they
exercise capabilities (`mcp`, `per_agent_model`, subagents declared inside the
settings file, the `apply_patch` scoping plugin) that only OpenCode declares.
`claudecode` declares `skills`, `system_prompt`, `slash_commands` and
`sub_agents` -- deliberately not `prompts`, `mcp` or `per_agent_model` -- so
this file drives the real engine against a real throwaway home and asserts
only what this adapter actually promises: artifacts on disk at *this*
adapter's own paths, a clean `doctor` report after install, a full teardown on
`uninstall`, and drift detection catching a hand-edited artifact.

A focused new file rather than parameterizing `test_installation.py`: that
suite's own assertions (the `apply_patch` plugin landing on disk,
`subagent_depth` being claimed, a per-agent `model` key) are OpenCode-only by
design, and forcing them over both adapters would either fail honestly on
`claudecode` or have to be weakened -- neither of which improves that file.
This module reuses its throwaway-home discipline and `tests/test_cli.py`'s
`cli_entry`-by-id lookup instead of inventing a third style.

Real disk throughout, via `RealHomeTestCase` -- the same base every other CLI
suite in this repository builds on.
"""
from __future__ import annotations

import io
import json

from pegasus import cli
from pegasus.adapters import available
from pegasus.adapters.claudecode import render as render_module
from pegasus.core import journal as journal_module
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = "claudecode"
NO_BINARY = {"PATH": ""}
ORCHESTRATOR_AGENT = "pegasus-orchestrator"


def cli_entry(report, cli_id: str = CLI):
    """`report["clis"]`'s entry for `cli_id`, never a positional index.

    `doctor`'s report lists every registered adapter sorted by id, so which
    index is "this adapter's own entry" depends on how many adapters are
    registered and in what order. Every test below looks its entry up by id
    instead, the same discipline `tests/test_cli.py`'s own `cli_entry` uses.
    """
    return next(entry for entry in report["clis"] if entry["cli"] == cli_id)


class RealHomeTestCase(_RealHomeTestCase):
    """The generic real-home base, plus what driving `cli.main` needs."""

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

    def installed(self):
        return journal_module.install_for(self.store().load(), CLI)

    def install(self, *extra) -> dict:
        self.present()
        code, report = self.run_cli("install", "--cli", CLI, *extra)
        self.assertEqual(code, 0, report)
        return report


class InstallTest(RealHomeTestCase):
    """Every capability this adapter declares actually lands on disk."""

    def test_install_lands_agents_skills_commands_system_prompt_and_the_agent_key(self):
        self.install()
        layout = self.layout()

        agent_files = sorted(p.name for p in layout.agents_dir.glob("*.md"))
        self.assertIn(f"{ORCHESTRATOR_AGENT}.md", agent_files)
        self.assertGreater(len(agent_files), 1, "expected more than just the orchestrator agent")

        skill_dirs = sorted(p.name for p in layout.skills_dir.iterdir() if p.is_dir())
        self.assertTrue(skill_dirs, "expected at least one rendered skill directory")
        self.assertTrue(
            any((layout.skills_dir / name / "SKILL.md").is_file() for name in skill_dirs),
            "expected at least one SKILL.md under the skills directory",
        )

        command_files = sorted(p.name for p in layout.commands_dir.glob("*.md"))
        self.assertTrue(command_files, "expected at least one rendered slash command")

        system_prompt = layout.config_dir / "rules" / "pegasus.md"
        self.assertTrue(system_prompt.is_file())
        self.assertGreater(len(system_prompt.read_bytes()), 0)

        settings = json.loads(layout.settings_file.read_bytes())
        self.assertEqual(settings["agent"], ORCHESTRATOR_AGENT)

    def test_the_orchestrator_agent_file_names_itself_in_its_own_frontmatter(self):
        """Real file contents, not merely a path existing: the rendered
        agent's frontmatter must actually declare the same name `settings.
        json`'s `agent` key points at, or the two would silently disagree."""
        self.install()
        layout = self.layout()
        body = (layout.agents_dir / f"{ORCHESTRATOR_AGENT}.md").read_text(encoding="utf-8")
        self.assertTrue(body.startswith("---\n"))
        self.assertIn(f'name: "{ORCHESTRATOR_AGENT}"', body)

    def test_installing_twice_writes_nothing_new(self):
        self.install()
        layout = self.layout()
        before = {
            path: path.read_bytes() for path in layout.config_dir.rglob("*") if path.is_file()
        }
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["updated"], [])
        self.assertEqual(report["created"], [])
        after = {path: path.read_bytes() for path in layout.config_dir.rglob("*") if path.is_file()}
        self.assertEqual(after, before)


class DoctorTest(RealHomeTestCase):
    def test_doctor_reports_a_fresh_install_as_present_and_clean(self):
        self.install()
        _, report = self.run_cli("doctor")
        entry = cli_entry(report)
        self.assertTrue(entry["pegasus_installed"])
        self.assertGreater(entry["artifacts"], 0)
        self.assertEqual(entry["drifted"], [])
        self.assertEqual(entry["missing"], [])

    def test_doctor_reports_a_clean_home_as_not_installed(self):
        self.present()
        _, report = self.run_cli("doctor")
        self.assertFalse(cli_entry(report)["pegasus_installed"])


class DoctorMcpTest(RealHomeTestCase):
    """Claude Code's `render_mcp` writes no `/mcp/<id>` configuration key for
    any server it grants -- bound or not (see `render.mcp`'s own docstring):
    the definition lives inside each granted agent's own `mcpServers:`
    frontmatter instead. Every server this adapter installs normally
    therefore leaves the exact same journal shape a binding does: a
    `mcp-convention:<id>` entry with no `mcp:<id>` key beside it, and no
    recorded `mcp_bindings` entry either.

    Before `CliAdapter.writes_mcp_config_key` existed, `_bound_checks` read
    that shape as "granted but not installed by Pegasus" regardless of
    adapter, which made a real install of five servers Pegasus itself
    obtained and administers (`cbm`, `context7`, `engram`, `jira`,
    `playwright`) get reported as five servers the user administers, with a
    remedy command telling them to re-bind servers Pegasus already owns.

    `context7` and `jira` stand in for the five here: both ship
    `distribution: remote` (see `content/mcp/context7.md`,
    `content/mcp/jira.md`), so granting them unbound needs no download and no
    `npm`/binary on `PATH` -- exactly what `cbm`, `engram` and `playwright`
    would need, and exactly the kind of real filesystem/network condition
    this suite's `no_network` guard refuses on purpose. The shape this test
    reproduces (a convention entry, no config key, no recorded binding) is
    identical regardless of which shipped server produces it.
    """

    def test_servers_pegasus_installed_are_not_reported_as_user_administered(self):
        self.install("--mcp", "context7", "--mcp", "jira")
        _, report = self.run_cli("doctor")
        entry = cli_entry(report)
        self.assertEqual(entry["mcp_bound"], [])

    def test_the_prose_report_says_nothing_about_administering_them(self):
        self.install("--mcp", "context7", "--mcp", "jira")
        _, output = self.run_prose("doctor")
        self.assertNotIn("you administer", output)
        self.assertNotIn("MCP servers granted with no configuration", output)

    def test_a_genuine_binding_is_still_reported_as_administered(self):
        """The false positive above must not take the true positive with it:
        `--mcp id=key` still asks Pegasus to grant tools for a server the
        user runs and administers themselves, and that fact is still worth
        reporting."""
        self.install("--mcp", "cbm=codebase-memory-mcp")
        _, report = self.run_cli("doctor")
        entry = cli_entry(report)
        self.assertEqual([check["id"] for check in entry["mcp_bound"]], ["cbm"])
        self.assertEqual(entry["mcp_bound"][0]["key"], "codebase-memory-mcp")
        self.assertIn("administer", entry["mcp_bound"][0]["detail"])

    def test_update_reapplies_pegasus_installed_servers_without_asking_for_a_key(self):
        """The same false shape used to make `update` refuse outright,
        telling the operator to supply a key for a server nobody bound --
        see `cli._mcp_update_selection`."""
        self.install("--mcp", "context7", "--mcp", "jira")
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0, report)
        entry = cli_entry(self.run_cli("doctor")[1])
        self.assertEqual(entry["mcp_bound"], [])
        self.assertEqual(entry["drifted"], [])
        self.assertEqual(entry["missing"], [])


class UninstallTest(RealHomeTestCase):
    def test_uninstall_removes_the_artifacts_and_forgets_the_install(self):
        self.install()
        layout = self.layout()
        orchestrator_file = layout.agents_dir / f"{ORCHESTRATOR_AGENT}.md"
        self.assertTrue(orchestrator_file.exists())

        code, report = self.run_cli("uninstall", "--cli", CLI)

        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "uninstalled")
        self.assertTrue(report["removed"])
        self.assertFalse(orchestrator_file.exists())
        remaining_files = [p for p in layout.config_dir.rglob("*") if p.is_file() and p.stat().st_size > 0]
        # The one file this adapter never fully empties is `settings.json`,
        # left behind holding whatever the user's own keys were (here: none,
        # so an empty `{}` document, non-empty text but zero owned content).
        remaining_files = [p for p in remaining_files if p != layout.settings_file]
        self.assertEqual(remaining_files, [])
        self.assertIsNone(journal_module.install_for(self.store().load(), CLI))


class DriftTest(RealHomeTestCase):
    def test_a_hand_edited_artifact_is_reported_drifted_for_claudecode_specifically(self):
        self.install()
        layout = self.layout()
        orchestrator_file = layout.agents_dir / f"{ORCHESTRATOR_AGENT}.md"
        orchestrator_file.write_bytes(orchestrator_file.read_bytes() + b"\nsomebody edited this by hand\n")

        _, report = self.run_cli("doctor")

        entry = cli_entry(report)
        self.assertIn("agent:pegasus-orchestrator", entry["drifted"])
        self.assertFalse(entry["missing"])


class PermissionsTest(RealHomeTestCase):
    """External directories allowed by default for Claude Code too (the same
    product decision already taken for OpenCode's `external_directory`
    baseline), written as `permissions.allow`/`permissions.deny` in
    `settings.json`, each entry Pegasus's own append -- never the person's
    whole array -- so a hand-written entry of theirs, present before install
    or added afterward, survives untouched.
    """

    def _settings(self):
        return json.loads(self.layout().settings_file.read_bytes())

    def test_install_writes_exactly_the_allow_rules_and_the_floor_deny_rules(self):
        self.install()
        settings = self._settings()
        self.assertEqual(settings["permissions"]["allow"], list(render_module.PERMISSIONS_ALLOW))
        self.assertEqual(settings["permissions"]["deny"], list(render_module.PERMISSIONS_DENY_FLOOR))

    def test_install_preserves_pre_existing_user_permission_entries(self):
        self.present()
        layout = self.layout()
        layout.settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(rm -rf /:*)"]}}),
            encoding="utf-8",
        )
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0, report)
        settings = self._settings()
        self.assertIn("Bash(ls:*)", settings["permissions"]["allow"])
        self.assertIn("Bash(rm -rf /:*)", settings["permissions"]["deny"])
        for rule in render_module.PERMISSIONS_ALLOW:
            self.assertIn(rule, settings["permissions"]["allow"])
        for rule in render_module.PERMISSIONS_DENY_FLOOR:
            self.assertIn(rule, settings["permissions"]["deny"])

    def test_update_is_idempotent_no_duplicate_rules(self):
        self.install()
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0, report)
        settings = self._settings()
        self.assertEqual(settings["permissions"]["allow"].count("Read(//**)"), 1)
        self.assertEqual(settings["permissions"]["allow"].count("Edit(//**)"), 1)
        self.assertEqual(len(settings["permissions"]["deny"]), len(render_module.PERMISSIONS_DENY_FLOOR))

    def test_the_agent_key_is_unaffected(self):
        self.install()
        settings = self._settings()
        self.assertEqual(settings["agent"], ORCHESTRATOR_AGENT)
        self.assertIn("permissions", settings)

    def test_uninstall_removes_only_pegasus_entries_and_keeps_the_users(self):
        self.present()
        layout = self.layout()
        layout.settings_file.write_text(
            json.dumps({"permissions": {"allow": ["Bash(ls:*)"], "deny": ["Bash(rm -rf /:*)"]}}),
            encoding="utf-8",
        )
        self.run_cli("install", "--cli", CLI)
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, 0, report)
        settings = self._settings()
        self.assertEqual(settings["permissions"]["allow"], ["Bash(ls:*)"])
        self.assertEqual(settings["permissions"]["deny"], ["Bash(rm -rf /:*)"])

    def test_doctor_flags_a_hand_removed_permission_entry(self):
        self.install()
        layout = self.layout()
        settings = self._settings()
        settings["permissions"]["deny"] = [
            rule for rule in settings["permissions"]["deny"] if rule != "Read(//**/.ssh/**)"
        ]
        layout.settings_file.write_text(json.dumps(settings), encoding="utf-8")

        _, report = self.run_cli("doctor")
        entry = cli_entry(report)
        self.assertIn("own:permission-deny:Read-ssh", entry["missing"] + entry["drifted"])
