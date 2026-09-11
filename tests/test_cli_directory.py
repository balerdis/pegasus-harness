"""`pegasus directory grant|revoke`: working directories the person administers.

`sdd-verify`, a sub-agent, was pointed at a working directory outside its own
worktree and refused outright by the runtime's `external_directory`
permission -- reported from real use, not from the suite. Pegasus had no
supported way for a person to hand an agent its own working directory: it
claims the agent's whole rendered entry, so a hand-edited exception would be
overwritten by the next `install`/`update`. `directory grant` is the lever
this change adds, mirroring `pegasus mcp grant`'s own shape (see
`test_cli_mcp.py`) for a different fact Pegasus cannot know on its own.

Follows the same discipline as `test_cli_mcp.py`: real disk, a throwaway
home, and the double only where a real filesystem condition cannot be
produced.
"""
from __future__ import annotations

import io
import json

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

    def install(self, *extra) -> None:
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, *extra)
        self.assertEqual(code, 0)

    def own_directory(self) -> str:
        """A working directory legitimately outside the worktree and outside
        the CLI's own configuration directory -- exactly the case this
        mechanism exists for."""
        target = self.home / "worktrees" / "extra"
        target.mkdir(parents=True, exist_ok=True)
        return str(target)


class GrantTest(RealHomeTestCase):
    def test_granting_a_directory_succeeds(self):
        self.install()
        path = self.own_directory()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, path)
        self.assertEqual(code, 0)
        self.assertEqual(report["action"], "grant")
        self.assertEqual(report["path"], path)
        self.assertIn(path, report["granted_directories"])

    def test_granting_persists_to_the_journal(self):
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        self.assertIn(path, self.installed().granted_directories)

    def test_granting_reapplies_the_rendered_agent_permission(self):
        """The whole point: an agent's rendered `permission` block must
        actually carry the grant, not just the journal."""
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        settings = self.settings()
        agents = settings.get("agent", {})
        self.assertTrue(agents, "expected at least one rendered agent")
        found_grant = any(
            entry.get("permission", {}).get("external_directory", {}).get(f"{path}/*") == "allow"
            for entry in agents.values()
        )
        self.assertTrue(found_grant, "no agent's rendered permission carries the directory grant")

    def test_granting_reaches_a_subagent_too(self):
        """Unlike an mcp grant, a directory grant has no per-agent shape to
        preserve -- both a primary and a sub-agent may need a working
        directory of their own."""
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        settings = self.settings()
        agents = settings.get("agent", {})
        subagents = {name: entry for name, entry in agents.items() if entry.get("mode") == "subagent"}
        self.assertTrue(subagents, "expected at least one rendered sub-agent")
        found_grant = any(
            entry.get("permission", {}).get("external_directory", {}).get(f"{path}/*") == "allow"
            for entry in subagents.values()
        )
        self.assertTrue(found_grant, "no sub-agent's rendered permission carries the directory grant")

    def test_grant_reports_a_restart_is_needed(self):
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, self.own_directory())
        self.assertEqual(code, 0)
        self.assertTrue(report.get("activation"))

    def test_grant_without_an_installation_is_refused(self):
        self.present()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, self.own_directory())
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_grant_with_an_unknown_cli_is_refused(self):
        code, report = self.run_cli("directory", "grant", "--cli", "nonesuch", self.own_directory())
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")

    def test_a_relative_path_is_refused(self):
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, "relative/path")
        self.assertNotEqual(code, 0)
        self.assertIn("relative/path", report["error"])

    def test_the_filesystem_root_is_refused(self):
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, "/")
        self.assertNotEqual(code, 0)
        self.assertIn("filesystem root", report["error"])

    def test_the_configuration_directory_itself_is_refused(self):
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, str(self.layout().config_dir))
        self.assertNotEqual(code, 0)
        self.assertIn("configuration directory", report["error"])

    def test_an_ancestor_of_the_configuration_directory_is_refused(self):
        self.install()
        code, report = self.run_cli(
            "directory", "grant", "--cli", CLI, str(self.layout().config_dir.parent)
        )
        self.assertNotEqual(code, 0)
        self.assertIn("configuration directory", report["error"])

    def test_a_directory_outside_the_home_is_not_refused_by_containment(self):
        """No home-containment check applies to a granted directory -- a
        legitimate working directory can sit anywhere on the machine."""
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, "/srv/worktrees/extra")
        self.assertEqual(code, 0, report)

    def test_a_wildcard_directory_is_refused(self):
        """A glob metacharacter in the path becomes part of the rendered
        permission rule verbatim -- `/*` would reach every absolute path
        with at least two slashes, since the runtime's own `*` crosses `/`."""
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, "/*")
        self.assertNotEqual(code, 0)
        self.assertIn("*", report["error"])

    def test_a_question_mark_in_the_path_is_refused(self):
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, "/srv/wor?k")
        self.assertNotEqual(code, 0)

    def test_a_bracket_in_the_path_is_refused(self):
        self.install()
        code, report = self.run_cli("directory", "grant", "--cli", CLI, "/srv/[work]")
        self.assertNotEqual(code, 0)

    def test_pegasus_own_data_directory_is_refused(self):
        """Granting write access to Pegasus's own data directory would let an
        agent's own write turn into arbitrary deletion at the next
        `uninstall`, which reads the journal that lives there uncritically."""
        self.install()
        data_dir = self.filesystem.data_dir(self.home)
        code, report = self.run_cli("directory", "grant", "--cli", CLI, str(data_dir))
        self.assertNotEqual(code, 0)
        self.assertIn("data directory", report["error"])

    def test_an_ancestor_of_pegasus_own_data_directory_is_refused(self):
        self.install()
        data_dir = self.filesystem.data_dir(self.home)
        code, report = self.run_cli("directory", "grant", "--cli", CLI, str(data_dir.parent))
        self.assertNotEqual(code, 0)
        self.assertIn("data directory", report["error"])

    def test_grant_reports_the_normalized_path_not_the_raw_typed_one(self):
        self.install()
        base = self.own_directory()
        typed = f"{base}//"
        code, report = self.run_cli("directory", "grant", "--cli", CLI, typed)
        self.assertEqual(code, 0, report)
        self.assertEqual(report["path"], base)
        self.assertIn(base, report["granted_directories"])


