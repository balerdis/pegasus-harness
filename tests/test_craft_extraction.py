"""The three SDD phase skills point at a craft reference instead of restating it.

`sdd-explore`, `sdd-verify` and `sdd-apply` used to mix craft (how to explore,
verify, or implement well) with chain (the SDD artifact envelope, persistence,
the archive verdict). The craft moved out to `_shared/exploration-craft.md`,
`_shared/verification-craft.md` and `_shared/implementation-craft.md`; the phase
skills keep only the chain-bound parts and point at the craft file for the rest.

Each assertion below is about a FACT (a distinctive sentence lives in exactly one
file across the whole shipped content tree), not about a filename string being
present somewhere -- a phase skill could name its craft file in prose while still
silently restating the craft it is supposed to point at instead.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_phase_less_specialists import PHASE_MARKERS

CONTENT = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content"
SKILLS = CONTENT / "skills"
CRAFT = SKILLS / "_shared" / "implementation-craft.md"

#: Slice (d): the Strict TDD reading rule, with one owner. A distinctive phrase
#: of it, and the rule's clauses pinned as written -- each a permission or a
#: prohibition, so each is closed-world: there exactly once, and no other
#: sentence of the same file on the same subject.
RULE_NEEDLE = "Resolve the mode once, in this order"
RULE_HEADING = "### Resolving Strict TDD Mode"
RULE_POINTER = '"Resolving Strict TDD Mode" in `_shared/implementation-craft.md`'
RULE_STEPS = (
    "A marker in the instructions already in context",
    "The project flag",
    "The runner default",
)
#: Every sentence of the craft file on the rule's subjects -- the marker, a
#: brief, a runner, the project flag, a change with no behavior, standard
#: mode, a fallback, a default, or setting the mode aside -- as written. The
#: first five and the hard-gate line predate slice (d) and are pinned so a new
#: "otherwise default to standard mode" cannot join them unseen.
CRAFT_RULE_SENTENCES = frozenset(
    {
        # The hard gate's own line: seen once the subject learned "without
        # writing tests".
        "If you complete a task WITHOUT writing tests first, mark it as FAILED in the evidence table",
        "**There is no silent fallback.** If Strict TDD is active, follow it or report failure.",
        "Do not quietly switch to standard mode.",
        "Every assigned work unit, including standard mode, MUST produce a **Work Unit Evidence** table before "
        "its tasks are marked complete:",
        "If design/tasks contain applicable threat-matrix cases, write and run each mapped RED test before the "
        "corresponding production change even in standard mode.",
        "The default PR review budget is **400 changed lines** (`additions + deletions`), counting authored text "
        "additions plus deletions only; generated goldens are excluded from that count.",
        "**A marker in the instructions already in context**, opening no file for it.",
        # The rule's second step: seen once the subject learned the project flag.
        "**The project flag** `sdd-init` wrote: `strict_tdd` in `openspec/config.yaml`, or Engram's "
        "`sdd/{project}/testing-capabilities`.",
        "A marker is a line whose whole content is `Strict TDD Mode: enabled` or `Strict TDD Mode: disabled`, "
        "or that line with its label in bold, `**Strict TDD Mode**: enabled`; no other shape is one.",
        "A project's marker beats the person's; contradictory markers of unclear origin count as none: say so "
        "and go on.",
        "**The runner default**: a test runner means active; none means inactive, and say so.",
        "`enabled` without a test runner is inactive, and say so.",
        "A brief carrying the marker's spelling has already resolved the mode; a brief with no spelling this "
        "rule recognizes is resolved here, never silently as standard mode.",
        "A change with no behavior to test records `N/A: no behavior changed` as its gate result, never FAILED.",
    }
)
CRAFT_RULE_SUBJECT = re.compile(
    r"marker|brief|runner|no behavior|standard mode|fall ?back|default|inactive"
    # Review found "skip TDD", "treat as disabled" and "assume off" missing:
    # the ways to say the mode is off without naming standard mode.
    r"|\bskip|\btreat|\bassum|\bdisabl|\boff\b|\bwithout tdd\b|\bno tdd\b"
    # The vocabulary corpus found the rest: other ways to set the mode aside
    # ("opt out", "waive", "optional", "proceed without tests"), and the
    # project flag the rule reads second.
    r"|opt(?:s|ed|ing)?[- ]out|bypass|\bignor|\bwaiv|\brelax|\bsuspend|optional|not (?:required|needed|mandatory)"
    r"|\bflag\b|strict_tdd|config|without (?:writing )?tests?",
    re.IGNORECASE,
)

#: The readers. Each unit -- a table row, a fence line, a heading, or a prose
#: sentence -- that speaks of resolving the mode, as written. Nothing else in
#: the reader may: a reader that restated the rule, or quietly defaulted to
#: standard mode, fails here whatever its wording.
READER_UNITS = {
    SKILLS / "sdd-init" / "SKILL.md": frozenset(
        {
            '| Strict TDD Mode | Resolve it with "Resolving Strict TDD Mode" in `_shared/implementation-craft.md`, '
            "then persist the result as `strict_tdd`. |",
            'Resolve Strict TDD Mode with "Resolving Strict TDD Mode" in `_shared/implementation-craft.md`, using '
            "the runner step 2 found.",
            "Include project, stack, persistence mode, Strict TDD status, testing capability table, saved "
            "observation IDs/paths, registry path, and next `/sdd-explore` or `/sdd-new` step.",
        }
    ),
    SKILLS / "sdd-apply" / "SKILL.md": frozenset(
        {
            "### Step 3: Resolve Strict TDD Mode",
            "Take `Strict TDD Mode` from your brief first.",
            'Without it, resolve the mode with "Resolving Strict TDD Mode" in `_shared/implementation-craft.md`, '
            "which also says what a brief with no recognized spelling means.",
        }
    ),
    SKILLS / "sdd-verify" / "SKILL.md": frozenset(
        {
            "| Brief says `Strict TDD Mode: enabled` | Strict TDD verify; load module. |",
            "| Brief says `Strict TDD Mode: disabled` | Standard verify; skip TDD checks. |",
            '| No recognized spelling in the brief | Resolve with "Resolving Strict TDD Mode" in '
            "`_shared/implementation-craft.md`. |",
            "Resolve Strict TDD Mode as the Decision Gates say.",
        }
    ),
}
READER_SUBJECT_MODE = re.compile(r"strict[ _-]?tdd|tdd mode|standard mode|test-driven mode", re.IGNORECASE)
READER_SUBJECT_RESOLUTION = re.compile(
    r"brief|strict_tdd|runner|marker|resolv|config|cache|capabilit|default|fall|spelling|recogni"
    r"|detect|infer|determin|decid|look(?:s|ed|ing)? up|lookup|assum|treat|flag|setting|persist|\bsav(?:e|es|ed|ing)\b",
    re.IGNORECASE,
)

#: A marker's spelling wherever the shipped tree writes it, counted per file.
#: Closed world: a new mention anywhere -- a template, a sentence, a stray
#: line -- changes a count and fails until the pin is edited on purpose.
MARKER_MENTION = re.compile(r"Strict TDD Mode\**\s*:\s*\**\s*[{<]?(?:enabled|disabled)", re.IGNORECASE)
MARKER_MENTIONS = {
    CRAFT: 3,
    SKILLS / "sdd-verify" / "SKILL.md": 2,
    SKILLS / "sdd-init" / "references" / "init-details.md": 1,
    # d5: the brief line, written as a template value -- never a bare marker.
    SKILLS / "_shared" / "sdd-session-preflight.md": 1,
    SKILLS / "_shared" / "ftd-procedure.md": 1,
}
#: A line that IS a marker, once list markers, quotes, backticks and bold are
#: peeled off. Pegasus never switches the mode on or off for the person, so no
#: shipped file may carry one.
BARE_MARKER = re.compile(r"^\**strict tdd mode\**\s*:\s*\**\s*(?:enabled|disabled)\**$", re.IGNORECASE)

#: d5: the mode is resolved once per session and travels in the brief. The
#: sentences that say so, pinned as written, and the files that must say
#: nothing else about Strict TDD. The subject is matched by its register, not
#: one spelling: "Strict TDD", "TDD", "test-driven", "test first", "red-green".
BRIEF_TEMPLATE = "`Strict TDD Mode: <enabled|disabled>`"
PREFLIGHT = SKILLS / "_shared" / "sdd-session-preflight.md"
PROCEDURE = SKILLS / "_shared" / "ftd-procedure.md"
KING = CONTENT / "agents" / "king-pegasus.md"
ORCHESTRATOR = CONTENT / "agents" / "pegasus-orchestrator.md"
PREFLIGHT_BRIEF = (
    'Resolve Strict TDD Mode once per session with "Resolving Strict TDD Mode" in `_shared/implementation-craft.md`, '
    "and pass it to every implementation launch as `Strict TDD Mode: <enabled|disabled>`, filled with the value "
    "resolved."
)
PROCEDURE_BRIEF = (
    'Whoever coordinates the FTD resolves Strict TDD Mode once per session with "Resolving Strict TDD Mode" in '
    "`_shared/implementation-craft.md`, and sends it in every implementation brief as "
    "`Strict TDD Mode: <enabled|disabled>`, filled with the value resolved."
)
KING_TDD = (
    "Resolve Strict TDD Mode once per session with `{{skills_root}}/_shared/implementation-craft.md` before "
    "writing code; if it is missing or unreadable, judge it yourself and say so."
)
TDD_SUBJECT = re.compile(
    r"strict[ _-]?tdd|\btdd\b|test[- ]driven|tests? first|test-first|red[- ]green|red\s*→\s*green"
    # Review found "always write tests before code" missing: the mode can be
    # overridden without naming it, by describing its discipline.
    r"|tests? before|before (?:writing )?(?:the )?code|failing test|\brgr\b|testing discipline"
    r"|\bred\b[^.]{0,40}\bgreen\b|write (?:the |a )?tests?\b"
    # The vocabulary corpus found the rest: "watch the test fail", "tests up
    # front", "no code without a failing test", "a RED test".
    r"|(?:see|watch)(?:es|ed|ing)? (?:it|them|the tests?) fail|tests? up-?\s?front"
    r"|code without (?:a |the )?(?:failing )?tests?|\bred (?:test|phase|step)",
    re.IGNORECASE,
)
#: What each file may say about Strict TDD, and nothing more. The orchestrator
#: says nothing: in L0 it loads neither the preflight nor the procedure, and
#: the implementer resolves the mode with the same rule.
TDD_UNITS = {
    PREFLIGHT: frozenset({PREFLIGHT_BRIEF}),
    PROCEDURE: frozenset({PROCEDURE_BRIEF}),
    KING: frozenset({KING_TDD}),
    ORCHESTRATOR: frozenset(),
}

#: The phrase the rule replaced, which nothing ever sent.
DEAD_TDD_PHRASE = "STRICT TDD MODE IS ACTIVE"

#: The phase-result headings, derived from the set the specialist guard already
#: forbids in a phase-less agent body rather than retyped here -- a future phase
#: marker that is a heading is covered without anyone remembering this file.
#: Filtered to the heading-shaped members: `PHASE_MARKERS` also carries
#: "Required loading gate" and "return `blocked`", which are not envelopes.
ENVELOPE_HEADINGS = tuple(marker for marker in PHASE_MARKERS if marker.startswith("## "))


def all_text() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in SKILLS.rglob("*.md")
        if "__pycache__" not in path.parts
    }


def occurrences(needle: str) -> list[Path]:
    return [path for path, text in all_text().items() if needle in text]


def content_files() -> list[Path]:
    """Every shipped text file in the content tree, not only the skills."""
    return sorted(
        path for path in CONTENT.rglob("*") if path.is_file() and "__pycache__" not in path.parts
    )


def content_occurrences(needle: str) -> list[Path]:
    """Files whose text, whitespace collapsed, contains `needle` -- a phrase
    wrapped across two source lines is still the phrase."""
    return [
        path
        for path in content_files()
        if needle in " ".join(path.read_text(encoding="utf-8", errors="replace").split())
    ]


def units_of(text: str) -> list[str]:
    """Table rows, fence lines and headings as they are; every list item and
    prose paragraph collapsed and cut into sentences, a leading list marker
    stripped."""
    units: list[str] = []
    paragraph: list[str] = []
    fenced = False

    def flush() -> None:
        if paragraph:
            for part in re.split(r"(?<=[.!?])\s+", " ".join(" ".join(paragraph).split())):
                part = re.sub(r"^(?:- |\d+\. )", "", part).strip()
                if part:
                    units.append(part)
            paragraph.clear()

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            flush()
            fenced = not fenced
        elif fenced or stripped.startswith("|") or stripped.startswith("#"):
            flush()
            if stripped:
                units.append(stripped)
        elif not stripped:
            flush()
        elif re.match(r"(?:- |\d+\. )", stripped):
            flush()
            paragraph.append(stripped)
        else:
            paragraph.append(stripped)
    flush()
    return units


def peeled(line: str) -> str:
    """A line with its list, quote and heading markers and its wrapping
    backticks removed. A heading is still a line a model reads as content, so
    `## Strict TDD Mode: enabled` has to peel to a bare marker too."""
    line = line.strip()
    line = re.sub(r"^(?:[-*+>]\s+|\d+[.)]\s+|#{1,6}\s+)+", "", line)
    return line.strip("`'\" ").strip()


def marker_candidates(line: str) -> list[str]:
    """What a model could read as a whole line: the line itself, peeled, and --
    for a table row -- each of its cells, since a one-cell row or a cell of its
    own is read the same way."""
    candidates = [peeled(line)]
    if line.strip().startswith("|"):
        candidates += [peeled(cell) for cell in line.strip().strip("|").split("|")]
    return candidates


class CraftFilesExistTest(unittest.TestCase):
    def test_exploration_craft_exists(self):
        self.assertTrue((SKILLS / "_shared" / "exploration-craft.md").is_file())

    def test_verification_craft_exists(self):
        self.assertTrue((SKILLS / "_shared" / "verification-craft.md").is_file())

    def test_implementation_craft_exists(self):
        self.assertTrue((SKILLS / "_shared" / "implementation-craft.md").is_file())


class PhaseSkillsPointAtCraftTest(unittest.TestCase):
    def test_sdd_explore_points_at_exploration_craft(self):
        text = (SKILLS / "sdd-explore" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("_shared/exploration-craft.md", text)

    def test_sdd_verify_points_at_verification_craft(self):
        text = (SKILLS / "sdd-verify" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("_shared/verification-craft.md", text)

    def test_sdd_apply_points_at_implementation_craft(self):
        text = (SKILLS / "sdd-apply" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("_shared/implementation-craft.md", text)


class CraftIsNotRestatedTest(unittest.TestCase):
    """A distinctive instruction from each craft file must live nowhere else.

    Proves the fact the extraction promises -- the phase skill no longer
    restates the craft -- rather than merely proving the pointer exists.
    """

    def test_the_investigation_checklist_lives_only_in_exploration_craft(self):
        found = occurrences("INVESTIGATE:")
        self.assertEqual(found, [SKILLS / "_shared" / "exploration-craft.md"])

    def test_the_comparison_order_lives_only_in_verification_craft(self):
        found = occurrences("Compare specs first, design second, task completion third.")
        self.assertEqual(found, [SKILLS / "_shared" / "verification-craft.md"])

    def test_the_work_unit_evidence_gate_lives_only_in_implementation_craft(self):
        found = occurrences("MUST produce a **Work Unit Evidence** table")
        self.assertEqual(found, [SKILLS / "_shared" / "implementation-craft.md"])

    def test_the_strict_tdd_reading_rule_lives_only_in_implementation_craft(self):
        """Across the whole content tree, agents and system prompt included."""
        self.assertEqual(content_occurrences(RULE_NEEDLE), [CRAFT])

    def test_the_readers_point_at_the_rule_instead_of_restating_it(self):
        for reader in READER_UNITS:
            with self.subTest(reader=reader.relative_to(SKILLS).as_posix()):
                self.assertIn(RULE_POINTER, " ".join(reader.read_text(encoding="utf-8").split()))

    def test_the_implementer_reaches_the_rule_through_its_craft_file(self):
        implementer = (CONTENT / "agents" / "pegasus-implementer.md").read_text(encoding="utf-8")
        self.assertIn("{{skills_root}}/_shared/implementation-craft.md", implementer)


class StrictTddResolutionTest(unittest.TestCase):
    """Slice (d): how any agent knows whether Strict TDD Mode is on, read from
    one owner. Every check pins the clause as written and closes the world
    around it: an inverted, reworded, passive or doubly negated clause fails,
    and so does any new sentence on the same subject."""

    def setUp(self):
        self.craft = CRAFT.read_text(encoding="utf-8")
        self.flat = " ".join(self.craft.split())

    def rule_section(self) -> str:
        self.assertIn(RULE_HEADING, self.craft)
        return self.craft.split(RULE_HEADING, 1)[1].split("\n### ", 1)[0]

    def test_the_rule_comes_before_the_hard_gate(self):
        self.assertLess(self.craft.index(RULE_HEADING), self.craft.index("### Strict TDD Hard Gate"))

    def test_the_order_is_marker_then_project_flag_then_runner(self):
        steps = re.findall(r"^(\d+)\. \*\*([^*]+)\*\*", self.rule_section(), re.MULTILINE)
        self.assertEqual(steps, [(str(number), lead) for number, lead in enumerate(RULE_STEPS, start=1)])

    def test_the_rule_sentences_are_exactly_the_pinned_ones(self):
        found = {unit for unit in units_of(self.craft) if CRAFT_RULE_SUBJECT.search(unit)}
        self.assertEqual(found, set(CRAFT_RULE_SENTENCES))

    def test_each_pinned_clause_is_there_exactly_once(self):
        for sentence in CRAFT_RULE_SENTENCES:
            with self.subTest(sentence=sentence):
                self.assertEqual(self.flat.count(sentence), 1)

    def test_the_marker_spellings_are_literals_in_the_rule(self):
        for spelling in ("`Strict TDD Mode: enabled`", "`Strict TDD Mode: disabled`", "`**Strict TDD Mode**: enabled`"):
            with self.subTest(spelling=spelling):
                self.assertIn(spelling, self.rule_section())

    def test_no_shipped_file_carries_a_marker_line(self):
        """Pegasus never decides the mode for the person: a bare marker line
        in anything it ships would."""
        offenders = [
            f"{path.relative_to(CONTENT).as_posix()}:{number}"
            for path in content_files()
            for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1)
            if any(BARE_MARKER.match(candidate) for candidate in marker_candidates(line))
        ]
        self.assertEqual(offenders, [])

    def test_the_marker_spelling_appears_only_where_pinned(self):
        found = {}
        for path in content_files():
            count = len(MARKER_MENTION.findall(path.read_text(encoding="utf-8", errors="replace")))
            if count:
                found[path] = count
        self.assertEqual(found, MARKER_MENTIONS)

    def test_each_reader_resolves_the_mode_only_in_its_pinned_units(self):
        for reader, pinned in READER_UNITS.items():
            with self.subTest(reader=reader.relative_to(SKILLS).as_posix()):
                found = {
                    unit
                    for unit in units_of(reader.read_text(encoding="utf-8"))
                    if READER_SUBJECT_MODE.search(unit) and READER_SUBJECT_RESOLUTION.search(unit)
                }
                self.assertEqual(found, set(pinned))

    def test_a_brief_without_a_recognized_spelling_falls_back_to_the_rule(self):
        """The compatibility clause, said once, by the owner: an old phrase
        from an orchestrator outside Pegasus means the rule decides, never a
        silent standard mode."""
        self.assertEqual(content_occurrences("never silently as standard mode"), [CRAFT])

    def test_the_dead_phrase_is_gone_from_the_shipped_tree(self):
        self.assertEqual(content_occurrences(DEAD_TDD_PHRASE), [])

    def test_sdd_init_still_writes_the_project_flag(self):
        details = (SKILLS / "sdd-init" / "references" / "init-details.md").read_text(encoding="utf-8")
        self.assertIn("`config.yaml` should include concise context, `strict_tdd`", details)
        self.assertIn("mem_save title/topic_key: sdd/{project}/testing-capabilities", details)


class StrictTddTravelsInTheBriefTest(unittest.TestCase):
    """Slice (d5): resolved once per session, sent in every implementation
    brief -- by the preflight in SDD and by the procedure in FTD -- and
    resolved by the teaching voice in its own session. Closed world: the
    pinned sentences, each exactly once, and nothing else on the subject in
    those files."""

    def flat(self, path: Path) -> str:
        return " ".join(path.read_text(encoding="utf-8").split())

    def test_the_preflight_sends_the_mode_beside_the_artifact_store(self):
        flat = self.flat(PREFLIGHT)
        self.assertEqual(flat.count(PREFLIGHT_BRIEF), 1)
        store = flat.index("Pass the resolved value to every sub-agent launch as `Artifact store mode`")
        self.assertLess(store, flat.index(PREFLIGHT_BRIEF))
        self.assertLess(flat.index(PREFLIGHT_BRIEF), flat.index("### 3. Chained PR strategy"))

    def test_the_procedure_sends_the_mode_in_every_implementation_brief(self):
        self.assertEqual(self.flat(PROCEDURE).count(PROCEDURE_BRIEF), 1)

    def test_king_resolves_the_mode_in_its_own_session_through_the_craft(self):
        rules = KING.read_text(encoding="utf-8").split("\n## Rules\n", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(" ".join(rules.split()).count(KING_TDD), 1)
        self.assertIn("{{skills_root}}/_shared/implementation-craft.md", KING_TDD)
        self.assertNotIn("ftd-procedure.md", KING.read_text(encoding="utf-8"))

    def test_the_brief_carries_the_marker_spelling_as_a_template(self):
        for sentence in (PREFLIGHT_BRIEF, PROCEDURE_BRIEF):
            with self.subTest(sentence=sentence[:40]):
                self.assertIn(BRIEF_TEMPLATE, sentence)
                self.assertIn(RULE_POINTER, sentence)

    def test_nothing_else_in_those_files_speaks_of_strict_tdd(self):
        for path, pinned in TDD_UNITS.items():
            with self.subTest(file=path.relative_to(CONTENT).as_posix()):
                found = {unit for unit in units_of(path.read_text(encoding="utf-8")) if TDD_SUBJECT.search(unit)}
                self.assertEqual(found, set(pinned))


class CraftOwnsNoPhaseEnvelopeTest(unittest.TestCase):
    """A craft file owns the shape of a good report; a phase skill owns the
    envelope its phase must emit.

    `exploration-craft.md` used to reproduce the literal heading
    `## Exploration: {topic}` inside its `## Report Shape` fence -- the exact
    string a phase-less specialist is forbidden to emit -- so `pegasus-explorer`
    was pointed at a ready-made template of the one thing it may not produce.
    The agent body's prose mitigation ("borrow the sections that fit") is
    advisory and untestable; this is the fact instead.

    What is forbidden is REPRODUCING the envelope as a heading -- a line that
    starts with `## ` and carries the marker -- not mentioning it. The
    distinction is load-bearing and it is why `verification-craft.md` passes:
    its `## Output Contract` says "Return `## Verification Report` with
    change/subject, mode, ..." inline in prose. Naming the output contract is
    exactly what a craft file should do; handing over a heading to copy is not.
    """

    def craft_files(self) -> list[Path]:
        return sorted(SKILLS.glob("_shared/*-craft.md"))

    def test_the_craft_files_are_found(self):
        """Without this the scan below would pass by finding nothing."""
        self.assertEqual(
            [path.name for path in self.craft_files()],
            ["exploration-craft.md", "implementation-craft.md", "verification-craft.md"],
        )

    def test_the_forbidden_set_is_derived_and_non_empty(self):
        self.assertTrue(ENVELOPE_HEADINGS, "no heading-shaped marker was derived")
        self.assertIn("## Exploration: {topic}", ENVELOPE_HEADINGS)
        self.assertIn("## Verification Report", ENVELOPE_HEADINGS)

    def test_no_craft_file_reproduces_a_phase_envelope_heading(self):
        for path in self.craft_files():
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip().startswith("## "):
                    continue
                for heading in ENVELOPE_HEADINGS:
                    if heading in line:
                        self.fail(f"{path.name}:{number} reproduces the phase envelope {heading!r}")

    def test_the_phase_skill_still_owns_the_envelope_it_must_emit(self):
        """Moved, not deleted: `sdd-explore` emits exactly the envelope it
        emitted before this change."""
        text = (SKILLS / "sdd-explore" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Exploration: {topic}", text)

    def test_the_craft_still_owns_the_sections_that_report_carries(self):
        """The requirement moved house; it did not evaporate."""
        text = (SKILLS / "_shared" / "exploration-craft.md").read_text(encoding="utf-8")
        for section in ("Current State", "Affected Areas", "Approaches", "Recommendation", "Risks"):
            with self.subTest(section=section):
                self.assertIn(section, text)


if __name__ == "__main__":
    unittest.main()
