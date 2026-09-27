"""Closed-world pin: the tool-absence-vs-denial bullet `AGENTS.md` gains in
7.3.3 (see `docs/arquitectura/arquitectura.md`'s own section for the
measurement behind it).

A live interactive test found the Claude Code orchestrator lacking the
engram tools -- they were simply absent, and the runtime's own error was
`No such tool available`, never a denial. It read that absence as a denial,
cited this file's existing "Tell the two denials apart" bullet (`## Editing
Something Your Editing Tools Cannot Reach`, `test_editing_reach_scope.py`),
and refused a legitimate delegation to a sub-agent that has engram. It also
inferred the sub-agent lacked MCP from its `tools:` line, which is wrong,
and proposed registering the server itself rather than asking.

The existing bullet is correct and untouched: a tool the runtime *denies*
still closes every other route. What was missing is the other half -- a
tool simply never given closes nothing by itself -- and this file pins the
new bullet that states it, plus holds the subject closed-world across the
whole system-prompt tree the same way `test_credential_transport_content.py`
holds rotation advice: the pinned bullet is the only sentence in the
always-on system prompt allowed to touch "a tool absent from your own
toolset", so a future edit that reintroduces the old, over-broad reading
elsewhere fails here rather than surviving unnoticed.

`TOOL_ABSENCE_STEM` names the subject, not its negation -- it matches the
sanctioned bullet too, which is fine: sanctioning is proven by exact bullet
membership below, the same split `test_credential_transport_content.py`
already draws between "touches the subject" and "is the one paragraph
allowed to".
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
AGENTS_MD = CONTENT / "system-prompt" / "AGENTS.md"
SYSTEM_PROMPT = CONTENT / "system-prompt"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def bullets_of(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.lstrip().startswith("- ")]


#: The subject: a tool absent from an agent's own toolset, said in the same
#: breath as "not a denial" -- in whichever order a paraphrase states the
#: two halves. Not a negation classifier (see module docstring): it matches
#: by naming the subject, never by excluding some other phrasing of it.
TOOL_ABSENCE_STEM = re.compile(
    r"\babsent\b[^.]*\btoolset\b[^.]*\bnot\b[^.]*\bdenial\b"
    r"|\bnot\b[^.]*\bdenial\b[^.]*\babsent\b[^.]*\btoolset\b",
    re.IGNORECASE,
)


def lines_on(text: str, stem: re.Pattern[str]) -> set[str]:
    return {line for line in bullets_of(text) if stem.search(line)}


#: The exact bullet added to `## Editing Something Your Editing Tools
#: Cannot Reach`, right after "Tell the two denials apart" -- same section,
#: because this is the third fact about tool reach that section already
#: exists to state, not a new topic.
AGENTS_TOOL_ABSENCE_BULLET = (
    "- A tool absent from your own toolset is not a denial and closes no route by itself: nobody "
    "told you no, you were simply never given it, and that says nothing about what another agent "
    "can reach. Delegating to an agent whose own reach includes it is legitimate when the task "
    "calls for it: `{{skills_root}}/_shared/delegation-capabilities.md`, where present, is what "
    "actually lists a target's reach — never a target's own `tools:` line, which is not the same "
    "fact and was misread as one. Installing or registering a server yourself to close the gap is "
    "not your call: say what is missing and ask."
)


class AgentsToolAbsenceBulletTest(unittest.TestCase):
    def test_the_bullet_is_present_verbatim(self):
        text = read(AGENTS_MD)
        self.assertIn(AGENTS_TOOL_ABSENCE_BULLET, bullets_of(text))

    def test_it_names_the_subject(self):
        self.assertTrue(TOOL_ABSENCE_STEM.search(AGENTS_TOOL_ABSENCE_BULLET))

    def test_it_states_delegation_is_legitimate(self):
        self.assertIn("legitimate when the task calls for it", AGENTS_TOOL_ABSENCE_BULLET)

    def test_it_points_at_the_delegation_reference(self):
        self.assertIn("delegation-capabilities.md", AGENTS_TOOL_ABSENCE_BULLET)

    def test_it_says_installing_a_server_is_not_the_agents_call(self):
        self.assertIn("not your call", AGENTS_TOOL_ABSENCE_BULLET)

    def test_the_existing_denial_rule_is_untouched(self):
        """The fix for a misfire, not a rewrite of the rule that misfired:
        the "Tell the two denials apart" bullet stays exactly as it was --
        `test_editing_reach_scope.py` already pins its own claims."""
        text = read(AGENTS_MD)
        self.assertIn(
            "Tell the two denials apart, because only one of them closes every path.",
            text,
        )


class ToolAbsenceIsClosedWorldTest(unittest.TestCase):
    """The pinned bullet is the only sentence in the always-on system prompt
    that may touch the tool-absence-vs-denial subject."""

    def test_only_the_pinned_bullet_touches_the_subject_anywhere_in_the_system_prompt(self):
        offenders: dict[str, set[str]] = {}
        for path in sorted(SYSTEM_PROMPT.rglob("*")):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            found = lines_on(text, TOOL_ABSENCE_STEM)
            allowed = found - {AGENTS_TOOL_ABSENCE_BULLET}
            if allowed:
                offenders[str(path.relative_to(ROOT))] = allowed
        self.assertEqual(offenders, {}, f"unexpected sentence(s) on the tool-absence subject: {offenders}")


if __name__ == "__main__":
    unittest.main()
