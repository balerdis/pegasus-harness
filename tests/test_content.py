"""Loading the content core, and refusing to load content that would mislead an adapter."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePosixPath

from pegasus.core import content
from pegasus.core.content import AgentMode, ContentError, Execution, RunsAs

SKILL = """---
name: alpha
description: Does alpha things
license: MIT
metadata:
  author: pegasus-balerdis
---

# Alpha

Body of alpha.
"""

AGENT = """---
name: probe-agent
description: Probes things
mode: subagent
hidden: true
requires_tools: [read, bash]
model_configurable: true
---

# Probe

Prompt body.
"""

COMMAND = """---
name: probe-command
description: Runs a probe
runs_as: orchestrator
execution: isolated
---

Command body.
"""


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TemporaryContent(unittest.TestCase):
    """Builds a content tree on disk so error paths can be exercised."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)

    def complete(self):
        write(self.root, "skills/alpha/SKILL.md", SKILL)
        write(self.root, "agents/probe-agent.md", AGENT)
        write(self.root, "commands/probe-command.md", COMMAND)
        write(self.root, "system-prompt/AGENTS.md", "# Rules\n\nBe careful.\n")


class FrontmatterTest(unittest.TestCase):
    def test_splits_fields_from_body(self):
        fields, body = content.split_frontmatter(SKILL)
        self.assertEqual(fields["name"], "alpha")
        self.assertTrue(body.startswith("# Alpha"))

    def test_nested_fields_are_parsed(self):
        fields, _ = content.split_frontmatter(SKILL)
        self.assertEqual(fields["metadata"], {"author": "pegasus-balerdis"})

    def test_missing_frontmatter_yields_no_fields(self):
        fields, body = content.split_frontmatter("# Just a body\n")
        self.assertEqual(fields, {})
        self.assertEqual(body, "# Just a body\n")

    def test_unterminated_frontmatter_is_rejected(self):
        with self.assertRaises(ContentError):
            content.split_frontmatter("---\nname: x\n\nno closing marker\n")

    def test_non_mapping_frontmatter_is_rejected(self):
        with self.assertRaises(ContentError):
            content.split_frontmatter("---\n- a\n- b\n---\n\nbody\n")


class LoadTest(TemporaryContent):
    def test_loads_every_category(self):
        self.complete()
        loaded = content.load(self.root)
        self.assertEqual([s.name for s in loaded.skills], ["alpha"])
        self.assertEqual([a.name for a in loaded.agents], ["probe-agent"])
        self.assertEqual([c.name for c in loaded.commands], ["probe-command"])
        self.assertIsNotNone(loaded.system_prompt)

    def test_absent_categories_load_as_empty(self):
        write(self.root, "skills/alpha/SKILL.md", SKILL)
        loaded = content.load(self.root)
        self.assertEqual(loaded.agents, ())
        self.assertEqual(loaded.commands, ())
        self.assertIsNone(loaded.system_prompt)

    def test_items_are_sorted_by_name(self):
        for name in ("zeta", "alpha", "mu"):
            write(self.root, f"commands/{name}.md", COMMAND.replace("probe-command", name))
        self.assertEqual([c.name for c in content.load(self.root).commands], ["alpha", "mu", "zeta"])

    def test_loading_twice_yields_equal_content(self):
        self.complete()
        self.assertEqual(content.load(self.root), content.load(self.root))


class SkillTest(TemporaryContent):
    def test_carries_every_file_in_the_skill_directory(self):
        write(self.root, "skills/alpha/SKILL.md", SKILL)
        write(self.root, "skills/alpha/references/guide.md", "# Guide\n")
        skill = content.load(self.root).skills[0]
        self.assertEqual(
            [str(asset.relative_path) for asset in skill.assets],
            ["SKILL.md", "references/guide.md"],
        )

    def test_assets_carry_raw_bytes(self):
        write(self.root, "skills/alpha/SKILL.md", SKILL)
        skill = content.load(self.root).skills[0]
        self.assertEqual(skill.assets[0].content, SKILL.encode("utf-8"))

    def test_skill_without_a_skill_file_is_rejected(self):
        write(self.root, "skills/alpha/references/orphan.md", "# Orphan\n")
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        self.assertIn("SKILL.md", str(raised.exception))

    def test_name_must_match_the_directory(self):
        write(self.root, "skills/beta/SKILL.md", SKILL)
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        self.assertIn("beta", str(raised.exception))


