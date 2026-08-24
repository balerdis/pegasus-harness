"""Loading the content core, and refusing to load content that would mislead an adapter."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePosixPath

from pegasus.core import content
from pegasus.core.content import AgentMode, ContentError, Distribution, Execution, RunsAs

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
mode: primary
requires_tools: [read, bash]
model_configurable: true
---

# Probe

Prompt body.
"""

#: A tree that has agents must carry the one a session starts in, so tests whose
#: subject is anything else ship it alongside whatever they are really probing.
SESSION_START = f"""---
name: {content.SESSION_STARTS_IN}
description: Where a session starts
mode: primary
---

# Session start

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

MCP = """---
name: probe-mcp
description: Probes an MCP server
distribution: remote
endpoint: https://example.test/mcp
---

Convention body.
"""


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def write_session_start(root: Path) -> Path:
    return write(root, f"agents/{content.SESSION_STARTS_IN}.md", SESSION_START)


class TemporaryContent(unittest.TestCase):
    """Builds a content tree on disk so error paths can be exercised."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.root = Path(self._directory.name)
        self.addCleanup(self._directory.cleanup)

    def complete(self):
        write(self.root, "skills/alpha/SKILL.md", SKILL)
        write_session_start(self.root)
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
        self.assertEqual([a.name for a in loaded.agents], [content.SESSION_STARTS_IN])
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
        write_session_start(self.root)
        write(self.root, "agents/probe-agent.md", text)
        return next(a for a in content.load(self.root).agents if a.name == "probe-agent")

    def test_reads_the_descriptor(self):
        agent = self.load_agent(AGENT)
        self.assertEqual(agent.mode, AgentMode.PRIMARY)
        self.assertEqual(agent.requires_tools, ("read", "bash"))
        self.assertTrue(agent.model_configurable)

    def test_body_is_the_prompt(self):
        self.assertIn("Prompt body.", self.load_agent(AGENT).body)

    def test_optional_fields_default_conservatively(self):
        agent = self.load_agent(
            "---\nname: probe-agent\ndescription: d\nmode: primary\n---\n\nx\n"
        )
        self.assertFalse(agent.model_configurable)
        self.assertEqual(
            (agent.requires_tools, agent.optional_mcp, agent.may_delegate_to), ((), (), ())
        )

    def test_optional_mcp_is_read(self):
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        agent = self.load_agent(
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\n"
            "See {{skills_root}}/_shared/mcp/context7-convention.md.\n"
        )
        self.assertEqual(agent.optional_mcp, ("context7",))

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


class OptionalMcpInvariantTest(TemporaryContent):
    """An `optional_mcp` id has to name a server that actually ships.

    Otherwise the agent would run believing tools might arrive from a server
    that was never going to be installed under any configuration.
    """

    def test_a_dangling_id_is_refused_naming_the_agent_file_and_the_id(self):
        write_session_start(self.root)
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [phantom]\n---\n\nx\n",
        )
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn("agents/probe-agent.md", message)
        self.assertIn("phantom", message)

    def test_an_id_a_server_actually_declares_is_accepted(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\n"
            "See {{skills_root}}/_shared/mcp/context7-convention.md.\n",
        )
        loaded = content.load(self.root)
        agent = next(a for a in loaded.agents if a.name == "probe-agent")
        self.assertEqual(agent.optional_mcp, ("context7",))