class RevokeTest(RealHomeTestCase):
    def test_revoking_a_never_granted_directory_reports_already_revoked_at_exit_0(self):
        self.install()
        code, report = self.run_cli("directory", "revoke", "--cli", CLI, self.own_directory())
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "already-revoked")

    def test_revoking_a_granted_directory_removes_it(self):
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        code, report = self.run_cli("directory", "revoke", "--cli", CLI, path)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "revoked")
        self.assertNotIn(path, self.installed().granted_directories)

    def test_revoking_reapplies_the_rendered_permission(self):
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        self.run_cli("directory", "revoke", "--cli", CLI, path)
        settings = self.settings()
        agents = settings.get("agent", {})
        self.assertTrue(agents, "expected at least one rendered agent")
        found_grant = any(
            entry.get("permission", {}).get("external_directory", {}).get(f"{path}/*") == "allow"
            for entry in agents.values()
        )
        self.assertFalse(found_grant, "revoked grant is still present in a rendered agent")

    def test_revoke_without_an_installation_is_refused(self):
        self.present()
        code, report = self.run_cli("directory", "revoke", "--cli", CLI, self.own_directory())
        self.assertNotEqual(code, 0)

    def test_revoking_a_trailing_slash_spelling_removes_a_grant_without_one(self):
        """`grant`/`revoke` must agree on one normalized spelling of the same
        directory, or a trailing slash silently leaves the grant in place --
        the exact bug this test reproduces if the normalization regresses."""
        self.install()
        base = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, base)
        code, report = self.run_cli("directory", "revoke", "--cli", CLI, f"{base}/")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "revoked")
        self.assertNotIn(base, self.installed().granted_directories)
        settings = self.settings()
        agents = settings.get("agent", {})
        self.assertTrue(agents, "expected at least one rendered agent")
        found_grant = any(
            entry.get("permission", {}).get("external_directory", {}).get(f"{base}/*") == "allow"
            for entry in agents.values()
        )
        self.assertFalse(found_grant, "revoked grant is still present in a rendered agent")

    def test_revoking_a_double_slash_spelling_removes_a_grant_without_one(self):
        self.install()
        base = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, base)
        parent, name = base.rsplit("/", 1)
        code, report = self.run_cli("directory", "revoke", "--cli", CLI, f"{parent}//{name}")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "revoked")
        self.assertNotIn(base, self.installed().granted_directories)

    def test_revoking_a_single_dot_component_spelling_removes_a_grant_without_one(self):
        self.install()
        base = self.own_directory()
        parent, name = base.rsplit("/", 1)
        self.run_cli("directory", "grant", "--cli", CLI, base)
        code, report = self.run_cli("directory", "revoke", "--cli", CLI, f"{parent}/./{name}")
        self.assertEqual(code, 0, report)
        self.assertEqual(report["status"], "revoked")
        self.assertNotIn(base, self.installed().granted_directories)


class GrantSurvivesReinstallTest(RealHomeTestCase):
    """The one that proves this actually solves the reported problem: a
    directory grant must not be a one-time render that the next `install` or
    `update` silently drops, the same way `Install.granted_mcp` already
    survives both.
    """

    def test_the_grant_survives_a_plain_install(self):
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, 0, report)
        self.assertIn(path, self.installed().granted_directories)
        settings = self.settings()
        agents = settings.get("agent", {})
        found_grant = any(
            entry.get("permission", {}).get("external_directory", {}).get(f"{path}/*") == "allow"
            for entry in agents.values()
        )
        self.assertTrue(found_grant, "a plain reinstall dropped the directory grant")

    def test_the_grant_survives_an_update(self):
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        code, report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(code, 0, report)
        self.assertIn(path, self.installed().granted_directories)
        settings = self.settings()
        agents = settings.get("agent", {})
        found_grant = any(
            entry.get("permission", {}).get("external_directory", {}).get(f"{path}/*") == "allow"
            for entry in agents.values()
        )
        self.assertTrue(found_grant, "update dropped the directory grant")


class DoctorReportsGrantedTest(RealHomeTestCase):
    def test_doctor_reports_granted_directories(self):
        self.install()
        path = self.own_directory()
        self.run_cli("directory", "grant", "--cli", CLI, path)
        code, report = self.run_cli("doctor")
        self.assertEqual(code, 0)
        entry = next(item for item in report["clis"] if item["cli"] == CLI)
        self.assertIn(path, entry["directories_granted"])

    def test_doctor_reports_no_granted_directories_when_none_are_granted(self):
        self.install()
        code, report = self.run_cli("doctor")
        entry = next(item for item in report["clis"] if item["cli"] == CLI)
        self.assertEqual(entry["directories_granted"], [])


if __name__ == "__main__":
    import unittest

    unittest.main()
