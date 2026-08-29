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
ENGRAM = ROOT / "mcp" / "engram.md"

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
    ("##", "DELIVERY GUARANTEE"),
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

    def test_the_session_summary_template_moved_to_the_engram_convention(self):
        """The memory protocol -- session-summary template included -- now ships
        only as engram's own convention body, not inlined into the baseline
        every install gets regardless of which servers it chose. The delivery
        guarantee legitimately still names `mem_save` as its worked example,
        so this checks for the protocol's own machinery, not the bare word."""
        self.assertNotIn("## Goal", self.text)
        self.assertNotIn("PROACTIVE SAVE TRIGGERS", self.text)
        self.assertNotIn("Session Close Protocol", self.text)
        self.assertNotIn("mem_search", self.text)
        self.assertNotIn("mem_context", self.text)

    def test_the_baseline_forbids_nothing_a_shipped_skill_requires(self):
        """`sdd-verify` has to run the build; a universal ban on building contradicts it."""
        self.assertNotIn("Never build after changes", self.text)


class MarkerAbsenceTest(unittest.TestCase):
    """The shipped baseline carries no marked block, and nothing reads one."""

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

    def test_the_baseline_carries_no_marked_block(self):
        """Nothing reads a marker, and nothing needs to.

        Markers were the mechanism for merging Pegasus's block into a file the
        user also owns: without them a re-install cannot rewrite one block
        without touching what surrounds it. That is not how the prompt ships.
        Pegasus writes its own file and points the CLI at it, so the file is
        created, replaced and removed whole. A marker no reader looks for is
        inert text in the always-on context of every agent.
        """
        self.assertEqual(self.events(self.text), [])

    def test_no_marker_carries_the_old_capitalised_spelling(self):
        self.assertNotIn("Pegasus baseline:", self.text)

    def test_the_gentle_ai_vocabulary_is_gone_from_the_whole_tree(self):
        offenders = [
            path.relative_to(ROOT).as_posix()
            for path in ROOT.rglob("*.md")
            if "gentle-ai:" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

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

        king-pegasus acts rather than delegates, so it does structural discovery
        too, but it declares no server: this voice is pending a reformulation
        that decides what it may act on. It must never gain write, edit, or bash.
        """
        self.assertEqual(list(self.agent.requires_tools), ["read"])
        self.assertEqual(self.agent.optional_tools, ())
        self.assertEqual(self.agent.optional_mcp, ())

    def test_the_persona_carries_the_voice_sections(self):
        """A set, not a sequence: `## Persona Scope` promises these exist."""
        found = headings(self.text)
        missing = [
            f"{level} {prefix}"
            for level, prefix in PERSONA_HEADINGS
            if not declares(found, level, prefix)
        ]
        self.assertEqual(missing, [], f"the persona lost sections; it has {found}")


class EngramConventionTest(unittest.TestCase):
    """Where the memory protocol -- session-summary template included -- landed
    once it left the baseline: engram's own convention body, shipped only when
    that server is selected."""

    @classmethod
    def setUpClass(cls):
        cls.text = ENGRAM.read_text(encoding="utf-8")
        cls.headings = headings(cls.text)

    def test_the_memory_protocol_lives_here_now(self):
        self.assertIn("mem_save", self.text)
        self.assertIn("## Session Close Protocol", self.text)

    def test_the_session_summary_template_is_a_fenced_payload(self):
        """Written with `##`, so unfenced it reads as six top-level document sections."""
        self.assertIn("## Goal", self.text)
        for line in ("## Goal", "## Discoveries", "## Accomplished", "## Next Steps"):
            self.assertNotIn(line, self.headings, f"{line!r} is being read as a real heading")


if __name__ == "__main__":
    unittest.main()
