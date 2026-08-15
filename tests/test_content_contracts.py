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

#: One decision of the definition, so a rule can be scoped to a decision rather than to
#: a literal: two files naming different defaults for the same decision contradict each
#: other just as loudly as two naming the same one.
SECTION = re.compile(r"^### \d+\.\s*(.+)$", re.MULTILINE)

#: How the rest of the tree enumerates a decision's values: pipe separated, delimited or
#: bare after a label. This is what the definition is checked against, so the values are
#: never restated here -- a swapped literal fails against the consumer that reads it.
ENUMERATION = re.compile(
    r"[`{<(]([a-z][\w:. -]*(?:\|[\w:. -]+)+)[`}>)]"
    r"|^[A-Z][\w ]*:\s*([a-z][\w:.-]*(?:\|[\w:.-]+)+)\s*$",
    re.MULTILINE,
)

#: Which file already enumerates each decision. Structure, not values: the values stay
#: derived. Without it a declared set can be validated against an unrelated enumeration
#: that happens to overlap, which is how a chain strategy adopted a set of modes.
CONSUMERS = {
    "Execution mode": "commands/sdd-ff.md",
    "Artifact store": "skills/_shared/persistence-contract.md",
    "Chained PR strategy": "skills/sdd-tasks/SKILL.md",
}

#: A default is declared when the marker is bound to the value it marks, not when both
#: merely appear. Co-occurrence reads "the default value ... is `auto`" as prose and
#: "do not assume `engram` is the default" as a declaration; both are wrong.
DECLARATION = "(?:[Dd]efaults?\\b[^`\\n]{{0,70}}?`{0}`|`{0}`[^`\\n]{{0,70}}?\\*\\*Default)"

#: A sentence that forbids a default is not one. It is the shape a careful author uses.
NEGATED = re.compile(
    r"\b(?:do not|don't|never|not)\s+(?:assume|use|set|hardcode|infer)\b"
    r"|\bno default\b|\bnot the default\b"
)

#: A line said to the user, not a declaration. Quoting a default while asking is not
#: owning it, and indentation must not change that.
QUOTED = re.compile(r"^[ \t]*>", re.MULTILINE)

#: A list item or heading begins its own unit; a line under it is its continuation.
ITEM = re.compile(r"^(?:[-*+]\s|\d+\.\s|#)")


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


def sentences(text: str) -> list[str]:
    """The units a declaration can occupy, so neither wrapping nor a table fools it.

    Prose wraps, so a paragraph is joined before being split on sentences -- otherwise
    a default stated across a line break is invisible. A table row is its own unit for
    the opposite reason: joined, one `**Default.**` in a table would mark every value
    in it as defaulted.
    """
    units, buffer = [], []

    def flush():
        if buffer:
            units.extend(re.split(r"(?<=\.)\s", " ".join(buffer)))
            buffer.clear()

    for line in text.splitlines():
        if QUOTED.match(line):
            continue
        stripped = line.strip()
        if stripped.startswith("|"):
            # Whole, and never sentence-split: a row reads "... risk. **Default.** |",
            # and splitting it strands the marker away from the value it marks.
            flush()
            units.append(stripped)
        elif not stripped or ITEM.match(stripped):
            flush()
            if stripped:
                buffer.append(stripped)
        else:
            buffer.append(stripped)
    flush()
    return units


def declares_default(text: str, option: str) -> bool:
    bound = re.compile(DECLARATION.format(re.escape(option)))
    return any(
        bound.search(sentence) and not NEGATED.search(sentence)
        for sentence in sentences(text)
    )


def declared_by_decision() -> dict[str, set[str]]:
    """Every value the definition declares, grouped by the decision it belongs to."""
    text = DEFINITION.read_text(encoding="utf-8") if DEFINITION.is_file() else ""
    parts = SECTION.split(text)
    grouped = {}
    for title, body in zip(parts[1::2], parts[2::2]):
        values = [match.group(1) for match in OPTION_ROW.finditer(body)]
        for line in OPTION_LIST.finditer(body):
            values.extend(BACKTICKED.findall(line.group(1)))
        if values:
            grouped[title.strip()] = set(values)
    return grouped


