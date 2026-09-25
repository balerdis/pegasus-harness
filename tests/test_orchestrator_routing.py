"""How the orchestrator decides: concurrently, at a cost, and only sometimes SDD.

Three reported frictions, one file:

1.  Concurrency was never mentioned, so independent delegations went out one at
    a time and the person waited for each round trip. OpenCode dispatches every
    tool call in a single assistant response concurrently, with no limit, so the
    rule is a real capability rather than an aspiration.
2.  The threshold read as permission. The file opened by telling the agent to
    launch work through its delegation primitive, and "Narrating the Work"
    opened by calling delegation the visible proof of coordinating -- nothing
    named what delegating something small COSTS. The observed behaviour was that
    it delegated everything, trivia included.
3.  Nothing in the product owned whether a request IS an SDD request, so
    everything was routed into the SDD flow and a person who wanted one thing
    looked at was asked to run `sdd-init` and resolve preflight first.
    `_shared/flow-applicability.md` now owns that question -- which of four
    routes a request takes: a query, an L0 direct change, FTD or SDD -- and
    the orchestrator keeps the compact IF.

The assertions hold FACTS rather than proxies: the old framings must be gone
from the file that produced the behaviour (not merely balanced by new text
elsewhere), Gate 1's own wording must live in exactly one file across the whole
shipped tree, and the preflight gate must still be intact for work that IS SDD.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_flow_routing import (
    SDD_MEETS_FTD_STEMS,
    _DECISION_STEM,
    sdd_blocks,
    sdd_clauses,
    sdd_meets_a_decision,
    sdd_meets_ftd_stems,
)

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
AGENTS = CONTENT / "agents"
SKILLS = CONTENT / "skills"
SHARED = SKILLS / "_shared"

ORCHESTRATOR = AGENTS / "pegasus-orchestrator.md"
APPLICABILITY = SHARED / "flow-applicability.md"
KING_PEGASUS = AGENTS / "king-pegasus.md"
CRITERION = SHARED / "sub-delegation-criterion.md"

#: Gate 1's own wording. The orchestrator must point at it, never restate it.
GATE_1 = "can I write each part's brief without naming another part's result?"

#: The two sentences that framed delegation as permission and as visible proof
#: of coordinating. Their removal is the change; new text alongside them would
#: not have been one.
PERMISSION_FRAMINGS = (
    "Above the threshold below, launch the work through your runtime's native delegation primitive",
    "Delegation is the part of your job the user can actually see",
)

#: A distinctive instruction from the new shared file. Finding it in a second
#: place means the compact IF swallowed the HOW it was supposed to point at.
APPLICABILITY_NEEDLE = "Name the moment out loud, propose the switch, and resolve preflight then"

#: What the retired applicability file listed as signs that work is SDD,
#: word for word. Under v7 each of them is FTD unless a reviewable contract
#: says otherwise, so the rename inverts them rather than keeping them.
RETIRED_SDD_SIGNALS = (
    "an approach worth arguing, trade-offs",
    "across several sessions",
    "A written record has to survive the session",
)

#: Word count, not line count. A line ceiling was proven defeatable in this
#: repository: hand-wrapping a bullet across three physical lines and then
#: collapsing it back to one, while ALSO adding new prose, took this very file
#: from 103 lines to 101 -- the guard's own name calls itself "traded text for
#: text" and it passed while text was added and none removed, because
#: rewrapping moves lines without moving words. Word count cannot be bought by
#: reflow: joining or splitting physical lines never changes how many
#: whitespace-separated tokens the file holds (see
#: `WordCeilingIsReformatProofTest` below, which proves this on a rewrapped
#: copy rather than asserting it).
#:
#: 1327 words when the ceiling was set; 1398 after v7 rewrote the routing
#: section text for text, which leaves the margin slice (c) needs. The
#: ceiling carries the same proportional headroom the retired line ceiling
#: did (104 / 97 ~= 1.072x), rounded down: 1327 * 1.07 ~= 1420. That is
#: room for a short new sentence, not a second section -- a change that
#: needs more than that earns a deliberate ceiling bump, not a reflow.
ORCHESTRATOR_WORD_CEILING = 1420

#: What every ceiling below measures: the WHOLE file, as `wc -w` and
#: `len(text.split())` count it -- front matter included -- exactly as
#: `ORCHESTRATOR_WORD_CEILING` above always has, even where prose calls the
#: file "the body". Subtracting the front matter re-derives a number these
#: tests never check. Each ceiling is the count measured when it was set plus
#: only the words already reserved for additions the v7 plan names: no
#: round-number slack, so drift beyond those additions is caught.
#:
#: `flow-applicability.md`: 1026 words measured after v7 a3 (it has no front
#: matter, so here whole file and prose agree). Reserved: 35 words for b5's
#: pointer to `_shared/ftd-procedure.md` at the exit of the FTD route clause --
#: one sentence naming the procedure (record, evidence, close), that it is read
#: only on that route, and its fail-open, estimated from a draft of that
#: sentence. 1026 + 35 = 1061. Anything past that pointer earns a deliberate
#: bump, never a reflow.
FLOW_APPLICABILITY_WORD_CEILING = 1061

#: `king-pegasus.md`: 715 words measured after v7 a5 -- 33 of them front
#: matter, its two `---` delimiters included. Reserved, estimated from a draft
#: of each sentence: 43 words for c3 -- about 30 for the readiness wording
#: beside "Close the loop you open" (outside SDD the readiness call is this
#: voice's own, made from what it observed, and signing what it wrote is said
#: as such) and about 13 for the rule that on FTD it keeps the record itself,
#: reached through `flow-applicability.md`; and 25 words for d5 -- naming
#: `_shared/implementation-craft.md` and resolving Strict TDD Mode once in its
#: own session, with that pointer's fail-open. 715 + 43 + 25 = 783.
KING_PEGASUS_WORD_CEILING = 783

#: The bodies a word ceiling guards, each with the ceiling it answers to.
CEILINGED_BODIES = (
    (ORCHESTRATOR, ORCHESTRATOR_WORD_CEILING),
    (APPLICABILITY, FLOW_APPLICABILITY_WORD_CEILING),
    (KING_PEGASUS, KING_PEGASUS_WORD_CEILING),
)


def rewrap_preserving_words(text: str) -> str:
    """Reflow `text` without adding or removing a single word.

    Joins any run of continuation lines (plain prose that wraps across
    physical lines) into one line per paragraph or bullet, so a hand-wrapped
    sentence becomes a single long line -- the exact transform that shrank
    this file's line count in the incident above. Headings, front-matter
    delimiters, and table rows are left alone, since folding them together
    would garble structure rather than merely rewrap prose; every word inside
    them is still preserved untouched. Blank lines are kept as paragraph
    breaks. This is a reflow, not a summary: no word is added, dropped, or
    reordered.
    """
    lines = text.split("\n")
    out: list[str] = []
    buffer: list[str] = []

    def flush() -> None:
        if buffer:
            out.append(" ".join(" ".join(buffer).split()))
            buffer.clear()

    for line in lines:
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#") or stripped.startswith("|") or stripped == "---":
            flush()
            out.append(line)
        else:
            buffer.append(stripped)
    flush()
    return "\n".join(out)


def content_documents() -> dict[Path, str]:
    return {
        path: path.read_text(encoding="utf-8")
        for path in sorted([*SKILLS.rglob("*.md"), *AGENTS.rglob("*.md")])
        if "__pycache__" not in path.parts
    }


def occurrences(needle: str) -> list[Path]:
    return [path for path, text in content_documents().items() if needle in text]


class ConcurrencyTest(unittest.TestCase):
    def setUp(self):
        self.text = ORCHESTRATOR.read_text(encoding="utf-8")

    def test_the_orchestrator_names_launching_in_one_response(self):
        """The rule has to name the mechanism, not merely praise parallelism:
        what makes two delegations concurrent is landing in the SAME response."""
        lowered = self.text.lower()
        self.assertIn("same response", lowered)
        self.assertIn("independent", lowered)

    def test_it_points_at_gate_1_for_what_independent_means(self):
        self.assertIn("Gate 1", self.text)
        self.assertIn("_shared/sub-delegation-criterion.md", self.text)

    def test_gate_1_is_pointed_at_rather_than_restated(self):
        """The fact, over the whole shipped tree: Gate 1's wording lives in the
        file that owns it and nowhere else."""
        self.assertEqual(occurrences(GATE_1), [CRITERION])


class ThresholdReadsAsCostTest(unittest.TestCase):
    def setUp(self):
        self.text = ORCHESTRATOR.read_text(encoding="utf-8")

    def test_the_permission_framings_are_gone(self):
        for framing in PERMISSION_FRAMINGS:
            with self.subTest(framing=framing):
                self.assertNotIn(framing, self.text)

    def test_the_cost_of_a_delegation_is_named(self):
        """A brief to write, a round trip, a report to read, a person waiting --
        the four the old framing left unsaid."""
        lowered = self.text.lower()
        for cost in ("a brief to write", "a round trip", "a report to read", "waiting"):
            with self.subTest(cost=cost):
                self.assertIn(cost, lowered)

    def test_the_default_is_doing_it_yourself(self):
        self.assertIn("inflate your own context", self.text)


class FlowApplicabilityTest(unittest.TestCase):
    def test_the_shared_file_exists_and_follows_the_house_conventions(self):
        self.assertTrue(APPLICABILITY.is_file())
        text = APPLICABILITY.read_text(encoding="utf-8")
        self.assertIn("## Scope", text)
        self.assertIn("## Authority", text)

    def test_the_shared_file_owns_the_cases_the_compact_if_does_not(self):
        text = APPLICABILITY.read_text(encoding="utf-8")
        lowered = text.lower()
        self.assertIn("ambiguous", lowered)
        self.assertIn("mid-flight", lowered)
        self.assertIn(APPLICABILITY_NEEDLE, text)

    def test_the_shared_file_fails_open(self):
        text = APPLICABILITY.read_text(encoding="utf-8")
        self.assertIn("missing or unreadable", text)

    def test_the_shared_file_points_instead_of_restating_preflight(self):
        """Preflight's own owner keeps owning WHAT preflight is and WHEN it
        runs; this file only decides which route the request takes."""
        text = APPLICABILITY.read_text(encoding="utf-8")
        self.assertIn("_shared/sdd-session-preflight.md", text)
        self.assertNotIn("Execution mode", text)
        self.assertNotIn("Review budget", text)

    def test_the_retired_sdd_signals_are_gone(self):
        collapsed = " ".join(APPLICABILITY.read_text(encoding="utf-8").split())
        for signal in RETIRED_SDD_SIGNALS:
            with self.subTest(signal=signal):
                self.assertNotIn(signal, collapsed)

    def test_the_scan_sees_the_sdd_route_and_steps(self):
        """Guards the two checks below from passing vacuously: the blocks they
        scan must at least include the SDD route and the SDD steps of the
        decision order."""
        text = APPLICABILITY.read_text(encoding="utf-8")
        clauses = sdd_clauses(text)
        self.assertGreaterEqual(len(clauses), 3, clauses)
        self.assertLessEqual(set(clauses), set(sdd_blocks(text)))

    def test_sdd_meets_what_v7_moved_to_ftd_only_in_the_pinned_blocks(self):
        """Closed world, not a negation classifier: in the four decision
        sections, the blocks where SDD co-occurs with a trade-off, a decision,
        a session, a record, durability or continuity must be exactly the
        pinned ones, as written. "It is not optional: a trade-off is SDD" fails
        here however it is negated, phrased or split."""
        found = sdd_meets_ftd_stems(APPLICABILITY.read_text(encoding="utf-8"))
        self.assertEqual(found, set(SDD_MEETS_FTD_STEMS))

    def test_a_decision_goes_to_sdd_only_when_someone_absent_reviews_it(self):
        """The same closed world, seen from decisions: SDD meets a decision only
        in the pinned blocks -- the reviewable-contract definition, and the
        blocks that send a decision alone to FTD."""
        found = sdd_meets_a_decision(APPLICABILITY.read_text(encoding="utf-8"))
        self.assertEqual(found, {block for block in SDD_MEETS_FTD_STEMS if _DECISION_STEM.search(block)})

    def test_the_orchestrator_carries_the_compact_if(self):
        text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.assertIn("_shared/flow-applicability.md", text)
        lowered = text.lower()
        self.assertIn("not every request is sdd", lowered)

    def test_the_orchestrator_no_longer_says_a_record_outliving_the_session_is_sdd(self):
        collapsed = " ".join(ORCHESTRATOR.read_text(encoding="utf-8").split())
        self.assertNotIn("a record outliving the session", collapsed)
        for sentence in re.split(r"(?<=[.!?])\s+", collapsed):
            if "SDD" in sentence:
                for stem in ("outliv", "surviv"):
                    with self.subTest(sentence=sentence, stem=stem):
                        self.assertNotIn(stem, sentence.lower())

    def test_the_orchestrator_does_not_swallow_the_how(self):
        self.assertEqual(occurrences(APPLICABILITY_NEEDLE), [APPLICABILITY])

    def test_the_non_sdd_path_names_the_three_specialists(self):
        """Scanned below the front matter on purpose: `may_delegate_to` already
        names all three, so a whole-file search would pass without the prose
        ever telling the agent where non-SDD work goes."""
        prose = ORCHESTRATOR.read_text(encoding="utf-8").split("---\n", 2)[2]
        for name in ("pegasus-explorer", "pegasus-verifier", "pegasus-implementer"):
            with self.subTest(agent=name):
                self.assertIn(name, prose)


class PreflightStaysStrictTest(unittest.TestCase):
    """What changes is that the gate stops firing for work that is not SDD --
    never that it got softer for work that is."""

    def setUp(self):
        self.text = ORCHESTRATOR.read_text(encoding="utf-8")

    def test_the_gate_still_stops_the_turn(self):
        self.assertIn("_shared/sdd-session-preflight.md", self.text)
        self.assertIn("and STOP", self.text)
        self.assertIn("Do not run the requested phase in the same turn", self.text)

    def test_the_gate_is_still_eager_for_a_natural_language_request(self):
        self.assertIn("a natural-language request never loads a command file", self.text)


class PersonaScopeNamesTheTerseExtremeTest(unittest.TestCase):
    """The Persona Scope bullet on briefs (line 96) already named every WARM
    failure -- persona, slang, CAPS, rhetorical questions. An observed real
    session failed the opposite way: a brief compressed until its grammar
    broke (`useramendment11068keepallsessions`). A model checking its own
    brief against the old list would have passed a brief in that shape. This
    pins the instruction that closes the gap (the actual prohibition, an
    imperative clause inside the sentence) separately from the diagnosis that
    merely explains why it matters, following the same lesson already learned
    for `sub-delegation-criterion.md`'s parallel-issuance section: a
    description is not an instruction."""

    def setUp(self):
        self.text = ORCHESTRATOR.read_text(encoding="utf-8")
        self.collapsed = " ".join(self.text.split())

    def test_pins_the_prohibition_not_only_its_diagnosis(self):
        """The actual instruction: no fusing words together to save tokens.
        Proven by deletion: removing only this clause and leaving the
        surrounding diagnosis intact must turn this assertion red while the
        diagnosis test below stays green."""
        self.assertIn("no words fused together to save tokens either", self.collapsed)

    def test_names_the_diagnosis_for_the_terse_extreme(self):
        self.assertIn(
            "a brief compressed until its grammar breaks is a brief its executor has to decompress "
            "first",
            self.collapsed,
        )

    def test_names_both_extremes_as_the_same_failure(self):
        self.assertIn("the terse extreme breaks the same contract as the warm one", self.collapsed)


class OrchestratorStaysSmallTest(unittest.TestCase):
    def test_the_body_traded_text_for_text(self):
        words = len(ORCHESTRATOR.read_text(encoding="utf-8").split())
        self.assertLessEqual(words, ORCHESTRATOR_WORD_CEILING, "the orchestrator body grew")


class FlowApplicabilityStaysSmallTest(unittest.TestCase):
    """The ladder is read whenever a route is not obvious; it must not grow into
    the manual of every flow. How FTD runs belongs to its own procedure."""

    def test_the_ladder_did_not_grow_in_hiding(self):
        words = len(APPLICABILITY.read_text(encoding="utf-8").split())
        self.assertLessEqual(words, FLOW_APPLICABILITY_WORD_CEILING, "flow-applicability.md grew")


class KingPegasusStaysSmallTest(unittest.TestCase):
    """An always-on body: every word is paid on every turn of the voice."""

    def test_the_teaching_voice_did_not_grow(self):
        words = len(KING_PEGASUS.read_text(encoding="utf-8").split())
        self.assertLessEqual(words, KING_PEGASUS_WORD_CEILING, "king-pegasus.md grew")


class WordCeilingIsReformatProofTest(unittest.TestCase):
    """The decisive guard: the measure must not move when only line breaks do.

    Rewraps each ceilinged body in memory -- the repository files are read and
    never written -- and asserts the word count this suite relies on is
    unchanged while the line count is, proving the incident in the comment
    above cannot recur under the new measure the way it did under the old one.
    """

    def test_rewrapping_moves_lines_but_not_words(self):
        for body, _ in CEILINGED_BODIES:
            with self.subTest(body=body.name):
                original = body.read_text(encoding="utf-8")
                rewrapped = rewrap_preserving_words(original)

                original_words = len(original.split())
                rewrapped_words = len(rewrapped.split())
                original_lines = len(original.splitlines())
                rewrapped_lines = len(rewrapped.splitlines())

                self.assertEqual(
                    original_words,
                    rewrapped_words,
                    "the rewrap changed the word count -- it is not a pure reflow",
                )
                self.assertNotEqual(
                    original_lines,
                    rewrapped_lines,
                    "the rewrap did not actually change the line layout -- the test proves nothing",
                )


if __name__ == "__main__":
    unittest.main()
