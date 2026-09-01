"""One file names the CBM tools; everyone else points at it.

Codebase Memory (`codebase-memory-mcp`) protocol prose used to be restated in
every phase that touches it -- the same tool priority order and index-repair
rule, paraphrased six or seven times, with two of those paraphrases landing on
opposite advice for a stale or missing index. `_shared/cbm-convention.md`
used to be the single hand-authored place that named CBM tools and stated the
rule, shipped to every install regardless of whether anyone chose CBM. Naming
`cbm` as a real MCP server moved that same prose into the server's own
descriptor body (`mcp/cbm.md`): the canonical place is now the descriptor, and
it travels only when `cbm` is selected, the same move `engram` went through
when it stopped being an unconditional part of the system prompt.

This file cannot check that the paraphrases said the same thing -- that is a
judgment about English, and this repository's tests never make one. What it
can check is the one fact that is not a matter of wording: which files name a
CBM tool identifier at all. `index_repository` cannot be paraphrased the way a
sentence can, so a file that calls the tools out by name is a file that still
carries the protocol inline, allowlist entries aside.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from pegasus.core import content as content_module

CONTENT = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content"
SKILLS = CONTENT / "skills"
AGENTS = CONTENT / "agents"
MCP = CONTENT / "mcp"
CBM_DESCRIPTOR = MCP / "cbm.md"
OLD_SHARED_CBM = SKILLS / "_shared" / "cbm-convention.md"

#: The MCP tool identifiers that make up the CBM protocol. Naming any of these
#: is naming the protocol, however the surrounding sentence is worded.
CBM_TOOL_IDENTIFIERS = (
    "search_graph",
    "trace_path",
    "get_code_snippet",
    "query_graph",
    "get_architecture",
    "search_code",
    "index_status",
    "index_repository",
    "detect_changes",
    "list_projects",
)

IDENTIFIER_PATTERN = re.compile(r"\b(?:%s)\b" % "|".join(CBM_TOOL_IDENTIFIERS))

#: Every file allowed to name a CBM tool identifier, and why. Anything else
#: that names one still carries the protocol inline instead of pointing at it.
ALLOWED_IDENTIFIER_FILES = frozenset(
    {
        # The canonical convention itself -- the one place the tools are named,
        # now the server's own descriptor body instead of a hand-authored file
        # shipped unconditionally.
        "mcp/cbm.md",
        # The post-apply Index Coherence Gate: apply-exclusive trigger derivation,
        # moderate-to-full reindex escalation, and apply-progress reporting. It
        # consumes the generic convention, it does not restate it.
        "skills/sdd-apply/references/cbm-index-coherence.md",
    }
)


def all_markdown() -> list[Path]:
    return sorted(path for path in CONTENT.rglob("*.md") if "__pycache__" not in path.parts)


def relative(path: Path) -> str:
    return path.relative_to(CONTENT).as_posix()


class DescriptorExistsTest(unittest.TestCase):
    """The convention now lives in the server's own descriptor, not a shared asset."""

    def test_the_cbm_descriptor_exists(self):
        self.assertTrue(CBM_DESCRIPTOR.is_file(), f"missing: {CBM_DESCRIPTOR}")

    def test_the_old_unconditional_shared_file_is_gone(self):
        """It shipped to every install before `cbm` had a descriptor of its own.

        Leaving it behind would mean the convention ships twice: once always,
        once only when `cbm` is selected.
        """
        self.assertFalse(OLD_SHARED_CBM.is_file(), f"still present: {OLD_SHARED_CBM}")

    def test_cbm_loads_as_a_real_mcp_server_with_a_convention_body(self):
        server = next(
            (server for server in content_module.load().mcp if server.name == "cbm"), None
        )
        self.assertIsNotNone(server, "cbm is not among the loaded mcp servers")
        self.assertTrue(server.body.strip())


class IdentifierAllowlistTest(unittest.TestCase):
    """Only the canonical file and its named exception may call CBM tools by name."""

    def test_no_file_outside_the_allowlist_names_a_cbm_tool(self):
        offenders = []
        for path in all_markdown():
            text = path.read_text(encoding="utf-8")
            hit = IDENTIFIER_PATTERN.search(text)
            if hit and relative(path) not in ALLOWED_IDENTIFIER_FILES:
                offenders.append(f"{relative(path)} names {hit.group(0)!r}")
        self.assertEqual(offenders, [], "\n".join(offenders))

    def test_the_allowlist_itself_still_names_a_tool(self):
        """A canary against the allowlist going stale after the files it names change."""
        for entry in ALLOWED_IDENTIFIER_FILES:
            text = (CONTENT / entry).read_text(encoding="utf-8")
            self.assertRegex(text, IDENTIFIER_PATTERN, entry)

    def test_the_allowlist_is_short(self):
        """The point of centralizing is that almost nothing still names a tool."""
        self.assertLessEqual(len(ALLOWED_IDENTIFIER_FILES), 2)


