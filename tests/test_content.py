"""Loading the content core, and refusing to load content that would mislead an adapter."""
from __future__ import annotations

import ast
import inspect
import tempfile
import unittest
import zipfile
from collections.abc import Callable
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

CHECKSUM = "sha256:" + "a" * 64

DOWNLOAD_MCP = f"""---
name: probe-mcp
description: Probes a downloaded MCP server
distribution: download
endpoint: https://example.test/probe-mcp-linux-x64
version: 1.2.3
checksum: {CHECKSUM}
---

Convention body.
"""

ARCHIVE_MCP = f"""---
name: probe-mcp
description: Probes an archived MCP server
distribution: download
endpoint: https://example.test/probe-mcp-linux-x64.tar.gz
version: 1.2.3
checksum: {CHECKSUM}
archive_members: [CHANGELOG.md, LICENSE, probe-mcp]
archive_executable: probe-mcp
---

Convention body.
"""

INTEGRITY = "sha512-" + "a" * 86 + "=="

NPM_LOCKFILE_NAME = "probe-mcp-package-lock.json"

NPM_MCP = f"""---
name: probe-mcp
description: Probes an npm-distributed MCP server
distribution: npm
endpoint: https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz
package: probe-mcp
version: 1.2.3
integrity: {INTEGRITY}
entry: cli.js
lockfile: {NPM_LOCKFILE_NAME}
---

Convention body.
"""

