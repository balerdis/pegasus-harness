"""Nothing shipped may assert a precondition that nothing shipped defines.

The SDD commands open by requiring that "SDD Session Preflight must already be
complete for this session". Ten of them say it. For a long while no file said
what preflight *was*, and no reader could have found out: the commands owned the
gate -- whether work may proceed -- and nobody owned the definition.

Writing the definition is only half of it, and the cheaper half. A definition
nothing routes to is the same outage wearing a file: the gate still sends the
reader to a prompt they cannot reach. So these tests check both -- that the term
is defined, and that somebody outside its own package points at it.

The second rule here is narrower and came from the same work: an option value the
definition declares must be a literal something else already uses. Wire labels
are agreed, never invented -- a plausible-looking value nobody recognises reads as
correct at every review and fails only in a running conversation. The match is
delimited rather than a substring, because the near-miss is the realistic defect:
`size-exception` and `size:exception` both exist here and mean different things.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

CONTENT = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content"
COMMANDS = CONTENT / "commands"
SHARED = CONTENT / "skills" / "_shared"
DEFINITION = SHARED / "sdd-session-preflight.md"

TERM = "SDD Session Preflight"
AUTHORITY = f"Canonical owner of the term *{TERM}*"

#: The requirements, anchored to the preflight sentence itself. Unanchored, any
#: earlier "It must include ..." in the file would hijack the whole contract.
REQUIREMENTS = re.compile(rf"{re.escape(TERM)} must already be complete[^.]*\.\s*It must include ([^.]+)\.")

#: A markdown table row whose first cell is a single backticked value.
OPTION = re.compile(r"^\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def documents() -> list[Path]:
    return sorted(path for path in CONTENT.rglob("*.md") if "__pycache__" not in path.parts)


def sdd_commands() -> list[Path]:
    return sorted(COMMANDS.glob("sdd-*.md"))


def asserting() -> list[Path]:
    return [path for path in sdd_commands() if TERM in path.read_text(encoding="utf-8")]


def requirements_in(path: Path) -> tuple[str, ...]:
    found = REQUIREMENTS.search(path.read_text(encoding="utf-8"))
    if not found:
        return ()
    parts = found.group(1).replace(" and ", ", ").split(",")
    return tuple(part.strip() for part in parts if part.strip())


def options() -> tuple[str, ...]:
    text = DEFINITION.read_text(encoding="utf-8") if DEFINITION.is_file() else ""
    return tuple(dict.fromkeys(match.group(1) for match in OPTION.finditer(text)))


def uses(literal: str, text: str) -> bool:
    """A delimited use, so `size:exception` never vouches for `size-exception`."""
    return re.search(rf"(?<![\w:.-]){re.escape(literal)}(?![\w:.-])", text) is not None


class PreflightContractTest(unittest.TestCase):
    def test_the_commands_do_assert_it(self):
        """Without this, everything below would pass by having nothing to check."""
        self.assertTrue(asserting(), f"no command asserts {TERM!r}")

    def test_every_sdd_command_still_carries_the_gate(self):
        """A command that quietly loses the gate is the outage, not a tidy-up."""
        without = [path.name for path in sdd_commands() if path not in asserting()]
        self.assertEqual(without, [], f"SDD commands with no preflight gate: {without}")

    def test_something_defines_what_it_is(self):
        self.assertTrue(
            DEFINITION.is_file(),
            f"{len(asserting())} commands require {TERM!r} and no shipped file defines it",
        )

    def test_the_commands_agree_on_what_it_must_include(self):
        """Reading one command and trusting the rest is how the two halves drift."""
        stated = {path.name: requirements_in(path) for path in asserting()}
        silent = sorted(name for name, items in stated.items() if not items)
        self.assertEqual(silent, [], f"assert the term but state no requirements: {silent}")
        self.assertEqual(len(set(stated.values())), 1, f"commands disagree: {stated}")

    def test_the_definition_covers_every_requirement_asserted(self):
        self.assertTrue(DEFINITION.is_file(), "there is no definition to check")
        text = DEFINITION.read_text(encoding="utf-8").casefold()
        asked = set().union(*(requirements_in(path) for path in asserting()))
        missing = sorted(item for item in asked if item.casefold() not in text)
        self.assertEqual(missing, [], f"asserted but undefined: {missing}")

    def test_a_consumer_can_actually_reach_it(self):
        """A definition nothing routes to is the same outage wearing a file.

        `_shared` declares itself not invokable, so its index pointing at the
        document proves nothing: somebody who reads it in the course of work has
        to be sent there.
        """
        referrers = [
            path.relative_to(CONTENT)
            for path in documents()
            if path != DEFINITION
            and path != SHARED / "SKILL.md"
            and DEFINITION.name in path.read_text(encoding="utf-8")
        ]
        self.assertTrue(referrers, f"only its own package index points at {DEFINITION.name}")

    def test_exactly_one_file_claims_the_term(self):
        claiming = [
            path.relative_to(CONTENT)
            for path in documents()
            if AUTHORITY in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(claiming, [DEFINITION.relative_to(CONTENT)], f"claimants: {claiming}")

    def test_no_option_has_its_default_declared_in_two_places(self):
        """Two definitions of one value is the original problem wearing a disguise.

        Only defaults for values this definition declares are the business of this
        test; a skill saying it defaults to English is nobody's contradiction.
        """
        clashing = {}
        for option in options():
            declaring = [
                str(path.relative_to(CONTENT))
                for path in documents()
                if re.search(
                    rf"[Dd]efaults? (?:to|when|only when)[^.\n]*`{re.escape(option)}`",
                    path.read_text(encoding="utf-8"),
                )
            ]
            if len(declaring) > 1:
                clashing[option] = declaring
        self.assertEqual(clashing, {}, f"a default declared in more than one file: {clashing}")


class NoInventedLiteralsTest(unittest.TestCase):
    """An option nobody else recognises reads as correct until it runs."""

    def test_options_were_found(self):
        self.assertTrue(options(), "no option tables found in the definition")

    def test_every_option_is_a_literal_something_else_uses(self):
        texts = [path.read_text(encoding="utf-8") for path in documents() if path != DEFINITION]
        invented = [item for item in options() if not any(uses(item, text) for text in texts)]
        self.assertEqual(invented, [], f"declared here and used nowhere: {invented}")


if __name__ == "__main__":
    unittest.main()