def declared_groups() -> list[tuple[str, set[str]]]:
    """Each declaration form on its own, because one decision may hold two sets.

    The chained-PR decision declares the delivery values and the chain values, and the
    consumers enumerate them separately, which is the shape that has to be compared.
    """
    text = DEFINITION.read_text(encoding="utf-8") if DEFINITION.is_file() else ""
    parts = SECTION.split(text)
    groups = []
    for title, body in zip(parts[1::2], parts[2::2]):
        rows = {match.group(1) for match in OPTION_ROW.finditer(body)}
        if rows:
            groups.append((title.strip(), rows))
        for line in OPTION_LIST.finditer(body):
            groups.append((title.strip(), set(BACKTICKED.findall(line.group(1)))))
    return groups


def enumerations(within: str | None = None) -> list[set[str]]:
    """Every value set the tree spells out, optionally only in one consumer."""
    found = []
    for path in documents():
        if path == DEFINITION:
            continue
        if within and str(path.relative_to(CONTENT)) != within:
            continue
        for match in ENUMERATION.finditer(path.read_text(encoding="utf-8")):
            spelled = match.group(1) or match.group(2)
            found.append({item.strip() for item in spelled.split("|")})
    return found


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
            and f"_shared/{DEFINITION.name}" in path.read_text(encoding="utf-8")
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

        # Scoped to the decision and counted by FILE, not by literal. Naming a different
        # value as the default for the same decision contradicts just as loudly, while one
        # file expressing a conditional default -- `engram` when available, else `none` --
        # is a single answer and not a clash.
        for decision, values in declared_by_decision().items():
            owners = sorted(
                {name for option, files in declaring.items() if option in values for name in files}
            )
            self.assertLessEqual(
                len(owners), 1, f"{decision}: more than one file sets its default: {owners}"
            )


class NoInventedLiteralsTest(unittest.TestCase):
    """An option nobody else recognises reads as correct until it runs."""

    def test_every_decision_matches_the_set_its_consumers_read(self):
        """Counting the values only proves how many there are, not which.

        Swapping one literal for another that exists elsewhere keeps every count and
        every use valid, which is how `size:exception` shipped as a chain strategy
        through three rounds of this test. So the values are never restated here:
        each decision is compared against the enumeration a consumer already spells
        out, and a decision whose set overlaps one must equal it.
        """
        for decision, declared in declared_groups():
            consumer = CONSUMERS.get(decision)
            self.assertIsNotNone(consumer, f"{decision} names no consumer to check against")

            spelled = [
                other for other in enumerations(within=consumer) if len(declared & other) >= 2
            ]
            # Counting how many decisions could be checked is how a decision goes
            # unchecked in silence, so every group must find its consumer.
            self.assertTrue(spelled, f"{decision}: {consumer} enumerates nothing like {declared}")

            # The consumer must also agree with itself. One place spelling a value one way
            # and another spelling it differently is the contradiction, wherever it lands.
            self.assertEqual(
                [other for other in spelled if other != spelled[0]],
                [],
                f"{decision}: {consumer} spells it more than one way: {spelled}",
            )
            self.assertEqual(
                declared, spelled[0], f"{decision}: {consumer} reads {spelled[0]}, not {declared}"
            )

    def test_every_option_is_a_literal_something_else_uses(self):
        texts = [path.read_text(encoding="utf-8") for path in documents() if path != DEFINITION]
        invented = [item for item in options() if not any(uses(item, text) for text in texts)]
        self.assertEqual(invented, [], f"declared here and used nowhere: {invented}")


if __name__ == "__main__":
    unittest.main()
