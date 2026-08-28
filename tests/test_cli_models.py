"""`models set` / `unset` / `list`: the CLI surface for a per-agent preference.

Follows the same discipline as `test_cli.py`: real disk, a throwaway home, and
the double only where a real filesystem condition cannot be produced.
"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import PurePosixPath
from unittest.mock import patch

from pegasus import cli
from pegasus.adapters import available
from pegasus.core.content import AgentMode, Agent, Content
from pegasus.infra.model_assignment_store_file import model_assignment_path
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
CONFIGURABLE_AGENT = "sdd-apply"


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self) -> cli.Runtime:
        return cli.Runtime(filesystem=self.filesystem, home=self.home, now=AT, out=io.StringIO())

    def run_cli(self, *argv) -> tuple[int, dict]:
        context = self.runtime()
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())


class SetTest(RealHomeTestCase):
    def test_setting_a_configurable_agent_succeeds_and_reports_it(self):
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--agent", CONFIGURABLE_AGENT,
            "--model", "anthropic/claude-sonnet-5", "--effort", "high",
        )
        self.assertEqual(code, 0)
        self.assertEqual(report["action"], "set")
        self.assertEqual(report["cli"], CLI)
        self.assertEqual(report["agent"], CONFIGURABLE_AGENT)
        self.assertEqual(report["model"], "anthropic/claude-sonnet-5")
        self.assertEqual(report["effort"], "high")

    def test_setting_persists_to_the_store(self):
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", CONFIGURABLE_AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        loaded = cli.model_assignment_store(self.runtime()).load()
        from pegasus.core import model_assignments as model_assignments_module

        assignment = model_assignments_module.get(loaded, CLI, CONFIGURABLE_AGENT)
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment.full_id, "anthropic/claude-sonnet-5")

    def test_an_unknown_agent_is_refused_with_a_clear_reason(self):
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--agent", "nonexistent-agent", "--model", "anthropic/claude-sonnet-5",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("nonexistent-agent", report["error"])
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())

    def test_a_non_configurable_agent_is_refused_with_a_clear_reason(self):
        not_configurable = Agent(
            name="static-agent",
            description="an agent nothing ever lets configure a model",
            body="body",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/static-agent.md"),
            model_configurable=False,
        )
        with patch("pegasus.core.content.load", return_value=Content(agents=(not_configurable,))):
            code, report = self.run_cli(
                "models", "set", "--cli", CLI, "--agent", "static-agent", "--model", "anthropic/claude-sonnet-5",
            )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")
        self.assertIn("static-agent", report["error"])
        self.assertFalse(model_assignment_path(self.filesystem, self.home).exists())

    def test_a_malformed_model_spec_is_refused(self):
        code, report = self.run_cli(
            "models", "set", "--cli", CLI, "--agent", CONFIGURABLE_AGENT, "--model", "not-a-provider-slash-model",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class UnsetTest(RealHomeTestCase):
    def test_unsetting_something_never_set_is_a_no_op_not_an_error(self):
        code, report = self.run_cli("models", "unset", "--cli", CLI, "--agent", CONFIGURABLE_AGENT)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "already-unset")

    def test_unsetting_a_set_assignment_removes_it(self):
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", CONFIGURABLE_AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        code, report = self.run_cli("models", "unset", "--cli", CLI, "--agent", CONFIGURABLE_AGENT)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "unset")

        from pegasus.core import model_assignments as model_assignments_module

        loaded = cli.model_assignment_store(self.runtime()).load()
        self.assertIsNone(model_assignments_module.get(loaded, CLI, CONFIGURABLE_AGENT))


class ListTest(RealHomeTestCase):
    def test_no_agent_starts_with_an_assignment(self):
        code, report = self.run_cli("models", "list")
        self.assertEqual(code, 0)
        self.assertEqual(report["assignments"], [])

    def test_listing_shows_what_was_set(self):
        self.run_cli(
            "models", "set", "--cli", CLI, "--agent", CONFIGURABLE_AGENT, "--model", "anthropic/claude-sonnet-5",
        )
        code, report = self.run_cli("models", "list")
        self.assertEqual(code, 0)
        self.assertEqual(len(report["assignments"]), 1)
        self.assertEqual(report["assignments"][0]["agent"], CONFIGURABLE_AGENT)

    def test_listing_can_be_narrowed_to_one_cli(self):
        code, report = self.run_cli("models", "list", "--cli", CLI)
        self.assertEqual(code, 0)
        self.assertEqual(report["assignments"], [])

    def test_listing_with_an_unknown_cli_is_refused(self):
        code, report = self.run_cli("models", "list", "--cli", "nonesuch")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


class ProseTest(RealHomeTestCase):
    def test_set_reads_as_prose(self):
        context = self.runtime()
        cli.main(
            ["models", "set", "--cli", CLI, "--agent", CONFIGURABLE_AGENT, "--model", "anthropic/claude-sonnet-5"],
            runtime=context,
        )
        self.assertIn(CONFIGURABLE_AGENT, context.out.getvalue())

    def test_missing_subcommand_is_an_error(self):
        code, report = self.run_cli("models")
        self.assertNotEqual(code, 0)
        self.assertEqual(report["status"], "failed")


if __name__ == "__main__":
    unittest.main()
