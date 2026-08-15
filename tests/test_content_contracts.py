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

#: The two forms in which the definition declares an option: a table row whose first
#: cell is the value, and an explicit `Values:` line. Reading only tables is how eight
#: literals silently left this set when their tables became prose.
OPTION_ROW = re.compile(r"^\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)
OPTION_LIST = re.compile(r"^Values:(.+)$", re.MULTILINE)
BACKTICKED = re.compile(r"`([^`]+)`")

#: How many the definition is expected to declare. A value that stops being seen would
#: otherwise vanish from the checked set instead of failing.
DECLARED = 14

#: A default is declared where a backticked value shares a line with the word Default.
#: Blockquote lines are what is said to the user, not a declaration -- quoting a default
#: while asking is not owning it.
DEFAULT = re.compile(r"^(?!>).*\bDefaults?\b.*$", re.MULTILINE | re.IGNORECASE)


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
    found = [match.group(1) for match in OPTION_ROW.finditer(text)]
    for line in OPTION_LIST.finditer(text):
        found.extend(BACKTICKED.findall(line.group(1)))
    return tuple(dict.fromkeys(found))


def declares_default(text: str, option: str) -> bool:
    return any(f"`{option}`" in line for line in DEFAULT.findall(text))


def uses(literal: str, text: str) -> bool:
    """A delimited use, so `size:exception` never vouches for `size-exception`."""
    return re.search(rf"(?<![\w:-]){re.escape(literal)}(?![\w:-])", text) is not None


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
        referrers = {
            str(path.relative_to(CONTENT))
            for path in documents()
            if SHARED not in path.parents
            and DEFINITION.name in path.read_text(encoding="utf-8")
        }
        self.assertTrue(referrers, f"nothing outside its own package points at {DEFINITION.name}")

        # The route that was actually installed, named. Without this the whole of it
        # can be reverted and a sibling inside `_shared` still satisfies the test.
        expected = {"agents/pegasus-orchestrator.md"} | {
            str(path.relative_to(CONTENT)) for path in sdd_commands()
        }
        self.assertEqual(expected - referrers, set(), f"lost the route: {expected - referrers}")

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
        texts = {path: path.read_text(encoding="utf-8") for path in documents()}
        declaring = {
            option: [
                str(path.relative_to(CONTENT))
                for path, text in texts.items()
                if declares_default(text, option)
            ]
            for option in options()
        }
        self.assertTrue(
            any(declaring.values()), "no default is declared anywhere; the rule went silent"
        )

        # The Authority rule, executable: a command may describe how it behaves under a
        # resolved value, it may not set one. Only the shared contract package may.
        package = str(SHARED.relative_to(CONTENT))
        outside = {
            option: [name for name in files if not name.startswith(package)]
            for option, files in declaring.items()
        }
        outside = {option: files for option, files in outside.items() if files}
        self.assertEqual(outside, {}, f"a default set away from the shared contract: {outside}")

        clashing = {option: files for option, files in declaring.items() if len(files) > 1}
        self.assertEqual(clashing, {}, f"a default declared in more than one file: {clashing}")


class NoInventedLiteralsTest(unittest.TestCase):
    """An option nobody else recognises reads as correct until it runs."""

    def test_every_declared_option_is_still_seen(self):
        """A value that stops matching would leave the checked set without failing."""
        self.assertEqual(len(options()), DECLARED, f"seen: {options()}")

    def test_every_option_is_a_literal_something_else_uses(self):
        texts = [path.read_text(encoding="utf-8") for path in documents() if path != DEFINITION]
        invented = [item for item in options() if not any(uses(item, text) for text in texts)]
        self.assertEqual(invented, [], f"declared here and used nowhere: {invented}")


if __name__ == "__main__":
    unittest.main()