class AgentTest(TemporaryContent):
    def load_agent(self, text):
        write(self.root, "agents/probe-agent.md", text)
        return content.load(self.root).agents[0]

    def test_reads_the_descriptor(self):
        agent = self.load_agent(AGENT)
        self.assertEqual(agent.mode, AgentMode.SUBAGENT)
        self.assertTrue(agent.hidden)
        self.assertEqual(agent.requires_tools, ("read", "bash"))
        self.assertTrue(agent.model_configurable)

    def test_body_is_the_prompt(self):
        self.assertIn("Prompt body.", self.load_agent(AGENT).body)

    def test_optional_fields_default_conservatively(self):
        agent = self.load_agent("---\nname: probe-agent\ndescription: d\nmode: primary\n---\n\nx\n")
        self.assertFalse(agent.hidden)
        self.assertFalse(agent.model_configurable)
        self.assertEqual((agent.requires_tools, agent.may_delegate_to), ((), ()))

    def test_delegation_list_is_read(self):
        agent = self.load_agent(
            "---\nname: probe-agent\ndescription: d\nmode: primary\nmay_delegate_to: [explore, general]\n---\n\nx\n"
        )
        self.assertEqual(agent.may_delegate_to, ("explore", "general"))

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_agent("---\nname: probe-agent\ndescription: d\nmode: sidekick\n---\n\nx\n")
        self.assertIn("sidekick", str(raised.exception))

    def test_missing_mode_is_rejected(self):
        with self.assertRaises(ContentError):
            self.load_agent("---\nname: probe-agent\ndescription: d\n---\n\nx\n")


class CommandTest(TemporaryContent):
    def load_command(self, text):
        write(self.root, "commands/probe-command.md", text)
        return content.load(self.root).commands[0]

    def test_reads_the_agnostic_fields(self):
        command = self.load_command(COMMAND)
        self.assertEqual(command.runs_as, RunsAs.ORCHESTRATOR)
        self.assertEqual(command.execution, Execution.ISOLATED)

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_command(COMMAND.replace("orchestrator", "pegasus-orchestrator"))
        self.assertIn("pegasus-orchestrator", str(raised.exception))

    def test_unknown_execution_is_rejected(self):
        with self.assertRaises(ContentError):
            self.load_command(COMMAND.replace("isolated", "subtask"))

    def test_missing_description_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_command("---\nname: probe-command\nruns_as: default\nexecution: inline\n---\n\nx\n")
        self.assertIn("description", str(raised.exception))


class ErrorReportingTest(TemporaryContent):
    def test_every_error_names_the_offending_file(self):
        write(self.root, "commands/broken.md", "---\nname: broken\ndescription: d\n---\n\nx\n")
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        self.assertIn("commands/broken.md", str(raised.exception))


class ShippedContentTest(unittest.TestCase):
    """The content this repository actually distributes must load cleanly."""

    @classmethod
    def setUpClass(cls):
        cls.content = content.load()

    def test_skills_load(self):
        self.assertEqual(len(self.content.skills), 27)

    def test_commands_load(self):
        self.assertEqual(len(self.content.commands), 16)

    def test_every_command_declares_an_agnostic_role(self):
        for command in self.content.commands:
            self.assertIsInstance(command.runs_as, RunsAs, command.name)
            self.assertIsInstance(command.execution, Execution, command.name)

    def test_agents_load(self):
        self.assertEqual(
            {a.name for a in self.content.agents},
            {
                "pegasus-orchestrator",
                "sdd-apply",
                "sdd-archive",
                "sdd-design",
                "sdd-explore",
                "sdd-init",
                "sdd-onboard",
                "sdd-propose",
                "sdd-spec",
                "sdd-tasks",
                "sdd-verify",
            },
        )

    def test_the_orchestrator_declares_its_delegation(self):
        orchestrator = next(a for a in self.content.agents if a.name == "pegasus-orchestrator")
        self.assertEqual(orchestrator.mode, AgentMode.PRIMARY)
        self.assertEqual(orchestrator.may_delegate_to, ("explore", "general", "sdd-verify"))

    def test_system_prompt_loads(self):
        self.assertIn("Co-Authored-By", self.content.system_prompt.body)

    def test_sources_are_relative_and_portable(self):
        for skill in self.content.skills:
            self.assertIsInstance(skill.source, PurePosixPath)
            self.assertFalse(skill.source.is_absolute())


if __name__ == "__main__":
    unittest.main()
