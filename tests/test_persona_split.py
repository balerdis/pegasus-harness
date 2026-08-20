"""The line between what binds every agent and what is one agent's voice.

The shipped instruction file that arrived from v3 carried both: universal rules
and protocols on one side, and the personality of a single agent on the other.
A rule like "never add tool attribution to a commit" has to bind the phase
macros too, and a phase macro must never inherit a speech style. So the file is
split, and this test guards the seam from both directions.

The baseline (`content/system-prompt/AGENTS.md`) must be self-contained and
runtime-neutral: no persona, no absolute path from anybody's machine, and no
pointer to a skill Pegasus does not ship -- a dangling pointer is worse than an
inline paragraph, because it fails in the middle of somebody's task instead of
here. The persona (`content/agents/king-pegasus.md`) must carry voice only.

Headings are read with fenced blocks removed on purpose. The session-summary
template is written with `##` lines, and it is a literal payload the agent hands
to a tool, not document structure. Fencing is what tells the two apart, and the
heading assertions below are what make the fencing load-bearing.

Every assertion here is structural: a heading, a marker, a frontmatter field, a
path. Nothing pins a sentence. Wording is the author's to change; the shape of
the two documents is what this file defends.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from pegasus.core import content as content_module

ROOT = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content"
BASELINE = ROOT / "system-prompt" / "AGENTS.md"
PERSONA = ROOT / "agents" / "king-pegasus.md"

HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")

#: Deliberately wider than the spellings Pegasus writes: a marker malformed with an
#: underscore or a capital still has to be seen, or it goes unbalanced in silence.
MARKER = re.compile(r"<!--\s*(/?)([A-Za-z0-9_:-]+)\s*-->")

#: Somebody else's disk. None of these belongs in a file that ships.
MACHINE_PATHS = ("/home/", ".config/opencode", "/Users/", "~/")

#: A skill directory named in prose, so a dangling pointer is caught here and not
#: in the middle of somebody's task.
SKILL_POINTER = re.compile(r"(?:^|[^\w./-])skills/([A-Za-z0-9_-]+)")

#: Required, unordered, matched case-insensitively by prefix. Adding a section is
#: allowed; losing one of these is not.
BASELINE_HEADINGS = (
    ("##", "Rules"),
    ("##", "Persona Scope"),
    ("##", "Language"),
    ("##", "Contextual Skill Loading"),
    ("##", "Engram Persistent Memory"),
    ("###", "DELIVERY GUARANTEE"),
    ("###", "SESSION CLOSE PROTOCOL"),
    ("###", "AFTER COMPACTION"),
)

#: The voice sections. `## Persona Scope` in the baseline promises a persona has
#: Language, Tone, Speech Patterns and Personality, so those four are load-bearing.
PERSONA_HEADINGS = (
    ("#", "King Pegasus"),
    ("##", "Rules"),
    ("##", "Personality"),
    ("##", "Language"),
    ("##", "Speech patterns"),
    ("##", "Tone"),
    ("##", "Philosophy"),
    ("##", "Expertise"),
    ("##", "Behavior"),
)

#: Sections the split moved out of the baseline for good.
PERSONA_OWNED = (
    "## Personality",
    "## Tone",
    "## Philosophy",
    "## Expertise",
    "## Behavior",
    "## Speech patterns",
)


def headings(text: str) -> list[str]:
    """Every heading the document really declares, fenced payloads excluded."""
    found = []
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = HEADING.match(line)
        if match:
            found.append(f"{match.group(1)} {match.group(2)}")
    return found


def declares(found: list[str], level: str, prefix: str) -> bool:
    """Is this section declared at this level, whatever the author suffixed to it?"""
    wanted = f"{level} {prefix}".casefold()
    return any(head.casefold().startswith(wanted) for head in found)


def shipped_skills() -> set[str]:
    return {path.name for path in (ROOT / "skills").iterdir() if path.is_dir()}


class SharedContentRules:
    """What holds for both shipped files. Mixed into each file's own test case."""

    path: Path
    text: str

    def test_no_machine_specific_path_survives(self):
        """It is installed on somebody else's disk; one home directory is not it."""
        for fragment in MACHINE_PATHS:
            self.assertNotIn(fragment, self.text, f"{self.path.name} names a local path: {fragment!r}")

    def test_no_pointer_to_a_skill_pegasus_does_not_ship(self):
        """A dangling pointer fails in the middle of a task instead of here."""
        shipped = shipped_skills()
        named = set(SKILL_POINTER.findall(self.text))
        self.assertEqual(
            sorted(named - shipped), [], f"{self.path.name} points at unshipped skills"
        )
        self.assertNotIn("engram-operations", shipped, "shipped now: point at it instead of inlining")
        self.assertNotIn("engram-operations", self.text)