class McpConventionReferenceInvariantTest(TemporaryContent):
    """A declared server and a referenced convention have to name the same set.

    The permission is derived from the declaration alone (`optional_mcp: [id]`
    grants the wildcard, nothing else reads the descriptor), so nothing forces an
    agent body to ever mention that the server has a usage convention at all --
    and nothing stops a body from pointing at a convention for a server it never
    declared, granting no permission at all. This invariant keeps both
    directions travelling together instead of letting either one drift.
    """

    def test_a_body_that_never_mentions_the_convention_path_is_refused(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\nx\n",
        )
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn("agents/probe-agent.md", message)
        self.assertIn("context7", message)
        self.assertIn("{{skills_root}}/_shared/mcp/context7-convention.md", message)

    def test_a_body_that_references_the_convention_path_is_accepted(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\n"
            "Follow {{skills_root}}/_shared/mcp/context7-convention.md for tool order.\n",
        )
        loaded = content.load(self.root)
        agent = next(a for a in loaded.agents if a.name == "probe-agent")
        self.assertEqual(agent.optional_mcp, ("context7",))

    def test_a_body_that_references_a_convention_never_declared_is_refused(self):
        """The reverse direction: a reference with no matching declaration grants
        no permission, so the body would tell the agent to follow a convention
        for tools it will never have.
        """
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n---\n\n"
            "Follow {{skills_root}}/_shared/mcp/context7-convention.md for tool order.\n",
        )
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn("agents/probe-agent.md", message)
        self.assertIn("context7", message)

    def test_both_directions_are_named_together_when_both_are_wrong(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(self.root, "mcp/cbm.md", MCP.replace("probe-mcp", "cbm"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\n"
            "Follow {{skills_root}}/_shared/mcp/cbm-convention.md for tool order.\n",
        )
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn("agents/probe-agent.md", message)
        self.assertIn("context7", message)
        self.assertIn("cbm", message)

    def test_the_matcher_finds_exactly_what_the_writer_would_have_written(self):
        """The body pattern the loader scans with has to be built from the same
        pieces `mcp_convention_path` uses, so a change to that path shape cannot
        make the writer and the matcher disagree about what counts as a reference.
        """
        for server_id in ("context7", "cbm", "a-b-c"):
            path = "{{skills_root}}/" + content.mcp_convention_path(server_id).as_posix()
            found = content._referenced_mcp_ids(f"See {path} for details.\n")
            self.assertEqual(found, {server_id})

    def test_the_matcher_does_not_cross_a_path_separator(self):
        """A slash inside the captured id would mean the pattern accepted more
        path than the id ever contains, defeating the point of anchoring it to
        the writer's own shape.
        """
        found = content._referenced_mcp_ids(
            "{{skills_root}}/_shared/mcp/not/a-convention.md\n"
        )
        self.assertEqual(found, set())


class SessionStartTest(TemporaryContent):
    """Which agent a session opens in is a fact about the set, and code names it once.

    No file can claim it, so no file can claim it twice and no tree can leave it
    unclaimed. What a tree still decides is whether the named agent is there at all
    and what mode it is in, and a session opens in a primary agent.
    """

    def agent(self, name: str, mode: str = "primary") -> None:
        write(
            self.root,
            f"agents/{name}.md",
            f"---\nname: {name}\ndescription: d\nmode: {mode}\n---\n\nx\n",
        )

    def test_a_tree_of_agents_without_the_named_one_is_refused(self):
        self.agent("alpha")
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn(content.SESSION_STARTS_IN, message)
        self.assertIn("agents", message)

    def test_the_named_agent_present_but_not_primary_is_refused(self):
        self.agent(content.SESSION_STARTS_IN, mode="subagent")
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn(f"agents/{content.SESSION_STARTS_IN}.md", message)
        self.assertIn(AgentMode.PRIMARY.value, message)

    def test_the_named_agent_is_the_only_one_a_session_starts_in(self):
        self.agent(content.SESSION_STARTS_IN)
        self.agent("beta")
        self.agent("gamma", mode="subagent")
        loaded = {agent.name: agent.default for agent in content.load(self.root).agents}
        self.assertEqual(
            loaded, {content.SESSION_STARTS_IN: True, "beta": False, "gamma": False}
        )

    def test_being_hidden_is_exactly_being_a_subagent(self):
        self.agent(content.SESSION_STARTS_IN)
        self.agent("beta", mode="subagent")
        loaded = {agent.name: agent.hidden for agent in content.load(self.root).agents}
        self.assertEqual(loaded, {content.SESSION_STARTS_IN: False, "beta": True})

    def test_a_derived_field_written_in_frontmatter_is_refused_not_obeyed(self):
        """Ignoring the line would leave a file stating a fact it does not decide."""
        for line in ("default: true", "default: false", "hidden: true", "hidden: false"):
            with self.subTest(line=line):
                write(
                    self.root,
                    f"agents/{content.SESSION_STARTS_IN}.md",
                    f"---\nname: {content.SESSION_STARTS_IN}\ndescription: d\n"
                    f"mode: primary\n{line}\n---\n\nx\n",
                )
                with self.assertRaises(ContentError) as raised:
                    content.load(self.root)
                message = str(raised.exception)
                self.assertIn(f"agents/{content.SESSION_STARTS_IN}.md", message)
                self.assertIn(line.split(":")[0], message)


class FlagTest(TemporaryContent):
    """A flag is a YAML boolean or nothing, and anything else is a refusal.

    `bool()` reads the string 'false' as true, so an author saying "not this one"
    would have said the opposite and been told nothing.
    """

    def load(self, line: str):
        write(
            self.root,
            f"agents/{content.SESSION_STARTS_IN}.md",
            f"---\nname: {content.SESSION_STARTS_IN}\ndescription: d\nmode: primary\n"
            f"{line}\n---\n\nx\n",
        )
        return content.load(self.root).agents[0]

    def test_a_real_boolean_is_read(self):
        self.assertTrue(self.load("model_configurable: true").model_configurable)

    def test_a_quoted_false_is_refused_rather_than_read_as_true(self):
        with self.assertRaises(ContentError) as raised:
            self.load('model_configurable: "false"')
        self.assertIn(f"agents/{content.SESSION_STARTS_IN}.md", str(raised.exception))

    def test_a_number_is_refused(self):
        with self.assertRaises(ContentError):
            self.load("model_configurable: 1")

    def test_a_list_is_refused(self):
        with self.assertRaises(ContentError):
            self.load("model_configurable: [yes]")


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


class McpTest(TemporaryContent):
    def load_mcp(self, text):
        write(self.root, "mcp/probe-mcp.md", text)
        return content.load(self.root).mcp[0]

    def test_reads_every_declared_field(self):
        mcp = self.load_mcp(MCP)
        self.assertEqual(mcp.description, "Probes an MCP server")
        self.assertIn("Convention body.", mcp.body)
        self.assertEqual(mcp.distribution, Distribution.REMOTE)
        self.assertEqual(mcp.endpoint, "https://example.test/mcp")

    def test_unknown_distribution_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(MCP.replace("distribution: remote", "distribution: bundled"))
        self.assertIn("bundled", str(raised.exception))

    def test_provides_tools_is_gone(self):
        """The permission an agent gets is derived from the server's id, not
        tabulated on the server: a hand-maintained list here would be
        unverifiable documentation with nothing to keep it honest.
        """
        mcp = self.load_mcp(MCP)
        self.assertFalse(hasattr(mcp, "provides_tools"))

    def test_missing_endpoint_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(
                "---\nname: probe-mcp\ndescription: d\ndistribution: remote\n---\n\nx\n"
            )
        self.assertIn("mcp/probe-mcp.md", str(raised.exception))
        self.assertIn("endpoint", str(raised.exception))


class McpConventionPathTest(unittest.TestCase):
    """The core, not the adapter, owns where a server's convention lands."""

    def test_the_path_is_relative_to_the_skills_root(self):
        self.assertEqual(
            content.mcp_convention_path("context7"),
            PurePosixPath("_shared/mcp/context7-convention.md"),
        )

    def test_the_path_is_keyed_by_the_server_id(self):
        self.assertEqual(
            content.mcp_convention_path("cbm"), PurePosixPath("_shared/mcp/cbm-convention.md")
        )


class ErrorReportingTest(TemporaryContent):
    def test_a_malformed_command_names_its_file(self):
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

    def test_mcp_servers_load(self):
        self.assertEqual([server.name for server in self.content.mcp], ["context7"])

    def test_every_shipped_server_declares_a_mechanism_and_a_convention(self):
        """A server nothing can carry out is not installable.

        `distribution` has one member per mechanism the installer implements, so the
        type check is what refuses a descriptor written ahead of its mechanism. The
        permission it grants is no longer tabulated on the server at all: an agent
        names the server's id, and the adapter derives the tool wildcard from that
        id itself.
        """
        for server in self.content.mcp:
            self.assertIsInstance(server.distribution, Distribution, server.name)
            self.assertTrue(server.body.strip(), server.name)

    def test_every_command_declares_an_agnostic_role(self):
        for command in self.content.commands:
            self.assertIsInstance(command.runs_as, RunsAs, command.name)
            self.assertIsInstance(command.execution, Execution, command.name)

    def test_agents_load(self):
        self.assertEqual(
            {a.name for a in self.content.agents},
            {
                "king-pegasus",
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
        self.assertIn("explore", orchestrator.may_delegate_to)
        self.assertIn("general", orchestrator.may_delegate_to)
        # Named on purpose: it is the sole readiness authority, so losing the right to
        # launch it would disable verification rather than one phase.
        self.assertIn("sdd-verify", orchestrator.may_delegate_to)

    def test_the_orchestrator_declares_tools(self):
        # The one agent among the twelve that declares no delegation-adjacent
        # tool need used to fall back on the runtime's defaults. Now that the
        # renderer's deny baseline covers every agent, this is the one whose
        # tools this repository must declare on purpose rather than by omission.
        # It declares no server: this coordinator is pending a reformulation
        # that decides what it may act on, so nothing is granted beyond the
        # native tools it needs to read and search.
        orchestrator = next(a for a in self.content.agents if a.name == "pegasus-orchestrator")
        self.assertEqual(
            set(orchestrator.requires_tools),
            {"read", "bash", "grep", "glob"},
        )
        self.assertEqual(orchestrator.optional_tools, ())
        self.assertEqual(orchestrator.optional_mcp, ())

    def test_the_orchestrator_is_the_agent_a_session_starts_in(self):
        starting = [agent.name for agent in self.content.agents if agent.default]
        self.assertEqual(starting, [content.SESSION_STARTS_IN])

    def test_being_hidden_is_exactly_being_a_subagent_across_the_whole_tree(self):
        """One assertion for every agent, instead of a per-agent claim per file.

        The persona must stay out of nobody's chooser and the ten phase executors
        must stay out of everybody's, and both used to be a frontmatter line that
        could be edited away from the mode beside it. Reading it off `mode` is what
        makes the two unable to disagree; this is where that is checked to hold for
        the content actually shipped.
        """
        self.assertEqual(
            {agent.name for agent in self.content.agents if agent.hidden},
            {agent.name for agent in self.content.agents if agent.mode is AgentMode.SUBAGENT},
        )

    def test_the_orchestrator_does_not_delegate_to_the_voice(self):
        # king-pegasus answers the user, it does not take work handed to it. It was in
        # this list only because it shipped as a subagent, and the rule below required
        # every shipped subagent to be delegable.
        orchestrator = next(a for a in self.content.agents if a.name == "pegasus-orchestrator")
        self.assertNotIn("king-pegasus", orchestrator.may_delegate_to)

    #: Agents the runtime supplies, which Pegasus may delegate to without shipping them.
    RUNTIME_BUILT_INS = frozenset({"explore", "general"})

    def test_the_orchestrator_may_delegate_to_every_subagent_it_ships_with(self):
        # render.py turns may_delegate_to into {"*": "deny", <named>: "allow"}, so an agent
        # missing from the list is not merely undeclared: it is denied. Comparing against a
        # hardcoded list would go stale the moment an agent is added, which is exactly how
        # the nine phase macros shipped denied.
        #
        # This asserts that every shipped subagent is delegable, which assumes shipped
        # subagents are all orchestrator-callable. That assumption held once the one agent
        # it was wrong about stopped being a subagent: king-pegasus is the voice the user
        # selects, and it is primary, so it is outside this set rather than forced into the
        # permission list. An agent that must not be launched directly and still has to be
        # a subagent would put the pressure back here, and the schema still has no
        # "delegable" field to answer it with.
        orchestrator = next(a for a in self.content.agents if a.name == "pegasus-orchestrator")
        shipped = {a.name for a in self.content.agents if a.mode is AgentMode.SUBAGENT}
        self.assertEqual(shipped - set(orchestrator.may_delegate_to), set())

    def test_the_orchestrator_delegates_to_nothing_that_does_not_exist(self):
        # The other direction. A name nobody answers to is a permission entry that grants
        # access to nothing: a typo or a removed agent survives as a silent no-op, and the
        # one-directional check above stays green through both.
        orchestrator = next(a for a in self.content.agents if a.name == "pegasus-orchestrator")
        shipped = {a.name for a in self.content.agents}
        self.assertEqual(set(orchestrator.may_delegate_to) - shipped - self.RUNTIME_BUILT_INS, set())

    def test_system_prompt_loads(self):
        self.assertIn("Co-Authored-By", self.content.system_prompt.body)

    def test_sources_are_relative_and_portable(self):
        for skill in self.content.skills:
            self.assertIsInstance(skill.source, PurePosixPath)
            self.assertFalse(skill.source.is_absolute())


class SelectMcpTest(unittest.TestCase):
    """`select_mcp` is what turns "every shipped server" into "what the user asked for"."""

    def setUp(self):
        self.context7 = content.Mcp(
            name="context7",
            description="Fetches library docs",
            body="Convention body.",
            distribution=Distribution.REMOTE,
            endpoint="https://example.test/context7",
            source=PurePosixPath("mcp/context7.md"),
        )
        self.other = content.Mcp(
            name="other",
            description="Another server",
            body="Convention body.",
            distribution=Distribution.REMOTE,
            endpoint="https://example.test/other",
            source=PurePosixPath("mcp/other.md"),
        )
        self.agent = content.Agent(
            name="probe-agent",
            description="Probes things",
            body="x",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/probe-agent.md"),
            optional_mcp=("context7", "other"),
        )
        self.plain_agent = content.Agent(
            name="plain-agent",
            description="Names no server",
            body="x",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/plain-agent.md"),
        )
        self.content = content.Content(
            agents=(self.agent, self.plain_agent), mcp=(self.context7, self.other)
        )

    def test_keeps_only_the_chosen_server(self):
        selected = content.select_mcp(self.content, ["context7"])
        self.assertEqual([server.name for server in selected.mcp], ["context7"])

    def test_keeps_only_the_chosen_id_in_optional_mcp(self):
        selected = content.select_mcp(self.content, ["context7"])
        chosen_agent = next(a for a in selected.agents if a.name == "probe-agent")
        self.assertEqual(chosen_agent.optional_mcp, ("context7",))

    def test_an_agent_naming_no_server_is_left_alone(self):
        selected = content.select_mcp(self.content, ["context7"])
        untouched_agent = next(a for a in selected.agents if a.name == "plain-agent")
        self.assertEqual(untouched_agent.optional_mcp, ())

    def test_choosing_nothing_is_the_default_and_installs_no_server(self):
        selected = content.select_mcp(self.content, [])
        self.assertEqual(selected.mcp, ())
        for agent in selected.agents:
            self.assertEqual(agent.optional_mcp, ())

    def test_an_unknown_id_is_refused_and_named(self):
        with self.assertRaises(ContentError) as raised:
            content.select_mcp(self.content, ["bogus"])
        self.assertIn("bogus", str(raised.exception))

    def test_the_refusal_also_lists_the_ids_that_do_exist(self):
        with self.assertRaises(ContentError) as raised:
            content.select_mcp(self.content, ["bogus"])
        message = str(raised.exception)
        self.assertIn("context7", message)
        self.assertIn("other", message)

    def test_is_pure_the_input_content_is_unchanged(self):
        before_mcp = self.content.mcp
        before_agents = self.content.agents
        content.select_mcp(self.content, ["context7"])
        self.assertEqual(self.content.mcp, before_mcp)
        self.assertEqual(self.content.agents, before_agents)
        self.assertEqual(self.agent.optional_mcp, ("context7", "other"))



if __name__ == "__main__":
    unittest.main()