class AgentPointerResolutionTest(unittest.TestCase):
    """An agent file's `{{skills_root}}/...` reference has to resolve for real.

    `test_skill_references.py` covers this class of check for files inside the
    skills tree. Agent prompts live outside it and use the placeholder form
    instead, so their references need their own resolution check.
    """

    REFERENCE = re.compile(r"\{\{skills_root\}\}/([\w./-]+\.md)")

    #: Agents that declare `optional_mcp: [cbm, ...]`, and therefore point at
    #: the server's own rendered convention rather than restate it.
    #:
    #: The two primaries were deliberately absent while their bodies said they
    #: declared no server. Both now do, for reasons their own bodies state: the
    #: orchestrator asks the graph the cheap question that decides where work
    #: goes, and the voice asks it because it does its own discovery instead of
    #: delegating it. What has not changed is the pairing --
    #: `_require_mcp_convention_referenced` in `content.py` requires the set an
    #: agent declares and the set its body references to match exactly, so an
    #: entry here without a declaration, or a declaration without the pointer,
    #: still fails at load.
    CBM_AGENTS = (
        "king-pegasus.md",
        "pegasus-orchestrator.md",
        "sdd-explore.md",
        "sdd-design.md",
        "sdd-apply.md",
        "sdd-verify.md",
    )

    def test_every_placeholder_reference_resolves_from_the_skills_root(self):
        """Every reference into the skills tree this repository ships is a real file.

        A server's convention is the one kind of reference that resolves to
        nothing here: it is not a shipped asset but a file rendered from the
        server's own descriptor body, so it exists only under the skills root of
        a real installation. The exclusion is derived from the shipped servers
        rather than listed, so a second server needs nobody to remember it, and
        those references are covered instead by the loader invariant that proves
        each one names a path the renderer will actually produce.
        """
        rendered_not_shipped = {
            str(content_module.mcp_convention_path(server.name))
            for server in content_module.load().mcp
        }
        offenders = []
        for path in sorted(AGENTS.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in self.REFERENCE.finditer(text):
                if match.group(1) in rendered_not_shipped:
                    continue
                if not (SKILLS / match.group(1)).is_file():
                    offenders.append(f"{path.name} -> {match.group(1)}")
        self.assertEqual(offenders, [])

    def test_every_cbm_agent_points_at_the_rendered_convention(self):
        missing = [
            name
            for name in self.CBM_AGENTS
            if "{{skills_root}}/_shared/mcp/cbm-convention.md" not in (AGENTS / name).read_text(
                encoding="utf-8"
            )
        ]
        self.assertEqual(missing, [], f"agents missing the CBM pointer: {missing}")

    def test_no_agent_still_names_the_old_unconditional_path(self):
        offenders = [
            path.name
            for path in sorted(AGENTS.glob("*.md"))
            if "_shared/cbm-convention.md" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


class SkillPointerTest(unittest.TestCase):
    """The skill-side counterpart: `_shared/mcp/cbm-convention.md`, no placeholder.

    A skill body ships verbatim, with no `{{skills_root}}` substitution, so it
    names the rendered path directly. That path only exists on disk once `cbm`
    is selected -- `test_skill_references.py` carries the same rendered-not-
    shipped exclusion the agent-side check above relies on.
    """

    CBM_SKILLS = (
        "sdd-explore/SKILL.md",
        "sdd-design/SKILL.md",
        "sdd-apply/SKILL.md",
        "sdd-verify/SKILL.md",
    )

    def test_every_cbm_skill_points_at_the_rendered_convention(self):
        missing = [
            name
            for name in self.CBM_SKILLS
            if "_shared/mcp/cbm-convention.md" not in (SKILLS / name).read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [], f"skills missing the CBM pointer: {missing}")


class KingPegasusToolsTest(unittest.TestCase):
    """king-pegasus reads the graph itself, because it is the one voice that
    does its own discovery instead of delegating it."""

    @classmethod
    def setUpClass(cls):
        cls.agent = next(
            agent for agent in content_module.load().agents if agent.name == "king-pegasus"
        )

    def test_declares_the_servers_whose_contract_is_ambient(self):
        # It used to declare none: applying a change was its own body's
        # decision, made through direct file and text search. That reasoning
        # held for delegation, not for discovery -- this voice acts rather than
        # delegates, so the discovery a phase agent would have done for it is
        # its own, and an explanation is only as good as the shape of the code
        # behind it. Memory it declares for the same reason every agent does.
        self.assertEqual(self.agent.optional_tools, ())
        self.assertEqual(set(self.agent.optional_mcp), {"cbm", "engram"})

    def test_gains_nothing_beyond_applying_a_file_change(self):
        # `write` and `edit` are what let this voice apply what it explains; `bash`
        # stays out, matching its own "never build after changes" rule.
        for granted in ("write", "edit"):
            self.assertIn(granted, self.agent.requires_tools)
        self.assertNotIn("bash", self.agent.requires_tools)
        self.assertNotIn("bash", self.agent.optional_tools)


if __name__ == "__main__":
    unittest.main()