class BaselineContentTest(SharedContentRules, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = BASELINE
        cls.text = BASELINE.read_text(encoding="utf-8")
        cls.headings = headings(cls.text)

    def test_the_baseline_declares_every_required_section(self):
        """A set, not a sequence: adding a section is fine, losing one is not."""
        missing = [
            f"{level} {prefix}"
            for level, prefix in BASELINE_HEADINGS
            if not declares(self.headings, level, prefix)
        ]
        self.assertEqual(missing, [], f"the baseline lost sections; it has {self.headings}")

    def test_the_persona_left_the_baseline(self):
        """The structural proof the split held."""
        for gone in PERSONA_OWNED:
            self.assertNotIn(gone, self.headings)

    def test_the_dead_auto_load_table_is_gone(self):
        """Two hardcoded rows nobody regenerated, superseded by the inventory rule.

        The ban is on the table, not on the names in it: `skill-creator` is a skill
        Pegasus really ships, and the baseline is free to mention it one day.
        """
        self.assertNotIn("Skills (Auto-load based on context)", self.text)
        self.assertNotIn("| Context | Skill to load |", self.text)

    def test_no_section_claims_a_top_level_title(self):
        """It is a section of the runtime's own prompt, not a second document pasted in."""
        self.assertEqual(
            [head for head in self.headings if head.startswith("# ")],
            [],
            "the baseline has no title of its own; nothing in it may claim `#`",
        )

    def test_the_session_summary_template_is_a_fenced_payload(self):
        """Written with `##`, so unfenced it reads as six top-level document sections."""
        self.assertIn("## Goal", self.text)
        for line in ("## Goal", "## Discoveries", "## Accomplished", "## Next Steps"):
            self.assertNotIn(line, self.headings, f"{line!r} is being read as a real heading")

    def test_the_baseline_forbids_nothing_a_shipped_skill_requires(self):
        """`sdd-verify` has to run the build; a universal ban on building contradicts it."""
        self.assertNotIn("Never build after changes", self.text)


class MarkerConventionTest(unittest.TestCase):
    """Markers are how a re-install finds a block it already wrote. One spelling."""

    @classmethod
    def setUpClass(cls):
        cls.text = BASELINE.read_text(encoding="utf-8")

    @staticmethod
    def events(text: str) -> list[tuple[str, str]]:
        """Every marker as (name, "open"|"close"), in the order it appears."""
        found = []
        for slash, token in MARKER.findall(text):
            if slash:
                found.append((token, "close"))
            elif token.endswith(":end"):
                found.append((token.removesuffix(":end"), "close"))
            elif token.endswith(":start"):
                found.append((token.removesuffix(":start"), "open"))
            else:
                found.append((token, "open"))
        return found

    def test_every_marker_is_balanced_ordered_and_disjoint(self):
        """A block that never closes, or closes around another, breaks re-install."""
        stack: list[str] = []
        for name, kind in self.events(self.text):
            if kind == "open":
                self.assertEqual(stack, [], f"{name} opens inside {stack}; blocks must not nest")
                stack.append(name)
            else:
                self.assertTrue(stack, f"{name} closes without opening")
                self.assertEqual(stack.pop(), name, f"{name} closes the wrong block")
        self.assertEqual(stack, [], f"never closed: {stack}")

    def test_the_baseline_rules_block_encloses_its_sections(self):
        """Unmarked or half-marked, a re-install cannot find these to replace them."""
        opened = "<!-- pegasus:baseline-rules -->"
        closed = "<!-- /pegasus:baseline-rules -->"
        self.assertEqual(self.text.count(opened), 1)
        self.assertEqual(self.text.count(closed), 1)
        block = self.text[self.text.index(opened) : self.text.index(closed)]
        for level, prefix in (
            ("##", "Rules"),
            ("##", "Persona Scope"),
            ("##", "Language"),
            ("##", "Contextual Skill Loading"),
        ):
            self.assertTrue(
                declares(headings(block), level, prefix),
                f"{prefix} sits outside the marked block",
            )

    def test_the_engram_block_uses_the_lowercase_pegasus_prefix(self):
        self.assertEqual(self.text.count("<!-- pegasus:engram-protocol -->"), 1)
        self.assertEqual(self.text.count("<!-- /pegasus:engram-protocol -->"), 1)

    def test_no_marker_carries_the_old_capitalised_spelling(self):
        self.assertNotIn("Pegasus baseline:", self.text)

    def test_the_gentle_ai_vocabulary_is_gone_from_the_whole_tree(self):
        offenders = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*.md")
            if "gentle-ai:" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_the_codebase_memory_block_left_the_baseline_for_good(self):
        """CBM protocol centralized to `_shared/cbm-convention.md`; the baseline
        no longer carries its own copy, so its marker pair leaves with it.
        """
        self.assertNotIn("<!-- codebase-memory-mcp:start -->", self.text)
        self.assertNotIn("<!-- codebase-memory-mcp:end -->", self.text)
        self.assertNotIn("pegasus:codebase-memory-mcp", self.text)


class PersonaTest(SharedContentRules, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = PERSONA
        cls.text = PERSONA.read_text(encoding="utf-8")
        cls.content = content_module.load()
        cls.agent = next((a for a in cls.content.agents if a.name == "king-pegasus"), None)

    def test_the_persona_is_registered_as_an_agent(self):
        """Not "the file exists": the loader has to have picked it up as an agent."""
        self.assertIsNotNone(self.agent, "king-pegasus is not among the loaded agents")
        self.assertEqual(self.agent.source.as_posix(), "agents/king-pegasus.md")
        self.assertTrue(self.agent.description.strip())
        self.assertTrue(self.agent.model_configurable)

    def test_the_voice_is_a_top_level_agent_the_user_selects(self):
        """It answers the user, so it is selectable at top level rather than delegated to.

        Being primary is the whole of it now: whether the runtime offers an agent is
        read off the mode rather than declared beside it, so a primary agent cannot
        also be taken out of the switcher. `test_content.py` guards that seam.
        """
        self.assertEqual(self.agent.mode, content_module.AgentMode.PRIMARY)

    def test_the_persona_asks_for_no_more_than_it_needs(self):
        """What the voice declares. That the declaration binds is the adapter's to prove.

        `codebase-memory` joined `read` because king-pegasus acts rather than
        delegates: it does structural discovery too, so it needs CBM. It must
        never gain write, edit, or bash.
        """
        self.assertEqual(list(self.agent.requires_tools), ["read", "codebase-memory"])

    def test_the_persona_carries_the_voice_sections(self):
        """A set, not a sequence: `## Persona Scope` promises these exist."""
        found = headings(self.text)
        missing = [
            f"{level} {prefix}"
            for level, prefix in PERSONA_HEADINGS
            if not declares(found, level, prefix)
        ]
        self.assertEqual(missing, [], f"the persona lost sections; it has {found}")


if __name__ == "__main__":
    unittest.main()
