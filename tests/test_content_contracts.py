"""Nothing shipped may assert a precondition that nothing shipped defines.

The SDD commands open by requiring that "SDD Session Preflight must already be
complete for this session". Ten of them say it. For a long while no file said
what preflight *was*, and no reader could have found out: the commands owned the
gate -- whether work may proceed -- and nobody owned the definition.

That is a contract with an author on one side and nobody on the other, and it is
invisible to every other test in this suite, because each file is individually
well formed. These tests make the two halves check each other.

The second rule here is narrower and came out of the same work: an option value
the definition declares must be a literal something else already uses. Wire
labels are agreed, never invented -- a plausible-looking value that no other file
recognises is worse than a missing one, because it reads as correct at every
review and fails only in a running conversation.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content"
COMMANDS = CONTENT / "commands"
DEFINITION = CONTENT / "skills" / "_shared" / "sdd-session-preflight.md"

TERM = "SDD Session Preflight"

#: The commands state their own requirements in prose; this reads them from there
#: rather than restating them, so the two can never drift apart silently.
REQUIREMENTS = re.compile(r"It must include ([^.]+)\.")

#: A markdown table row whose first cell is a single backticked value.
OPTION = re.compile(r"^\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def documents() -> list[Path]:
    return sorted(path for path in CONTENT.rglob("*.md") if "__pycache__" not in path.parts)


def asserting() -> list[Path]:
    return [path for path in sorted(COMMANDS.glob("*.md")) if TERM in path.read_text(encoding="utf-8")]


def requirements() -> tuple[str, ...]:
    """The four decisions, taken from the sentence the commands themselves assert."""
    for path in asserting():
        found = REQUIREMENTS.search(path.read_text(encoding="utf-8"))
        if found:
            parts = found.group(1).replace(" and ", ", ").split(",")
            return tuple(part.strip() for part in parts if part.strip())
    return ()


def options() -> tuple[str, ...]:
    text = DEFINITION.read_text(encoding="utf-8")
    return tuple(dict.fromkeys(match.group(1) for match in OPTION.finditer(text)))


class PreflightContractTest(unittest.TestCase):
    def test_the_commands_do_assert_it(self):
        """Without this, everything below would pass by having nothing to check."""
        self.assertTrue(asserting(), f"no command asserts {TERM!r}")

    def test_the_assertion_still_names_its_requirements(self):
        """The tests below read the four decisions out of this sentence."""
        self.assertTrue(requirements(), "no command states what preflight must include")

    def test_something_defines_what_it_is(self):
        self.assertTrue(
            DEFINITION.is_file(),
            f"{len(asserting())} commands require {TERM!r} and no shipped file defines it",
        )

    def test_the_definition_covers_every_requirement_asserted(self):
        text = DEFINITION.read_text(encoding="utf-8").casefold()
        missing = [item for item in requirements() if item.casefold() not in text]
        self.assertEqual(missing, [], f"asserted but undefined: {missing}")

    def test_exactly_one_file_claims_authority(self):
        """Two definitions of one term is the problem this closes, wearing a disguise."""
        claiming = [
            path.relative_to(CONTENT)
            for path in documents()
            if "Canonical owner of the term" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(len(claiming), 1, f"more than one file claims the term: {claiming}")


class NoInventedLiteralsTest(unittest.TestCase):
    """An option nobody else recognises reads as correct until it runs."""

    def test_options_were_found(self):
        self.assertTrue(options(), "no option tables found in the definition")

    def test_every_option_is_a_literal_something_else_uses(self):
        others = [path for path in documents() if path != DEFINITION]
        texts = [path.read_text(encoding="utf-8") for path in others]
        invented = [
            option for option in options() if not any(option in text for text in texts)
        ]
        self.assertEqual(invented, [], f"declared here and used nowhere: {invented}")


if __name__ == "__main__":
    unittest.main()
