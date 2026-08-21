"""One file names the CBM tools; everyone else points at it.

Codebase Memory (`codebase-memory-mcp`) protocol prose used to be restated in
every phase that touches it -- the same tool priority order and index-repair
rule, paraphrased six or seven times, with two of those paraphrases landing on
opposite advice for a stale or missing index. `_shared/cbm-convention.md` is
the single place that names CBM tools and states the rule; every other file
that used to restate it now points there instead.

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
SHARED_CBM = SKILLS / "_shared" / "cbm-convention.md"

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
        # The canonical convention itself -- the one place the tools are named.
        "skills/_shared/cbm-convention.md",
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


class SharedFileExistsTest(unittest.TestCase):
    def test_the_shared_convention_file_exists(self):
        self.assertTrue(SHARED_CBM.is_file(), f"missing: {SHARED_CBM}")

    def test_the_shared_convention_ships_as_a_skill_asset(self):
        """Existing on disk is not enough -- the loader has to pick it up."""
        loaded = content_module.load()
        shared = next((skill for skill in loaded.skills if skill.name == "_shared"), None)
        self.assertIsNotNone(shared, "_shared is not among the loaded skills")
        names = [str(asset.relative_path) for asset in shared.assets]
        self.assertIn("cbm-convention.md", names)


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

    #: Agents documented to use CBM, and therefore expected to point at the
    #: shared convention rather than restate it.
    CBM_AGENTS = (
        "pegasus-orchestrator.md",
        "sdd-explore.md",
        "sdd-design.md",
        "sdd-apply.md",
        "sdd-verify.md",
        "king-pegasus.md",
    )

    def test_every_placeholder_reference_resolves_from_the_skills_root(self):
        offenders = []
        for path in sorted(AGENTS.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            for match in self.REFERENCE.finditer(text):
                if not (SKILLS / match.group(1)).is_file():
                    offenders.append(f"{path.name} -> {match.group(1)}")
        self.assertEqual(offenders, [])

    def test_every_cbm_agent_points_at_the_shared_convention(self):
        missing = [
            name
            for name in self.CBM_AGENTS
            if "{{skills_root}}/_shared/cbm-convention.md" not in (AGENTS / name).read_text(
                encoding="utf-8"
            )
        ]
        self.assertEqual(missing, [], f"agents missing the CBM pointer: {missing}")


class SkillPointerTest(unittest.TestCase):
    """The skill-side counterpart: `_shared/cbm-convention.md`, no placeholder."""

    CBM_SKILLS = (
        "sdd-explore/SKILL.md",
        "sdd-design/SKILL.md",
        "sdd-apply/SKILL.md",
        "sdd-verify/SKILL.md",
    )

    def test_every_cbm_skill_points_at_the_shared_convention(self):
        missing = [
            name
            for name in self.CBM_SKILLS
            if "_shared/cbm-convention.md" not in (SKILLS / name).read_text(encoding="utf-8")
        ]
        self.assertEqual(missing, [], f"skills missing the CBM pointer: {missing}")


class KingPegasusToolsTest(unittest.TestCase):
    """king-pegasus joins the CBM users: structural reading only, never write/edit/bash."""

    @classmethod
    def setUpClass(cls):
        cls.agent = next(
            agent for agent in content_module.load().agents if agent.name == "king-pegasus"
        )

    def test_gains_codebase_memory(self):
        # Optional, not required: the tool comes from an MCP the user may not
        # select, and a requirement no installation can satisfy is not one.
        # The body already reads that way — it says what to do when CBM is absent.
        # Exact, not a subset check: `render._tools` grants requires_tools ∪
        # optional_tools identically, so a loose containment check would miss an
        # extra tool sneaking into optional_tools and being granted alongside it.
        self.assertEqual(set(self.agent.optional_tools), {"codebase-memory"})
        self.assertNotIn("codebase-memory", self.agent.requires_tools)

    def test_gains_nothing_else(self):
        for forbidden in ("write", "edit", "bash"):
            self.assertNotIn(forbidden, self.agent.requires_tools)
            self.assertNotIn(forbidden, self.agent.optional_tools)


if __name__ == "__main__":
    unittest.main()
