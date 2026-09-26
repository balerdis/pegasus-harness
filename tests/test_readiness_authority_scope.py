"""`sdd-verify`'s readiness-authority claim is scoped to the SDD archive gate.

`sdd-verify` used to describe itself as Pegasus's "sole readiness authority for
executable and configuration changes" -- wording broad enough to read as
authority over every change anywhere, which forced anyone who only wanted a
verification run to enter the whole SDD flow to reach it. What the claim
actually gates is narrower: `sdd-archive` may run only on a current
verify-report with no critical findings. The claim is rewritten to say that
scope out loud, and this guard keeps a future agent body from re-widening it
by making the same broad claim again.

This guard used to be a word bag. It asserted `"archive" in text.lower()` over
the whole file, which an adversarial review defeated by reverting the claim
sentence to its pre-fix, un-scoped form -- "sole authority for declaring that an
executable or configuration change is ready" -- and appending an unrelated
parenthetical, "(An archive follows once a change is ready.)", purely to keep
the word present somewhere. All three tests stayed green while the fix they
exist for was fully undone.

The guard now holds the FACT instead: it locates the sentence that MAKES the
claim and checks THAT sentence names the archive scope. A word anywhere else in
the file is no longer an answer, and neither is the old `assertNotIn` on one
exact phrase -- the reviewer's wording ("an executable or configuration change")
slipped past it by changing a conjunction and a plural.

`GuardIsNotAWordBagTest` below runs the reviewer's exact mutation through this
module's own helper, so the weakening cannot be reintroduced without a test
failing.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

AGENTS = Path(__file__).resolve().parents[1] / "src" / "pegasus" / "content" / "agents"

#: A self-declared "I am THE authority" claim, worded loosely enough to catch a
#: future agent phrasing it differently while still claiming the same thing:
#: "sole" -- or "only", "final", "ultimate", "exclusive", "single", "the one"
#: -- within a short distance of "authority".
AUTHORITY_CLAIM = re.compile(
    r"\b(?:sole|only|final|ultimate|exclusive|single|the one)\b.{0,60}\bauthority\b", re.IGNORECASE | re.DOTALL
)

#: The scope the claim is allowed to have: the SDD archive gate.
ARCHIVE_SCOPE = re.compile(r"\barchive\b", re.IGNORECASE)

#: The scope it must not go back to. Matched as word classes rather than as one
#: exact phrase: the review's revert said "an executable or configuration
#: change", which an `assertNotIn("executable and configuration changes")` never
#: saw. Either word inside a claim sentence means the claim is about a class of
#: change rather than about the archive gate.
CHANGE_CLASS_SCOPE = re.compile(r"\b(executable|configuration)\b", re.IGNORECASE)

#: The two files entitled to make the claim at all.
OWNERS = ("sdd-verify.md", "pegasus-orchestrator.md")


def claim_units(text: str) -> list[str]:
    """Every sentence-like unit of an agent file that makes the authority claim.

    Front matter is split per line rather than per sentence: its lines are
    independent `key: value` declarations, and joining them would let a scope
    word from a neighbouring key stand in for one the claim itself never says.
    The body is unwrapped paragraph by paragraph first -- a claim wrapped across
    two source lines is one sentence, and splitting on newlines would cut it in
    half and lose whichever half carried the scope.
    """
    parts = text.split("---\n", 2)
    front, body = (parts[1], parts[2]) if len(parts) == 3 else ("", text)
    units = [line for line in front.splitlines() if line.strip()]
    for paragraph in re.split(r"\n\s*\n", body):
        joined = " ".join(paragraph.split())
        units += [piece for piece in re.split(r"(?<=\.)\s+", joined) if piece.strip()]
    return [unit for unit in units if AUTHORITY_CLAIM.search(unit)]


def claims_by_file() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in sorted(AGENTS.glob("*.md")):
        units = claim_units(path.read_text(encoding="utf-8"))
        if units:
            found[path.name] = units
    return found


class ReadinessAuthorityScopeTest(unittest.TestCase):
    def test_sdd_verify_actually_makes_the_claim(self):
        """Non-vacuity: every assertion below quantifies over the claims found,
        so a file that made none would satisfy all of them."""
        self.assertTrue(claim_units((AGENTS / "sdd-verify.md").read_text(encoding="utf-8")))

    def test_the_orchestrator_actually_makes_the_claim(self):
        self.assertTrue(
            claim_units((AGENTS / "pegasus-orchestrator.md").read_text(encoding="utf-8"))
        )

    def test_every_claim_sentence_names_the_archive_scope_itself(self):
        """The fix `29f22c1` landed, held where it was made. A word elsewhere in
        the file is not this sentence saying what it governs."""
        for name, units in claims_by_file().items():
            for unit in units:
                with self.subTest(agent=name, claim=unit):
                    self.assertRegex(unit, ARCHIVE_SCOPE)

    def test_no_claim_sentence_reverts_to_a_class_of_change(self):
        """The wording the fix replaced, matched by word class rather than by
        one exact phrase."""
        for name, units in claims_by_file().items():
            for unit in units:
                with self.subTest(agent=name, claim=unit):
                    self.assertNotRegex(unit, CHANGE_CLASS_SCOPE)

    def test_only_sdd_verify_and_the_orchestrator_make_the_claim(self):
        found = claims_by_file()
        self.assertEqual(
            set(found),
            set(OWNERS),
            f"a readiness-authority claim was found outside its owner: {found}",
        )


class GuardIsNotAWordBagTest(unittest.TestCase):
    """The review's own mutation, run through this module's helper.

    Kept as a fixture rather than as a mutation of the shipped file so the
    weakening this guard suffered once cannot be reintroduced silently: if
    someone widens the checks back to a whole-file word search, these fail.
    """

    #: Verbatim from the adversarial review: the claim reverts to its pre-fix
    #: scope, and an unrelated parenthetical keeps the word "archive" in the
    #: file so a word-bag guard stays green.
    REVERTED = (
        "---\n"
        "name: sdd-verify\n"
        "description: Sole authority for declaring an SDD change ready to archive\n"
        "---\n\n"
        "# SDD Verify\n\n"
        "You are Pegasus's sole authority for declaring that an executable or\n"
        "configuration change is ready. (An archive follows once a change is ready.)\n"
    )

    def setUp(self):
        self.units = claim_units(self.REVERTED)

    def test_the_reverted_claim_is_located_as_a_claim(self):
        self.assertTrue(self.units)

    def test_the_word_elsewhere_in_the_file_does_not_satisfy_the_scope_check(self):
        body_claims = [unit for unit in self.units if not unit.startswith("description:")]
        self.assertTrue(body_claims, "the reverted body sentence was not located")
        for unit in body_claims:
            with self.subTest(claim=unit):
                self.assertNotRegex(unit, ARCHIVE_SCOPE)

    def test_the_reverted_wording_is_caught_as_a_class_of_change(self):
        self.assertTrue(any(CHANGE_CLASS_SCOPE.search(unit) for unit in self.units))

    def test_a_claim_wrapped_across_source_lines_is_read_as_one_sentence(self):
        """The reverted claim above wraps after "or". Splitting on newlines
        would hand the scope check half a sentence and pass it."""
        self.assertTrue(any("executable or configuration change" in unit for unit in self.units))


if __name__ == "__main__":
    unittest.main()