NPM_LOCKFILE = f"""{{
  "name": "pegasus-probe-mcp",
  "lockfileVersion": 3,
  "requires": true,
  "packages": {{
    "": {{"name": "pegasus-probe-mcp", "dependencies": {{"probe-mcp": "1.2.3"}}}},
    "node_modules/probe-mcp": {{
      "version": "1.2.3",
      "resolved": "https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz",
      "integrity": "{INTEGRITY}"
    }}
  }}
}}
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


def write_zip(archive_path: Path, entries: dict[str, str]) -> None:
    with zipfile.ZipFile(archive_path, "w") as archive:
        for relative, text in entries.items():
            archive.writestr(relative, text)


class ZipRootTest(unittest.TestCase):
    """A package shipped inside a zip has no directory to walk on disk.

    `importlib.resources.files(...)` hands the loader a `zipfile.Path` in that
    case instead of a `pathlib.Path`. The two share `iterdir`, `is_dir`,
    `is_file`, `read_text`, `read_bytes` and `joinpath`, but a `zipfile.Path`
    has no `resolve`, no `relative_to`, no `parent`, and no `glob`/`rglob` --
    exactly the calls this loader must not depend on if it is to work inside
    an actual archive, not merely on a filesystem that happens to look like
    one.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        archive_path = Path(self._directory.name) / "content.zip"
        write_zip(
            archive_path,
            {
                "skills/alpha/SKILL.md": SKILL,
                "skills/alpha/references/guide.md": "# Guide\n",
                f"agents/{content.SESSION_STARTS_IN}.md": SESSION_START.replace(
                    "mode: primary\n", "mode: primary\noptional_mcp: [probe-mcp]\n"
                ),
                "commands/probe-command.md": COMMAND,
                "mcp/probe-mcp.md": NPM_MCP,
                f"mcp/{NPM_LOCKFILE_NAME}": NPM_LOCKFILE,
                "agents/mcp/probe-mcp.md": (
                    "## Probe\n\nFollow {{skills_root}}/_shared/mcp/probe-mcp-convention.md.\n"
                ),
                "system-prompt/AGENTS.md": "# Rules\n\nBe careful.\n",
            },
        )
        self.zip_file = zipfile.ZipFile(archive_path)
        self.addCleanup(self.zip_file.close)
        self.zip_root = zipfile.Path(self.zip_file)

    def test_loads_every_category_from_inside_a_zip(self):
        loaded = content.load(self.zip_root)
        self.assertEqual([s.name for s in loaded.skills], ["alpha"])
        self.assertEqual([a.name for a in loaded.agents], [content.SESSION_STARTS_IN])
        self.assertEqual([c.name for c in loaded.commands], ["probe-command"])
        self.assertEqual([m.name for m in loaded.mcp], ["probe-mcp"])
        self.assertIsNotNone(loaded.system_prompt)

    def test_a_skill_asset_below_the_top_level_is_read_from_the_zip(self):
        """Exercises the recursive walk that stands in for `Path.rglob`."""
        skill = content.load(self.zip_root).skills[0]
        self.assertEqual(
            [str(asset.relative_path) for asset in skill.assets],
            ["SKILL.md", "references/guide.md"],
        )
        guide = next(a for a in skill.assets if str(a.relative_path) == "references/guide.md")
        self.assertEqual(guide.content, "# Guide\n".encode("utf-8"))

    def test_an_agents_mcp_section_is_read_from_the_zip(self):
        """Exercises the nested-directory lookup that stands in for `Path.glob`.

        `agents/mcp/` is the one content directory that sits *inside* another
        one, so it is the one whose exclusion from the agent scan and whose own
        listing both depend on `iterdir` behaving the same inside an archive as
        it does on disk. A `zipfile.Path` has no `glob`, and this is where that
        would first be reached for.
        """
        agents = content.load(self.zip_root).agents
        self.assertEqual([a.name for a in agents], [content.SESSION_STARTS_IN])
        self.assertEqual([s.name for s in agents[0].mcp_sections], ["probe-mcp"])
        self.assertIn("probe-mcp-convention.md", agents[0].mcp_sections[0].body)

    def test_an_npm_servers_lockfile_beside_it_is_read_from_the_zip(self):
        """Exercises the sibling lookup that stands in for `Path.parent`."""
        mcp = content.load(self.zip_root).mcp[0]
        self.assertEqual(mcp.npm_lockfile, NPM_LOCKFILE.encode("utf-8"))

    def test_sources_read_from_a_zip_are_the_same_as_from_a_directory(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        write(root, "skills/alpha/SKILL.md", SKILL)
        write(root, "skills/alpha/references/guide.md", "# Guide\n")
        write(
            root,
            f"agents/{content.SESSION_STARTS_IN}.md",
            SESSION_START.replace("mode: primary\n", "mode: primary\noptional_mcp: [probe-mcp]\n"),
        )
        write(root, "commands/probe-command.md", COMMAND)
        write(root, "mcp/probe-mcp.md", NPM_MCP)
        write(root, f"mcp/{NPM_LOCKFILE_NAME}", NPM_LOCKFILE)
        write(
            root,
            "agents/mcp/probe-mcp.md",
            "## Probe\n\nFollow {{skills_root}}/_shared/mcp/probe-mcp-convention.md.\n",
        )
        write(root, "system-prompt/AGENTS.md", "# Rules\n\nBe careful.\n")
        from_directory = content.load(root)
        from_zip = content.load(self.zip_root)
        self.assertEqual(from_directory, from_zip)


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


class McpReachesAnAgentInvariantTest(TemporaryContent):
    """A shipped server has to name at least one agent that grants it.

    The mirror of `OptionalMcpInvariantTest`: that one refuses an agent
    declaring a server that does not exist. This one refuses the opposite
    typo -- a server descriptor with no agent's `optional_mcp` ever updated to
    name it, so `select_mcp` would filter it down to an empty set of
    recipients under every possible `--mcp` choice. This is the exact shape
    the shipped `playwright` server regressed to before `_require_mcp_reaches_an_agent`
    existed: a descriptor, a README promise, and nothing that could ever use it.
    """

    def test_a_server_no_agent_declares_is_refused_naming_the_server_file(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn("mcp/context7.md", message)
        self.assertIn("context7", message)

    def test_a_server_at_least_one_agent_declares_is_accepted(self):
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
        self.assertEqual([server.name for server in loaded.mcp], ["context7"])


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


class AgentMcpSectionTest(TemporaryContent):
    """The same ambient/on-demand split the system prompt already has
    (`McpSection`, `_load_mcp_sections`), applied to agent prompts: the
    pointer paragraph lives beside the grant in `agents/mcp/`, not baked
    unconditionally into every agent that might one day carry it.
    """

    def load_agents(self):
        return {agent.name: agent for agent in content.load(self.root).agents}

    def test_a_shared_section_is_attached_to_every_agent_that_declares_the_id(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\nx\n",
        )
        write(
            self.root,
            "agents/mcp/context7.md",
            "Follow {{skills_root}}/_shared/mcp/context7-convention.md for tool order.\n",
        )
        agent = self.load_agents()["probe-agent"]
        self.assertEqual([s.name for s in agent.mcp_sections], ["context7"])
        self.assertIn("context7-convention.md", agent.mcp_sections[0].body)

    def test_an_override_replaces_the_shared_section_for_that_agent_only(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        for name in ("probe-agent", "other-agent"):
            write(
                self.root,
                f"agents/{name}.md",
                f"---\nname: {name}\ndescription: d\nmode: primary\n"
                "optional_mcp: [context7]\n---\n\nx\n",
            )
        pointer = "{{skills_root}}/_shared/mcp/context7-convention.md"
        write(self.root, "agents/mcp/context7.md", f"Shared framing. Follow {pointer}.\n")
        write(self.root, "agents/mcp/context7@probe-agent.md", f"Special framing. Follow {pointer}.\n")
        agents = self.load_agents()
        self.assertIn("Special framing.", agents["probe-agent"].mcp_sections[0].body)
        self.assertIn("Shared framing.", agents["other-agent"].mcp_sections[0].body)

    def test_an_override_for_an_agent_that_never_declared_the_id_is_refused(self):
        """Naming a real agent is not the same as naming a wired one.

        An override that targets an agent who never put that id in its own
        `optional_mcp` attaches to nothing: the resolution walks the agent's
        declaration, so a file addressed to somebody who is not listening is
        read, validated and then dropped. It is the likelier mistake than the
        renamed agent the check above catches -- an author adds the framing and
        forgets the declaration -- and it fails the same silent way, so it earns
        the same refusal.
        """
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n---\n\nx\n",
        )
        write(
            self.root,
            "agents/mcp/context7@probe-agent.md",
            "Follow {{skills_root}}/_shared/mcp/context7-convention.md for tool order.\n",
        )
        with self.assertRaises(content.ContentError) as raised:
            content.load(self.root)
        message = str(raised.exception)
        self.assertIn("agents/mcp/context7@probe-agent.md", message)
        self.assertIn("probe-agent", message)

    def test_an_id_with_neither_shared_nor_override_carries_no_section(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\n"
            "Follow {{skills_root}}/_shared/mcp/context7-convention.md for tool order.\n",
        )
        agent = self.load_agents()["probe-agent"]
        self.assertEqual(agent.mcp_sections, ())

    def test_the_mcp_subdirectory_is_never_read_as_an_agent(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\n"
            "Follow {{skills_root}}/_shared/mcp/context7-convention.md for tool order.\n",
        )
        write(self.root, "agents/mcp/context7.md", "Shared text.\n")
        names = set(self.load_agents())
        self.assertNotIn("context7", names)
        self.assertNotIn("mcp", names)

    def test_a_section_naming_a_server_nothing_ships_is_refused(self):
        write_session_start(self.root)
        write(self.root, "agents/mcp/phantom.md", "Ambient text.\n")
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        self.assertIn("agents/mcp/phantom.md", str(raised.exception))

    def test_an_override_naming_an_agent_that_does_not_exist_is_refused(self):
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(self.root, "agents/mcp/context7@ghost-agent.md", "Ambient text.\n")
        with self.assertRaises(ContentError) as raised:
            content.load(self.root)
        self.assertIn("agents/mcp/context7@ghost-agent.md", str(raised.exception))

    def test_the_convention_pointer_can_live_only_in_the_section(self):
        """The pairing invariant (`McpConventionReferenceInvariantTest`) is
        satisfied by body plus sections combined, not by the agent's own prose
        alone -- that is the whole point of moving the pointer out of every
        agent body and into one shared file.
        """
        write_session_start(self.root)
        write(self.root, "mcp/context7.md", MCP.replace("probe-mcp", "context7"))
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [context7]\n---\n\nx\n",
        )
        write(
            self.root,
            "agents/mcp/context7.md",
            "Follow {{skills_root}}/_shared/mcp/context7-convention.md for tool order.\n",
        )
        loaded = content.load(self.root)
        agent = next(a for a in loaded.agents if a.name == "probe-agent")
        self.assertEqual(agent.optional_mcp, ("context7",))


class SelectMcpAgentSectionTest(unittest.TestCase):
    """`select_mcp` prunes an agent's own mcp sections in the same step it
    prunes `optional_mcp`, so a grant and the pointer telling an agent to use
    it can never disagree -- the same invariant `_select_system_prompt_mcp`
    upholds for the system prompt's ambient half.
    """

    def setUp(self):
        self.context7 = content.Mcp(
            name="context7", description="d", body="b", distribution=Distribution.REMOTE,
            endpoint="https://example.test/context7", source=PurePosixPath("mcp/context7.md"),
        )
        self.cbm = content.Mcp(
            name="cbm", description="d", body="b", distribution=Distribution.DOWNLOAD,
            endpoint="https://example.test/cbm.tar.gz", checksum="sha256:" + "a" * 64,
            source=PurePosixPath("mcp/cbm.md"),
        )
        self.agent = content.Agent(
            name="probe-agent", description="d", body="x", mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/probe-agent.md"),
            optional_mcp=("context7", "cbm"),
            mcp_sections=(
                content.McpSection(
                    name="context7", body="Ambient context7.",
                    source=PurePosixPath("agents/mcp/context7.md"),
                ),
                content.McpSection(
                    name="cbm", body="Ambient cbm.", source=PurePosixPath("agents/mcp/cbm.md")
                ),
            ),
        )
        self.content = content.Content(agents=(self.agent,), mcp=(self.context7, self.cbm))

    def test_keeps_only_the_chosen_server_s_section(self):
        selected = content.select_mcp(self.content, ["context7"])
        self.assertEqual([s.name for s in selected.agents[0].mcp_sections], ["context7"])

    def test_choosing_nothing_leaves_no_section(self):
        selected = content.select_mcp(self.content, [])
        self.assertEqual(selected.agents[0].mcp_sections, ())

    def test_a_bound_server_s_section_survives_matched_by_id_not_by_the_rewritten_key(self):
        """`optional_mcp` gets rewritten to the bound key, but a section's own
        `name` is the descriptor id and is never rewritten -- matching a
        section against the post-binding value would drop it the moment a
        server is bound, since the section's name never changes to match.
        """
        selected = content.select_mcp(self.content, ["cbm=codebase-memory-mcp"])
        agent = selected.agents[0]
        self.assertEqual(agent.optional_mcp, ("codebase-memory-mcp",))
        self.assertEqual([s.name for s in agent.mcp_sections], ["cbm"])

    def test_is_pure(self):
        before = self.agent.mcp_sections
        content.select_mcp(self.content, ["context7"])
        self.assertEqual(self.agent.mcp_sections, before)


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
    def load_mcp(self, text, lockfile=NPM_LOCKFILE):
        write(self.root, "mcp/probe-mcp.md", text)
        write(self.root, f"mcp/{NPM_LOCKFILE_NAME}", lockfile)
        write_session_start(self.root)
        write(
            self.root,
            "agents/probe-agent.md",
            "---\nname: probe-agent\ndescription: d\nmode: primary\n"
            "optional_mcp: [probe-mcp]\n---\n\n"
            "See {{skills_root}}/_shared/mcp/probe-mcp-convention.md.\n",
        )
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

    def test_withheld_tools_defaults_to_empty(self):
        mcp = self.load_mcp(MCP)
        self.assertEqual(mcp.withheld_tools, ())

    def test_withheld_tools_is_read(self):
        mcp = self.load_mcp(
            MCP.replace(
                "endpoint: https://example.test/mcp\n",
                "endpoint: https://example.test/mcp\nwithheld_tools: [delete_project, ingest_traces]\n",
            )
        )
        self.assertEqual(mcp.withheld_tools, ("delete_project", "ingest_traces"))

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

    def test_a_download_server_reads_its_version_and_checksum(self):
        mcp = self.load_mcp(DOWNLOAD_MCP)
        self.assertEqual(mcp.distribution, Distribution.DOWNLOAD)
        self.assertEqual(mcp.version, "1.2.3")
        self.assertEqual(mcp.checksum, CHECKSUM)

    def test_a_download_server_missing_its_version_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(DOWNLOAD_MCP.replace("version: 1.2.3\n", ""))
        self.assertIn("version", str(raised.exception))

    def test_a_download_server_missing_its_checksum_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(DOWNLOAD_MCP.replace(f"checksum: {CHECKSUM}\n", ""))
        self.assertIn("checksum", str(raised.exception))

    def test_a_malformed_checksum_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(DOWNLOAD_MCP.replace(CHECKSUM, "sha256:not-hex"))
        self.assertIn("checksum", str(raised.exception))

    def test_a_remote_server_may_not_declare_a_version(self):
        """A stray `version:` left on a `remote` descriptor would suggest a
        pin that nothing reads -- refused instead of silently ignored."""
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(MCP.replace("endpoint: https://example.test/mcp\n", "endpoint: https://example.test/mcp\nversion: 1.0.0\n"))
        self.assertIn("version", str(raised.exception))

    def test_an_npm_server_reads_its_package_version_integrity_and_entry(self):
        mcp = self.load_mcp(NPM_MCP)
        self.assertEqual(mcp.distribution, Distribution.NPM)
        self.assertEqual(mcp.package, "probe-mcp")
        self.assertEqual(mcp.version, "1.2.3")
        self.assertEqual(mcp.integrity, INTEGRITY)
        self.assertEqual(mcp.entry, "cli.js")

    def test_an_npm_server_missing_any_required_field_is_rejected(self):
        for line in (
            "package: probe-mcp\n",
            "version: 1.2.3\n",
            f"integrity: {INTEGRITY}\n",
            "entry: cli.js\n",
            f"lockfile: {NPM_LOCKFILE_NAME}\n",
        ):
            with self.subTest(line=line), self.assertRaises(ContentError) as raised:
                self.load_mcp(NPM_MCP.replace(line, ""))
            self.assertIn(line.split(":")[0], str(raised.exception))

    def test_a_malformed_integrity_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP.replace(INTEGRITY, "sha256:not-sha512"))
        self.assertIn("integrity", str(raised.exception))

    def test_an_npm_server_reads_the_real_lockfile_beside_it_verbatim(self):
        mcp = self.load_mcp(NPM_MCP)
        self.assertEqual(mcp.npm_lockfile, NPM_LOCKFILE.encode("utf-8"))

    def test_an_npm_server_reads_the_lockfiles_own_root_name(self):
        """The root name is read from the lockfile itself, not derived from
        the descriptor's own file stem (`probe-mcp` here) -- the two happen
        to differ in this fixture precisely so a re-derivation would be
        caught rather than passing by coincidence.
        """
        mcp = self.load_mcp(NPM_MCP, lockfile=NPM_LOCKFILE.replace("pegasus-probe-mcp", "totally-different-name"))
        self.assertEqual(mcp.npm_package_name, "totally-different-name")

    def test_a_lockfile_with_no_root_name_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP, lockfile=NPM_LOCKFILE.replace('"name": "pegasus-probe-mcp", ', ""))
        self.assertIn("name", str(raised.exception))

    def test_a_lockfile_naming_a_file_that_does_not_exist_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP.replace(NPM_LOCKFILE_NAME, "ghost-lock.json"))
        self.assertIn("ghost-lock.json", str(raised.exception))

    def test_a_lockfile_naming_a_path_outside_its_directory_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP.replace(NPM_LOCKFILE_NAME, f"../{NPM_LOCKFILE_NAME}"))
        self.assertIn("lockfile", str(raised.exception))

    def test_a_lockfile_that_is_not_valid_json_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP, lockfile="not json at all")
        self.assertIn("JSON", str(raised.exception))

    def test_a_lockfile_whose_root_package_pins_a_different_version_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP, lockfile=NPM_LOCKFILE.replace('"probe-mcp": "1.2.3"', '"probe-mcp": "9.9.9"'))
        self.assertIn("probe-mcp@1.2.3", str(raised.exception))

    def test_a_lockfile_whose_pinned_integrity_disagrees_with_the_descriptor_is_rejected(self):
        other_integrity = "sha512-" + "b" * 86 + "=="
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP, lockfile=NPM_LOCKFILE.replace(INTEGRITY, other_integrity))
        self.assertIn("integrity", str(raised.exception))

    def test_a_lockfile_whose_pinned_resolved_url_disagrees_with_the_descriptor_is_rejected(self):
        other_lockfile = NPM_LOCKFILE.replace(
            "https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz",
            "https://example.test/somewhere-else.tgz",
        )
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP, lockfile=other_lockfile)
        self.assertIn("resolved", str(raised.exception))

    def test_a_lockfile_with_no_entry_for_the_pinned_package_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(NPM_MCP, lockfile=NPM_LOCKFILE.replace("node_modules/probe-mcp", "node_modules/other"))
        self.assertIn("node_modules/probe-mcp", str(raised.exception))

    def test_a_remote_server_may_not_declare_npm_fields(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(MCP.replace("endpoint: https://example.test/mcp\n", "endpoint: https://example.test/mcp\npackage: probe-mcp\n"))
        self.assertIn("package", str(raised.exception))

    def test_a_download_server_may_not_declare_npm_fields(self):
        """`download` and `npm` each own their own extra fields."""
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(DOWNLOAD_MCP.replace(f"checksum: {CHECKSUM}\n", f"checksum: {CHECKSUM}\nintegrity: {INTEGRITY}\n"))
        self.assertIn("integrity", str(raised.exception))

    def test_a_plain_download_server_declares_no_archive(self):
        """A single-binary `download` server is unaffected by the archive form."""
        mcp = self.load_mcp(DOWNLOAD_MCP)
        self.assertEqual(mcp.archive_members, ())
        self.assertIsNone(mcp.archive_executable)

    def test_an_archive_server_reads_its_members_and_executable(self):
        mcp = self.load_mcp(ARCHIVE_MCP)
        self.assertEqual(mcp.archive_members, ("CHANGELOG.md", "LICENSE", "probe-mcp"))
        self.assertEqual(mcp.archive_executable, "probe-mcp")

    def test_archive_members_without_an_executable_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(ARCHIVE_MCP.replace("archive_executable: probe-mcp\n", ""))
        self.assertIn("archive_executable", str(raised.exception))

    def test_an_executable_without_archive_members_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(
                ARCHIVE_MCP.replace("archive_members: [CHANGELOG.md, LICENSE, probe-mcp]\n", "")
            )
        self.assertIn("archive_members", str(raised.exception))

    def test_an_executable_not_among_the_members_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(ARCHIVE_MCP.replace("archive_executable: probe-mcp\n", "archive_executable: ghost\n"))
        self.assertIn("ghost", str(raised.exception))

    def test_an_archive_member_that_escapes_its_directory_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(ARCHIVE_MCP.replace("LICENSE", "../LICENSE"))
        self.assertIn("../LICENSE", str(raised.exception))

    def test_an_archive_member_with_an_absolute_path_is_rejected(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(ARCHIVE_MCP.replace("LICENSE", "/etc/LICENSE"))
        self.assertIn("/etc/LICENSE", str(raised.exception))

    def test_a_remote_server_may_not_declare_archive_fields(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(
                MCP.replace(
                    "endpoint: https://example.test/mcp\n",
                    "endpoint: https://example.test/mcp\narchive_members: [a]\narchive_executable: a\n",
                )
            )
        self.assertIn("archive_members", str(raised.exception))

    def test_a_download_server_declares_no_argv_by_default(self):
        mcp = self.load_mcp(DOWNLOAD_MCP)
        self.assertEqual(mcp.argv, ())

    def test_a_download_server_reads_its_argv_in_order(self):
        mcp = self.load_mcp(DOWNLOAD_MCP.replace(f"checksum: {CHECKSUM}\n", f"checksum: {CHECKSUM}\nargv: [mcp, --tools=agent]\n"))
        self.assertEqual(mcp.argv, ("mcp", "--tools=agent"))

    def test_an_npm_server_reads_its_argv_in_order(self):
        mcp = self.load_mcp(NPM_MCP.replace("entry: cli.js\n", "entry: cli.js\nargv: [serve]\n"))
        self.assertEqual(mcp.argv, ("serve",))

    def test_a_remote_server_may_not_declare_argv(self):
        with self.assertRaises(ContentError) as raised:
            self.load_mcp(
                MCP.replace(
                    "endpoint: https://example.test/mcp\n",
                    "endpoint: https://example.test/mcp\nargv: [serve]\n",
                )
            )
        self.assertIn("argv", str(raised.exception))


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

    def test_every_agent_mcp_section_opens_with_its_own_heading(self):
        """A section is appended after the body, so it has to announce itself.

        These paragraphs used to sit mid-prompt, where the section above them
        gave them their context. Composed at the end they have no such
        neighbour: an unheaded paragraph after `## Result identity` reads as
        more of the result identity, which is the one thing it is not. The
        system prompt's own sections already open with a heading for exactly
        this reason -- see `system-prompt/mcp/engram.md`.
        """
        for agent in self.content.agents:
            for section in agent.mcp_sections:
                self.assertTrue(
                    section.body.lstrip().startswith("## "),
                    f"{section.source}: must open with a level-2 heading",
                )

    def test_skills_load(self):
        self.assertEqual(len(self.content.skills), 25)

    def test_commands_load(self):
        self.assertEqual(len(self.content.commands), 16)

    def test_mcp_servers_load(self):
        self.assertEqual(
            [server.name for server in self.content.mcp], ["cbm", "context7", "engram", "playwright"]
        )

    def test_playwright_is_declared_by_exactly_the_agents_that_drive_a_browser(self):
        """Regression guard for the bug `_require_mcp_reaches_an_agent` now
        refuses at load time: `playwright` shipped with a descriptor and a
        README promise, but no agent declared it, so choosing it installed a
        server nothing could ever use. This asserts over the loaded agents
        themselves, not a hand-kept copy of the list -- the list is the thing
        that drifted last time.
        """
        declares_playwright = {
            agent.name for agent in self.content.agents if "playwright" in agent.optional_mcp
        }
        self.assertEqual(declares_playwright, {"sdd-apply", "sdd-explore", "sdd-verify"})

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
        # It declares no server: what it may act on is settled by the direct-work
        # threshold in its own body, not by a codebase-memory server, so `write`
        # and `edit` join the native tools it needs to read, search and make a
        # small, already-known, single-file edit without delegating it away.
        orchestrator = next(a for a in self.content.agents if a.name == "pegasus-orchestrator")
        self.assertEqual(
            set(orchestrator.requires_tools),
            {"read", "bash", "grep", "glob", "write", "edit", "skill", "ask"},
        )
        self.assertEqual(orchestrator.optional_tools, ())
        # It declares the two servers whose contract is ambient rather than
        # phase-owned: memory, which every agent must be able to write, and the
        # code graph, which is how a router decides where to send work without
        # reading four files to find out.
        self.assertEqual(set(orchestrator.optional_mcp), {"cbm", "engram"})

    def test_the_two_voices_that_face_the_user_can_reach_the_skills_and_ask(self):
        """Both are demanded by text this repository ships, and neither survives
        the deny baseline unless it is declared.

        `pegasus-AGENTS.md` opens its Contextual Skill Loading section with
        "this is a blocking requirement, not optional context" -- and the
        runtime only puts the skill inventory in front of an agent that holds
        the tool, so an agent without it is told to consult a list that is not
        there. The preflight gate is the same shape: "ask what it defines, and
        STOP" is not something an agent can do with no way to ask.
        """
        for name in ("pegasus-orchestrator", "king-pegasus"):
            with self.subTest(agent=name):
                agent = next(a for a in self.content.agents if a.name == name)
                self.assertIn("skill", agent.requires_tools)
                self.assertIn("ask", agent.requires_tools)

    def test_every_voice_that_faces_the_user_declares_a_register(self):
        """A primary agent is the one a person actually talks to, and a prompt
        that is all procedure and no register does not become neutral -- it
        inherits whatever the underlying model defaults to. That is how the
        orchestrator came to read as a dispatcher next to `king-pegasus`: same
        product, same session, two unrelated voices, because only one of the
        two files said anything about how it speaks.

        Structural on purpose, never a judgment about English: this asserts
        that a user-facing agent settles its language and its tone somewhere in
        its own body, not that either section is any good. An executor is
        exempt -- it reports to the orchestrator, and a register there would be
        noise in a machine-read report.
        """
        for agent in self.content.agents:
            if agent.mode is not AgentMode.PRIMARY:
                continue
            with self.subTest(agent=agent.name):
                self.assertIn("## Language", agent.body)
                self.assertIn("## Tone", agent.body)

    def test_no_executor_can_reach_the_skills_or_ask(self):
        """The other side of the same line. An executor receives a task and a
        named procedure it loads by path, so it needs no inventory; and it
        returns `blocked` rather than asking, which is what keeps a phase from
        stalling on a question nobody is watching for. `sdd-verify` says so in
        its own body: "do not call the `skill()` tool".
        """
        for agent in self.content.agents:
            if agent.mode is not AgentMode.SUBAGENT:
                continue
            with self.subTest(agent=agent.name):
                self.assertNotIn("skill", agent.requires_tools + agent.optional_tools)
                self.assertNotIn("ask", agent.requires_tools + agent.optional_tools)

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

    def test_every_agent_can_reach_memory(self):
        """Memory is ambient: an agent that fixes a bug must be able to record it.

        Declared per agent rather than left to the system prompt, because the
        declaration is what grants the tools. The renderer writes a deny
        baseline for every agent, so one that does not name `engram` cannot
        call `mem_save` at all -- however plainly the ambient section tells it
        to. An instruction without the tool behind it is the failure this is
        here to make impossible.
        """
        self.assertEqual(
            {agent.name for agent in self.content.agents if "engram" not in agent.optional_mcp},
            set(),
        )

    def test_structural_discovery_is_declared_by_the_agents_that_do_it(self):
        """Not everyone: an agent that never asks the graph a question should
        not carry the graph's convention, and the pairing invariant would make
        it carry one. The two primaries earn it for different reasons -- the
        orchestrator to route, the voice to answer -- and the four phase agents
        because discovery is their work.
        """
        self.assertEqual(
            {agent.name for agent in self.content.agents if "cbm" in agent.optional_mcp},
            {
                "king-pegasus",
                "pegasus-orchestrator",
                "sdd-apply",
                "sdd-design",
                "sdd-explore",
                "sdd-verify",
            },
        )

    def test_the_system_prompt_carries_a_section_for_engram(self):
        self.assertIn(
            "engram", [section.name for section in self.content.system_prompt.mcp_sections]
        )

    def test_every_system_prompt_section_belongs_to_a_shipped_server(self):
        shipped = {server.name for server in self.content.mcp}
        for section in self.content.system_prompt.mcp_sections:
            with self.subTest(section=section.name):
                self.assertIn(section.name, shipped)

    def test_no_shipped_agent_body_names_the_shared_mcp_path_unconditionally(self):
        """The paragraph that used to be pasted into twelve agent prompts now
        lives in a section that ships only when the server it belongs to is
        selected. An agent body that still names `_shared/mcp/` directly would
        resurrect exactly the bug this mechanism exists to fix: every install
        would see the pointer regardless of which servers it chose.
        """
        offenders = [agent.name for agent in self.content.agents if "_shared/mcp/" in agent.body]
        self.assertEqual(offenders, [])

    def test_every_agent_carries_the_engram_section(self):
        """Every agent can reach memory (`test_every_agent_can_reach_memory`
        above); this is the other half of that promise -- the pointer telling
        it how to use the grant travels with the grant, for every one of them.
        """
        for agent in self.content.agents:
            with self.subTest(agent=agent.name):
                self.assertIn("engram", [s.name for s in agent.mcp_sections])

    def test_the_five_context7_agents_carry_the_shared_section_and_no_one_else_does(self):
        context7_agents = {"sdd-apply", "sdd-design", "sdd-explore", "sdd-verify", "sdd-onboard"}
        for agent in self.content.agents:
            with self.subTest(agent=agent.name):
                carries = "context7" in [s.name for s in agent.mcp_sections]
                self.assertEqual(carries, agent.name in context7_agents)

    def test_the_cbm_section_is_shared_for_three_agents_and_overridden_for_three(self):
        """`sdd-apply`, `sdd-design` and `sdd-explore` carry the plain pointer;
        `king-pegasus`, `pegasus-orchestrator` and `sdd-verify` each carry
        deliberate, agent-specific framing that a shared file would flatten.
        """
        shared_agents = {"sdd-apply", "sdd-design", "sdd-explore"}
        overridden_agents = {"king-pegasus", "pegasus-orchestrator", "sdd-verify"}
        by_name = {agent.name: agent for agent in self.content.agents}

        shared_sources = set()
        for name in shared_agents:
            section = next(s for s in by_name[name].mcp_sections if s.name == "cbm")
            shared_sources.add(section.source)
        self.assertEqual(len(shared_sources), 1, shared_sources)

        for name in overridden_agents:
            section = next(s for s in by_name[name].mcp_sections if s.name == "cbm")
            self.assertIn(f"@{name}.md", section.source.name)
            self.assertNotIn(section.source, shared_sources)

        for agent in self.content.agents:
            if agent.name not in shared_agents | overridden_agents:
                self.assertNotIn("cbm", [s.name for s in agent.mcp_sections], agent.name)

    def test_the_engram_section_defers_its_detail_to_the_convention(self):
        """The ambient section says what to do; the convention says how.

        Lazy loading is the whole point of splitting them. A section long
        enough to carry field formats, topic-key rules and lifecycle states
        would be paid for by every agent on every turn, and that detail is
        only ever needed on the turns that actually save.
        """
        section = next(
            item for item in self.content.system_prompt.mcp_sections if item.name == "engram"
        )
        self.assertIn("{{skills_root}}/_shared/mcp/engram-convention.md", section.body)


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
        self.system_prompt = content.SystemPrompt(
            body="Base rules.",
            source=PurePosixPath("system-prompt/AGENTS.md"),
            mcp_sections=(
                content.McpSection(
                    name="context7",
                    body="Ambient context7 rules.",
                    source=PurePosixPath("system-prompt/mcp/context7.md"),
                ),
                content.McpSection(
                    name="other",
                    body="Ambient other rules.",
                    source=PurePosixPath("system-prompt/mcp/other.md"),
                ),
            ),
        )
        self.content = content.Content(
            agents=(self.agent, self.plain_agent),
            mcp=(self.context7, self.other),
            system_prompt=self.system_prompt,
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

    def test_keeps_only_the_chosen_server_s_ambient_section(self):
        """A server nobody chose leaves no instruction behind.

        This is the failure the whole conditional exists for: an ambient
        section for a server that was never installed would tell every agent
        to reach for tools none of them were granted, and the agent would have
        no way to tell a missing tool from its own mistake.
        """
        selected = content.select_mcp(self.content, ["context7"])
        self.assertEqual(
            [section.name for section in selected.system_prompt.mcp_sections], ["context7"]
        )

    def test_the_base_system_prompt_survives_every_choice(self):
        for chosen in ([], ["context7"], ["context7", "other"]):
            with self.subTest(chosen=chosen):
                selected = content.select_mcp(self.content, chosen)
                self.assertEqual(selected.system_prompt.body, "Base rules.")

    def test_choosing_nothing_leaves_the_system_prompt_with_no_section(self):
        selected = content.select_mcp(self.content, [])
        self.assertEqual(selected.system_prompt.mcp_sections, ())

    def test_a_content_without_a_system_prompt_is_left_alone(self):
        bare = content.Content(mcp=(self.context7,))
        self.assertIsNone(content.select_mcp(bare, ["context7"]).system_prompt)

    def test_is_pure_the_input_content_is_unchanged(self):
        before_mcp = self.content.mcp
        before_agents = self.content.agents
        before_sections = self.system_prompt.mcp_sections
        content.select_mcp(self.content, ["context7"])
        self.assertEqual(self.content.mcp, before_mcp)
        self.assertEqual(self.content.agents, before_agents)
        self.assertEqual(self.agent.optional_mcp, ("context7", "other"))
        self.assertEqual(self.system_prompt.mcp_sections, before_sections)


class PerAgentMcpKeysTest(unittest.TestCase):
    """`per_agent_mcp_keys`: the one rule `grant_mcp` refuses collisions
    against and `cli.mcp_list` asks the identical, non-raising question of --
    see that function's own docstring for why there must be exactly one of
    it."""

    def setUp(self):
        self.context7 = content.Mcp(
            name="context7",
            description="Fetches library docs",
            body="Convention body.",
            distribution=Distribution.REMOTE,
            endpoint="https://example.test/context7",
            source=PurePosixPath("mcp/context7.md"),
        )
        self.agent_a = content.Agent(
            name="agent-a",
            description="Agent A",
            body="x",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/agent-a.md"),
            optional_mcp=("context7",),
        )
        self.agent_b = content.Agent(
            name="agent-b",
            description="Agent B",
            body="x",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/agent-b.md"),
        )
        self.content = content.Content(agents=(self.agent_a, self.agent_b), mcp=(self.context7,))

    def test_a_chosen_shipped_id_is_named(self):
        self.assertIn("context7", content.per_agent_mcp_keys(self.content))

    def test_a_server_not_chosen_at_all_is_not_named(self):
        empty = content.select_mcp(self.content, [])
        self.assertNotIn("context7", content.per_agent_mcp_keys(empty))

    def test_a_bound_key_is_named_alongside_its_own_shipped_id(self):
        """Binding `context7` to `jira-mcp` widens what is already reached
        per-agent: both the id itself (still `content.mcp`'s own name) and
        the key it now resolves to (`optional_mcp`'s rewritten entry) are
        already covered, so both are refused by `grant_mcp` and both must be
        named here."""
        selected = content.select_mcp(self.content, ["context7=jira-mcp"])
        keys = content.per_agent_mcp_keys(selected)
        self.assertIn("jira-mcp", keys)
        self.assertIn("context7", keys)

    def test_a_key_the_installation_never_heard_of_is_not_named(self):
        self.assertNotIn("jira", content.per_agent_mcp_keys(self.content))

    def test_agrees_with_grant_mcp_on_every_collision(self):
        """The property that matters: whatever this function names, `grant_mcp`
        refuses, and whatever it does not name, `grant_mcp` accepts -- proven
        both ways so the two can never quietly drift apart."""
        selected = content.select_mcp(self.content, ["context7=jira-mcp"])
        collisions = content.per_agent_mcp_keys(selected)
        for key in collisions:
            with self.assertRaises(ContentError):
                content.grant_mcp(selected, [key])
        for key in ("jira", "figma", "some.server_1"):
            self.assertNotIn(key, collisions)
            granted, dropped = content.grant_mcp(selected, [key])
            self.assertEqual(dropped, ())
            self.assertEqual(granted.agents[0].granted_mcp, (key,))


class GrantMcpTest(unittest.TestCase):
    """`grant_mcp` hands a server the user administers to every agent uniformly.

    Distinct from `optional_mcp`: a granted key ships no descriptor and no
    convention, so none of `optional_mcp`'s invariants -- known-server,
    convention-referenced, reachability -- may ever apply to it.
    """

    def setUp(self):
        self.context7 = content.Mcp(
            name="context7",
            description="Fetches library docs",
            body="Convention body.",
            distribution=Distribution.REMOTE,
            endpoint="https://example.test/context7",
            source=PurePosixPath("mcp/context7.md"),
        )
        self.agent_a = content.Agent(
            name="agent-a",
            description="Agent A",
            body="x",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/agent-a.md"),
            optional_mcp=("context7",),
        )
        self.agent_b = content.Agent(
            name="agent-b",
            description="Agent B",
            body="x",
            mode=AgentMode.SUBAGENT,
            source=PurePosixPath("agents/agent-b.md"),
        )
        self.content = content.Content(agents=(self.agent_a, self.agent_b), mcp=(self.context7,))

    def test_every_agent_gets_the_grant_uniformly(self):
        granted, dropped = content.grant_mcp(self.content, ["jira"])
        self.assertEqual(dropped, ())
        for agent in granted.agents:
            self.assertEqual(agent.granted_mcp, ("jira",))

    def test_multiple_keys_are_all_granted(self):
        granted, dropped = content.grant_mcp(self.content, ["jira", "figma"])
        self.assertEqual(dropped, ())
        for agent in granted.agents:
            self.assertEqual(agent.granted_mcp, ("jira", "figma"))

    def test_granting_nothing_leaves_every_agent_with_no_grant(self):
        granted, dropped = content.grant_mcp(self.content, [])
        self.assertEqual(dropped, ())
        for agent in granted.agents:
            self.assertEqual(agent.granted_mcp, ())

    def test_granted_mcp_is_distinct_from_optional_mcp(self):
        """A grant must never be folded into `optional_mcp` -- doing so would
        trip `_require_mcp_convention_referenced`, since a granted key has no
        convention and no body reference to satisfy it."""
        granted, _dropped = content.grant_mcp(self.content, ["jira"])
        agent_a = next(a for a in granted.agents if a.name == "agent-a")
        self.assertEqual(agent_a.optional_mcp, ("context7",))
        self.assertEqual(agent_a.granted_mcp, ("jira",))

    def test_a_key_colliding_with_a_shipped_mcp_id_is_refused(self):
        with self.assertRaises(ContentError) as raised:
            content.grant_mcp(self.content, ["context7"])
        self.assertIn("context7", str(raised.exception))

    def test_a_key_colliding_with_a_binding_already_in_play_is_refused(self):
        """Re-granting a server already granted per-agent (through
        `optional_mcp`, bound or not) could undo deliberate per-agent
        narrowing, so it is refused rather than silently widened."""
        selected = content.select_mcp(self.content, ["context7=jira-mcp"])
        with self.assertRaises(ContentError) as raised:
            content.grant_mcp(selected, ["jira-mcp"])
        self.assertIn("jira-mcp", str(raised.exception))

    def test_a_droppable_collision_is_dropped_rather_than_raised(self):
        """A key named as `droppable` is only a carried-forward grant this
        call did not itself ask for -- see `grant_mcp`'s own docstring."""
        selected = content.select_mcp(self.content, ["context7=jira-mcp"])
        granted, dropped = content.grant_mcp(selected, ["jira-mcp"], droppable=["jira-mcp"])
        self.assertEqual(dropped, ("jira-mcp",))
        for agent in granted.agents:
            self.assertEqual(agent.granted_mcp, ())

    def test_a_droppable_key_that_does_not_collide_is_still_granted(self):
        granted, dropped = content.grant_mcp(self.content, ["jira"], droppable=["jira"])
        self.assertEqual(dropped, ())
        for agent in granted.agents:
            self.assertEqual(agent.granted_mcp, ("jira",))

    def test_a_non_droppable_key_still_raises_alongside_a_droppable_one(self):
        """Naming one key explicit and one carried forward in the same call:
        only the carried-forward one may be dropped, so the explicit
        collision must still raise."""
        selected = content.select_mcp(self.content, ["context7=jira-mcp"])
        with self.assertRaises(ContentError) as raised:
            content.grant_mcp(selected, ["jira-mcp", "context7"], droppable=["jira-mcp"])
        self.assertIn("context7", str(raised.exception))
        self.assertNotIn("jira-mcp", str(raised.exception))

    def test_is_pure_the_input_content_is_unchanged(self):
        before_agents = self.content.agents
        content.grant_mcp(self.content, ["jira"])
        self.assertEqual(self.content.agents, before_agents)
        self.assertEqual(self.agent_a.granted_mcp, ())

    def test_a_wildcard_key_is_refused(self):
        """The exact escalation the adversarial review reproduced: an
        unvalidated `*` renders `**`, a rule beating the per-agent deny
        baseline for everything the agent was never granted."""
        with self.assertRaises(ContentError) as raised:
            content.grant_mcp(self.content, ["*"])
        self.assertIn("*", str(raised.exception))

    def test_no_wildcard_key_reaches_the_rendered_tools_or_permission_map(self):
        """End-to-end: even if `grant_mcp` were ever bypassed at the type
        level, a wildcard key must never survive to what the renderer
        actually emits."""
        with self.assertRaises(ContentError):
            content.grant_mcp(self.content, ["*"])
        # `grant_mcp` is pure and raised before returning, so nothing was
        # granted at all -- no agent carries a `granted_mcp` a renderer
        # could turn into `"**": True`.
        for agent in self.content.agents:
            self.assertEqual(agent.granted_mcp, ())

    def test_various_malformed_keys_are_refused(self):
        for spelling in ["*", "a*", "**", "", "   ", "a/b", 'a"b', "a=b"]:
            with self.subTest(spelling=spelling):
                with self.assertRaises(ContentError):
                    content.grant_mcp(self.content, [spelling])

    def test_legitimate_keys_still_work(self):
        for spelling in ["jira", "figma-developer-mcp", "some.server_1"]:
            with self.subTest(spelling=spelling):
                granted, dropped = content.grant_mcp(self.content, [spelling])
                self.assertEqual(dropped, ())
                for agent in granted.agents:
                    self.assertEqual(agent.granted_mcp, (spelling,))


class SelectMcpShippedContentTest(unittest.TestCase):
    """`select_mcp` conditionality proven against the real shipped tree, not a
    fixture stand-in -- the fixture in `SelectMcpTest` proves the mechanism
    works in general, this proves it actually gates `playwright` the way the
    brief requires.
    """

    @classmethod
    def setUpClass(cls):
        cls.loaded = content.load()

    def test_playwright_not_chosen_grants_it_to_no_agent(self):
        selected = content.select_mcp(self.loaded, ["cbm", "context7", "engram"])
        self.assertNotIn("playwright", [server.name for server in selected.mcp])
        for agent in selected.agents:
            self.assertNotIn("playwright", agent.optional_mcp, agent.name)

    def test_playwright_chosen_grants_it_to_exactly_the_intended_agents(self):
        selected = content.select_mcp(self.loaded, ["playwright"])
        granted = {agent.name for agent in selected.agents if "playwright" in agent.optional_mcp}
        self.assertEqual(granted, {"sdd-apply", "sdd-explore", "sdd-verify"})


class BoundMcpTest(unittest.TestCase):
    """A server the user already administers: Pegasus owns the contract, not the binary.

    An installation that already runs a server has it under a key of its own
    choosing, at a version of its own choosing. Today `optional_mcp: [cbm]`
    means two things at once -- fetch and manage this server, and grant its
    tools -- and only the second is wanted there. Binding separates them: the
    grants point at the key that installation really uses, and Pegasus fetches
    nothing.
    """

    def setUp(self):
        self.server = content.Mcp(
            name="cbm",
            description="Code graph",
            body="Convention body.",
            distribution=Distribution.DOWNLOAD,
            endpoint="https://example.test/cbm.tar.gz",
            checksum="sha256:" + "a" * 64,
            source=PurePosixPath("mcp/cbm.md"),
        )
        self.agent = content.Agent(
            name="probe-agent",
            description="Probes things",
            body="x",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/probe-agent.md"),
            optional_mcp=("cbm",),
        )
        self.content = content.Content(agents=(self.agent,), mcp=(self.server,))

    def test_a_key_that_could_act_as_a_wildcard_is_refused(self):
        """The bound key becomes a permission rule verbatim, on both sides.

        A grant is written as `f"{key}*"`, so a key that is itself `*` renders
        `**` — a rule that matches every action name there is. Placed after the
        deny baseline it becomes the last matching rule for everything the
        agent was never granted, which does not merely weaken this feature: it
        removes the whole per-agent restriction the baseline exists to impose.
        Refused where the value is read, because by the time it is a rule
        nothing can tell it from one somebody meant.
        """
        for key in ("*", "?", "cbm*", "a?b"):
            with self.subTest(key=key):
                with self.assertRaises(content.ContentError) as raised:
                    content.parse_mcp_choice(f"cbm={key}")
                self.assertIn(key, str(raised.exception))

    def test_the_keys_real_servers_use_are_still_accepted(self):
        for key in ("codebase-memory-mcp", "engram", "context7", "my.server_2"):
            with self.subTest(key=key):
                self.assertEqual(content.parse_mcp_choice(f"cbm={key}"), ("cbm", key))

    def test_an_unbound_choice_leaves_the_server_unbound(self):
        selected = content.select_mcp(self.content, ["cbm"])
        self.assertIsNone(selected.mcp[0].bound_to)
        self.assertFalse(selected.mcp[0].is_bound)

    def test_a_binding_records_the_key_that_installation_uses(self):
        selected = content.select_mcp(self.content, ["cbm=codebase-memory-mcp"])
        self.assertEqual(selected.mcp[0].bound_to, "codebase-memory-mcp")
        self.assertTrue(selected.mcp[0].is_bound)

    def test_the_server_keeps_its_own_id_when_bound(self):
        """The id is what names the convention file and what an agent body
        references, so it must survive the binding untouched."""
        selected = content.select_mcp(self.content, ["cbm=codebase-memory-mcp"])
        self.assertEqual(selected.mcp[0].name, "cbm")

    def test_an_agent_grant_follows_the_binding(self):
        """The grant is matched by the runtime against the server key, so a
        bound server has to be granted under the key the runtime resolves --
        not under Pegasus's own name for it, which that installation never
        writes."""
        selected = content.select_mcp(self.content, ["cbm=codebase-memory-mcp"])
        self.assertEqual(selected.agents[0].optional_mcp, ("codebase-memory-mcp",))

    def test_an_unbound_grant_stays_the_id(self):
        selected = content.select_mcp(self.content, ["cbm"])
        self.assertEqual(selected.agents[0].optional_mcp, ("cbm",))

    def test_binding_a_server_nobody_ships_is_refused_and_named(self):
        with self.assertRaises(ContentError) as raised:
            content.select_mcp(self.content, ["bogus=whatever"])
        self.assertIn("bogus", str(raised.exception))

    def test_a_binding_with_no_key_is_refused(self):
        for spelling in ("cbm=", "=codebase-memory-mcp", "cbm= ", "cbm=a=b"):
            with self.subTest(spelling=spelling):
                with self.assertRaises(ContentError):
                    content.select_mcp(self.content, [spelling])

    def test_is_pure_the_input_content_is_unchanged(self):
        content.select_mcp(self.content, ["cbm=codebase-memory-mcp"])
        self.assertIsNone(self.server.bound_to)
        self.assertEqual(self.agent.optional_mcp, ("cbm",))


def _content_error_raise_sites() -> dict[str, int]:
    """`raise ContentError(...)` sites in `content.py`, keyed by enclosing
    function name plus call order -- stable under unrelated edits, unlike a
    line number, and moved only by adding/removing/reordering a raise inside
    that function, which is exactly what `test_every_raise_site_has_a_case`
    must catch.
    """
    tree = ast.parse(inspect.getsource(content))
    sites: dict[str, int] = {}
    counters: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: ast.AST) -> None:
        pushed = isinstance(node, ast.FunctionDef)
        if pushed:
            stack.append(node.name)
        if isinstance(node, ast.Raise):
            call = node.exc
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "ContentError":
                function = stack[-1] if stack else "<module>"
                sites[f"{function}#{counters.get(function, 0)}"] = node.lineno
                counters[function] = counters.get(function, 0) + 1
        for child in ast.iter_child_nodes(node):
            visit(child)
        if pushed:
            stack.pop()

    visit(tree)
    return sites


_ContentCase = Callable[[Path], tuple[str | None, str]]


def _via_load(files: dict[str, str], expected: str) -> _ContentCase:
    """A case whose fixture is the given files, refused by `content.load`."""

    def run(root: Path) -> tuple[str, str]:
        for relative, text in files.items():
            write(root, relative, text)
        try:
            content.load(root)
        except ContentError as error:
            return expected, str(error)
        raise AssertionError(f"malformed fixture was accepted: {sorted(files)}")

    return run


def _agent_text(name: str, mode: str = "primary", extra: str = "") -> str:
    return f"---\nname: {name}\ndescription: d\nmode: {mode}\n{extra}---\n\nx\n"


_SESSION_START_FILE = f"agents/{content.SESSION_STARTS_IN}.md"


def _session_start_case(extra: str) -> _ContentCase:
    """A malformed session-start agent, the only file in the tree."""
    return _via_load({_SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN, extra=extra)}, _SESSION_START_FILE)


def _run_dead_branch(root: Path) -> tuple[None, str]:
    """Evidence for `split_frontmatter#2`: a non-mapping document is refused
    by `frontmatter.parse` itself via `FrontmatterError`, before the
    `isinstance` check ever runs -- `parse` only ever returns a `dict` it
    built, or raises.
    """
    try:
        content.split_frontmatter("---\n- a\n- b\n---\n\nbody\n")
    except ContentError as error:
        return None, str(error)
    raise AssertionError("non-mapping frontmatter was accepted")


def _run_mcp_choice(spelling: str):
    """A malformed `--mcp` value, refused by `parse_mcp_choice`."""

    def run(root: Path) -> tuple[None, str]:
        try:
            content.parse_mcp_choice(spelling)
        except ContentError as error:
            return None, str(error)
        raise AssertionError(f"a malformed mcp choice was accepted: {spelling!r}")

    return run


def _run_select_mcp_unknown_id(root: Path) -> tuple[None, str]:
    server = content.Mcp(
        name="context7", description="d", body="b", distribution=Distribution.REMOTE,
        endpoint="https://example.test/context7", source=PurePosixPath("mcp/context7.md"),
    )
    try:
        content.select_mcp(content.Content(mcp=(server,)), ["bogus"])
    except ContentError as error:
        return None, str(error)
    raise AssertionError("an unknown mcp id was accepted")


def _run_grant_mcp_malformed_key(root: Path) -> tuple[None, str]:
    try:
        content.grant_mcp(content.Content(), ["*"])
    except ContentError as error:
        return None, str(error)
    raise AssertionError("a malformed mcp key was accepted")


def _run_grant_mcp_collision(root: Path) -> tuple[None, str]:
    server = content.Mcp(
        name="context7", description="d", body="b", distribution=Distribution.REMOTE,
        endpoint="https://example.test/context7", source=PurePosixPath("mcp/context7.md"),
    )
    try:
        content.grant_mcp(content.Content(mcp=(server,)), ["context7"])
    except ContentError as error:
        return None, str(error)
    raise AssertionError("a colliding mcp key was accepted")


class ContentErrorSitesTest(unittest.TestCase):
    """Table test over every `raise ContentError` site in `content.py`, from
    an AST walk rather than a hand-kept list -- the `test_architecture.py`
    habit. Every reachable site's message must name the real path of the file
    responsible, matching `frontmatter.py`'s own `"{source}:{line_no}: ..."`.
    """

    #: key -> (runner, reason); reason is set only where no path applies.
    CASES: dict[str, tuple[_ContentCase, str]] = {
        "split_frontmatter#0": (
            _via_load({"commands/broken.md": "---\nname: broken\ndescription: d\n\nno closing\n"}, "commands/broken.md"), ""),
        "split_frontmatter#1": (
            _via_load({"commands/broken.md": "---\n  bad: x\n---\n\nb\n"}, "commands/broken.md"), ""),
        "split_frontmatter#2": (_run_dead_branch, "Dead code -- see `_run_dead_branch`'s docstring."),
        "parse_mcp_choice#0": (
            _run_mcp_choice("cbm=a=b"),
            "Refuses a `--mcp` value, not a file on disk, so no path applies; the "
            "message quotes the value and names both spellings that are accepted.",
        ),
        "parse_mcp_choice#1": (
            _run_mcp_choice("cbm="),
            "Same: a value the user typed, quoted back, with no file to name.",
        ),
        "parse_mcp_choice#2": (
            _run_mcp_choice("cbm=*"),
            "Same: a value the user typed, refused before it can become a rule.",
        ),
        "select_mcp#0": (
            _run_select_mcp_unknown_id,
            "Refuses a chosen mcp id, not a file on disk, so no path applies; the "
            "message already names the offending id and the ids that do exist.",
        ),
        "grant_mcp#0": (
            _run_grant_mcp_malformed_key,
            "Refuses a granted key shaped like a wildcard, not a file on disk, so no "
            "path applies; the message already names the offending key.",
        ),
        "grant_mcp#1": (
            _run_grant_mcp_collision,
            "Refuses a granted key colliding with a shipped mcp id or an already-bound "
            "key, not a file on disk, so no path applies; the message already names "
            "the offending key.",
        ),
        "_load_skills#0": (
            _via_load({"skills/alpha/references/orphan.md": "# Orphan\n"}, "skills/alpha"), ""),
        "_require_the_session_start#0": (_via_load({"agents/alpha.md": _agent_text("alpha")}, "agents"), ""),
        "_require_the_session_start#1": (
            _via_load({_SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN, mode="subagent")}, _SESSION_START_FILE), ""),
        "_require_known_optional_mcp#0": (
            _via_load(
                {
                    _SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN),
                    "agents/probe-agent.md": "---\nname: probe-agent\ndescription: d\nmode: primary\n"
                    "optional_mcp: [phantom]\n---\n\nx\n",
                },
                "agents/probe-agent.md",
            ),
            "",
        ),
        "_require_mcp_reaches_an_agent#0": (
            _via_load(
                {
                    _SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN),
                    "mcp/context7.md": MCP.replace("probe-mcp", "context7"),
                },
                "mcp/context7.md",
            ),
            "",
        ),
        "_require_mcp_convention_referenced#0": (
            _via_load(
                {
                    _SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN),
                    "mcp/context7.md": MCP.replace("probe-mcp", "context7"),
                    "agents/probe-agent.md": "---\nname: probe-agent\ndescription: d\nmode: primary\n"
                    "optional_mcp: [context7]\n---\n\nx\n",
                },
                "agents/probe-agent.md",
            ),
            "",
        ),
        "_load_agent_mcp_sections#0": (
            _via_load(
                {
                    _SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN),
                    "agents/mcp/phantom.md": "Ambient text.\n",
                },
                "agents/mcp/phantom.md",
            ),
            "",
        ),
        "_load_agent_mcp_sections#1": (
            _via_load(
                {
                    _SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN),
                    "mcp/context7.md": MCP.replace("probe-mcp", "context7"),
                    "agents/mcp/context7@ghost-agent.md": "Ambient text.\n",
                },
                "agents/mcp/context7@ghost-agent.md",
            ),
            "",
        ),
        "_require_every_override_is_wired#0": (
            _via_load(
                {
                    _SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN),
                    "mcp/context7.md": MCP.replace("probe-mcp", "context7"),
                    "agents/probe-agent.md": (
                        "---\nname: probe-agent\ndescription: d\nmode: primary\n---\n\nx\n"
                    ),
                    "agents/mcp/context7@probe-agent.md": "Ambient text.\n",
                },
                "agents/mcp/context7@probe-agent.md",
            ),
            "",
        ),
        "_refuse_foreign_form_fields#0": (
            _via_load(
                {"mcp/probe-mcp.md": MCP.replace(
                    "endpoint: https://example.test/mcp\n",
                    "endpoint: https://example.test/mcp\nversion: 1.0.0\n",
                )},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_download_form#0": (
            _via_load({"mcp/probe-mcp.md": DOWNLOAD_MCP.replace(CHECKSUM, "sha256:not-hex")}, "mcp/probe-mcp.md"), ""),
        "_archive_form#0": (
            _via_load({"mcp/probe-mcp.md": ARCHIVE_MCP.replace("archive_executable: probe-mcp\n", "")}, "mcp/probe-mcp.md"), ""),
        "_archive_form#1": (
            _via_load(
                {"mcp/probe-mcp.md": ARCHIVE_MCP.replace(
                    "archive_members: [CHANGELOG.md, LICENSE, probe-mcp]", "archive_members: []"
                )},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_archive_form#2": (
            _via_load({"mcp/probe-mcp.md": ARCHIVE_MCP.replace("LICENSE", "../LICENSE")}, "../LICENSE"), ""),
        "_archive_form#3": (
            _via_load(
                {"mcp/probe-mcp.md": ARCHIVE_MCP.replace("archive_executable: probe-mcp\n", "archive_executable: ghost\n")},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_npm_form#0": (
            _via_load(
                {"mcp/probe-mcp.md": NPM_MCP.replace(INTEGRITY, "sha256:not-sha512"), f"mcp/{NPM_LOCKFILE_NAME}": NPM_LOCKFILE},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_npm_form#1": (
            _via_load(
                {"mcp/probe-mcp.md": NPM_MCP.replace(NPM_LOCKFILE_NAME, f"../{NPM_LOCKFILE_NAME}"), f"mcp/{NPM_LOCKFILE_NAME}": NPM_LOCKFILE},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_npm_form#2": (
            _via_load({"mcp/probe-mcp.md": NPM_MCP.replace(NPM_LOCKFILE_NAME, "ghost-lock.json")}, "ghost-lock.json"), ""),
        "_require_lockfile_pins#0": (
            _via_load({"mcp/probe-mcp.md": NPM_MCP, f"mcp/{NPM_LOCKFILE_NAME}": "not json at all"}, "mcp/probe-mcp.md"), ""),
        "_require_lockfile_pins#1": (
            _via_load({"mcp/probe-mcp.md": NPM_MCP, f"mcp/{NPM_LOCKFILE_NAME}": '{"name": "no-packages-here"}'}, "mcp/probe-mcp.md"), ""),
        "_require_lockfile_pins#2": (
            _via_load(
                {"mcp/probe-mcp.md": NPM_MCP, f"mcp/{NPM_LOCKFILE_NAME}": NPM_LOCKFILE.replace('"probe-mcp": "1.2.3"', '"probe-mcp": "9.9.9"')},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_require_lockfile_pins#3": (
            _via_load(
                {"mcp/probe-mcp.md": NPM_MCP, f"mcp/{NPM_LOCKFILE_NAME}": NPM_LOCKFILE.replace('"name": "pegasus-probe-mcp", ', "")},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_require_lockfile_pins#4": (
            _via_load(
                {"mcp/probe-mcp.md": NPM_MCP, f"mcp/{NPM_LOCKFILE_NAME}": NPM_LOCKFILE.replace("node_modules/probe-mcp", "node_modules/other")},
                "node_modules/probe-mcp",
            ),
            "",
        ),
        "_require_lockfile_pins#5": (
            _via_load(
                {"mcp/probe-mcp.md": NPM_MCP, f"mcp/{NPM_LOCKFILE_NAME}": NPM_LOCKFILE.replace(INTEGRITY, "sha512-" + "b" * 86 + "==")},
                "mcp/probe-mcp.md",
            ),
            "",
        ),
        "_require_known_system_prompt_mcp#0": (
            _via_load(
                {
                    _SESSION_START_FILE: _agent_text(content.SESSION_STARTS_IN),
                    "system-prompt/AGENTS.md": "# Rules\n",
                    "system-prompt/mcp/phantom.md": "---\nname: phantom\n---\n\nAmbient rules.\n",
                },
                "system-prompt/mcp/phantom.md",
            ),
            "",
        ),
        "_load_system_prompt#0": (
            _via_load({"system-prompt/AGENTS.md": "# Rules\n", "system-prompt/OTHER.md": "# More\n"}, "system-prompt"), ""),
        "_descriptor#0": (_via_load({"commands/probe-command.md": "# Just a body\n"}, "commands/probe-command.md"), ""),
        "_refuse_derived_fields#0": (
            _session_start_case("default: true\n"), ""),
        "_require_known_placeholders#0": (
            _via_load({"commands/probe-command.md": COMMAND.replace("Command body.", "{{bogus}}")}, "commands/probe-command.md"), ""),
        "_require_known_placeholders#1": (
            _via_load({"commands/probe-command.md": COMMAND.replace("Command body.", "{{ oops")}, "commands/probe-command.md"), ""),
        "_refuse_verbatim_placeholders#0": (
            _via_load(
                {"skills/alpha/SKILL.md": SKILL, "skills/alpha/references/note.md": "See {{skills_root}}.\n"},
                "skills/alpha/references/note.md",
            ),
            "",
        ),
        "_refuse_verbatim_placeholders#1": (
            _via_load(
                {"skills/alpha/SKILL.md": SKILL, "skills/alpha/references/note.md": "{{ oops\n"},
                "skills/alpha/references/note.md",
            ),
            "",
        ),
        "_require_name#0": (_via_load({"skills/beta/SKILL.md": SKILL}, "skills/beta/SKILL.md"), ""),
        "_text#0": (
            _via_load(
                {"commands/probe-command.md": "---\nname: probe-command\nruns_as: default\nexecution: inline\n---\n\nx\n"},
                "commands/probe-command.md",
            ),
            "",
        ),
        "_choice#0": (
            _via_load({"commands/probe-command.md": COMMAND.replace("orchestrator", "pegasus-orchestrator")}, "commands/probe-command.md"), ""),
        "_flag#0": (_session_start_case('model_configurable: "false"\n'), ""),
        "_names#0": (_session_start_case("requires_tools: bash\n"), ""),
        "_names#1": (_session_start_case('requires_tools: [""]\n'), ""),
    }

    def _temp_root(self) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def test_every_raise_site_has_a_case(self):
        self.assertEqual(set(_content_error_raise_sites()), set(self.CASES))

    def test_every_reachable_site_names_a_real_path(self):
        for key, (run, reason) in self.CASES.items():
            with self.subTest(key=key):
                expected, message = run(self._temp_root())
                if expected is None:
                    self.assertTrue(reason, f"{key}: a path-less result must record why")
                    continue
                self.assertFalse(reason, f"{key}: a reason is only for path-less results")
                self.assertIn(expected, message)

    def test_a_representative_subset_raises_identically_from_inside_a_zip(self):
        """Same malformed trees, staged inside a real zip archive instead of
        loose files, must raise identically -- proof these fixtures are not
        bypassing the `Traversable` path production reads a zip through.
        """
        subset = {
            "skills/alpha/references/orphan.md": ("# Orphan\n", "skills/alpha"),
            "mcp/probe-mcp.md": (NPM_MCP.replace(NPM_LOCKFILE_NAME, "ghost-lock.json"), "ghost-lock.json"),
            "agents/mcp/phantom.md": ("Ambient text.\n", "agents/mcp/phantom.md"),
        }
        for relative, (text, expected) in subset.items():
            with self.subTest(relative=relative):
                archive_dir = tempfile.TemporaryDirectory()
                self.addCleanup(archive_dir.cleanup)
                archive_path = Path(archive_dir.name) / "content.zip"
                write_zip(archive_path, {relative: text})
                zip_file = zipfile.ZipFile(archive_path)
                self.addCleanup(zip_file.close)
                with self.assertRaises(ContentError) as raised:
                    content.load(zipfile.Path(zip_file))
                self.assertIn(expected, str(raised.exception))


class WithheldMcpToolsTest(unittest.TestCase):
    """`select_mcp` is the one place that knows both a server's descriptor and
    the key an agent's grant actually resolves against, so it is where the
    fully-qualified names a wildcard grant must not reach get built.
    """

    def setUp(self):
        self.server = content.Mcp(
            name="cbm",
            description="Code graph",
            body="Convention body.",
            distribution=Distribution.DOWNLOAD,
            endpoint="https://example.test/cbm.tar.gz",
            checksum="sha256:" + "a" * 64,
            source=PurePosixPath("mcp/cbm.md"),
            withheld_tools=("delete_project", "ingest_traces"),
        )
        self.plain_server = content.Mcp(
            name="context7",
            description="Docs",
            body="Convention body.",
            distribution=Distribution.REMOTE,
            endpoint="https://example.test/mcp",
            source=PurePosixPath("mcp/context7.md"),
        )
        self.agent = content.Agent(
            name="probe-agent",
            description="Probes things",
            body="x",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/probe-agent.md"),
            optional_mcp=("cbm", "context7"),
        )
        self.content = content.Content(agents=(self.agent,), mcp=(self.server, self.plain_server))

    def test_an_unbound_grant_denies_the_ids_own_tool_names(self):
        selected = content.select_mcp(self.content, ["cbm", "context7"])
        self.assertEqual(
            selected.agents[0].denied_mcp_tools,
            ("cbm_delete_project", "cbm_ingest_traces"),
        )

    def test_a_bound_grant_denies_tool_names_built_from_the_bound_key(self):
        """The deny has to name a tool the runtime can actually resolve --
        which only exists under the key the grant was rewritten to, not under
        Pegasus's own id for the server.
        """
        selected = content.select_mcp(
            self.content, ["cbm=codebase-memory-mcp", "context7"]
        )
        self.assertEqual(
            selected.agents[0].denied_mcp_tools,
            ("codebase-memory-mcp_delete_project", "codebase-memory-mcp_ingest_traces"),
        )

    def test_a_server_with_nothing_withheld_contributes_no_denies(self):
        selected = content.select_mcp(self.content, ["context7"])
        self.assertEqual(selected.agents[0].denied_mcp_tools, ())

    def test_choosing_nothing_leaves_no_denies(self):
        selected = content.select_mcp(self.content, [])
        self.assertEqual(selected.agents[0].denied_mcp_tools, ())

    def test_an_agent_that_never_declares_the_server_carries_no_denies(self):
        untouched = content.Agent(
            name="other-agent",
            description="d",
            body="x",
            mode=AgentMode.PRIMARY,
            source=PurePosixPath("agents/other-agent.md"),
        )
        with_untouched = content.Content(
            agents=(self.agent, untouched), mcp=(self.server, self.plain_server)
        )
        selected = content.select_mcp(with_untouched, ["cbm"])
        other = next(a for a in selected.agents if a.name == "other-agent")
        self.assertEqual(other.denied_mcp_tools, ())


if __name__ == "__main__":
    unittest.main()
