"""The parallel-delivery procedure: how a coordinator delivers several
independent units at once, read only when a fan-out has writers.

`_shared/sub-delegation-criterion.md` decides whether to fan out and carries
the one pointer; `_shared/parallel-delivery.md` says how it runs. It stays
lazy and dense, and it points at the owners it depends on.

Where a check guards a precise instruction, it pins the clause as written and
requires it exactly once. No negation classifier is used: a pinned clause
fails on any rewording, which is the point.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from test_flow_routing import sections
from test_ftd_procedure import always_on_bodies, collapsed, content_files_containing
from test_readiness_authority_scope import AUTHORITY_CLAIM

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "src" / "pegasus" / "content"
SHARED = CONTENT / "skills" / "_shared"
PROCEDURE = SHARED / "parallel-delivery.md"
CRITERION = SHARED / "sub-delegation-criterion.md"
PROCEDURE_NAME = PROCEDURE.name

#: Measured words when set (whole file, no front matter), plus nothing: any
#: growth earns a deliberate bump, never a reflow.
PARALLEL_DELIVERY_WORD_CEILING = 718

WORKTREE_ADD = "`git worktree add -b <branch> <path> <base>`"
WORKTREE_PATH = (
    "`${XDG_STATE_HOME:-$HOME/.local/state}/agent-worktrees/<repo-name>-<short hash of the toplevel path>"
    "/<run-id>/<unit>`"
)
PRUNE = "Run `git worktree prune` at the start of every run."
NO_FLOOR = "Never put a worktree under a directory the deny floor names, and never copy a sensitive file into one."
HOT_DOCUMENTS = (
    "The coordinator owns the shared documents: the project's decision or architecture document, its "
    "release notes, and the FTD record if one exists. Workers never edit them; each returns a "
    "paste-ready paragraph for the coordinator to integrate."
)
STRICT_DISJOINT = "Units are strictly file-disjoint: anything two units would share goes to exactly one of them."
ONE_MESSAGE = "**Launch everything in one message.** Read-only research units go in the same message, with no worktree."
BRIEF_COMMIT = "one local commit, no push, no AI or tool attribution"
BRIEF_SUITE = "run the project's test suite with its output redirected to a file, never piped and never backgrounded"
BRIEF_REPORT = (
    "a fixed report: branch and commit, files changed, tests and their result, the paste-ready paragraph "
    "for the coordinator's documents, and anything found but not fixed"
)
PROGRESS = (
    "When the CLI delivers results one at a time, give the person one short line per finished unit, then "
    "the consolidated report at the end. When all arrive together, give only the consolidated report."
)
ISOLATION = "Before integrating, confirm that `git status --porcelain` in the main checkout shows nothing the units wrote."
CHERRY = "Then confirm with `git cherry <main> <branch>` that each commit is in;"
CLEANUP = "only after that run `git worktree remove`, `git branch -D` and `git worktree prune`."
SUITE_RUN = (
    "One full run on the integrated tree, by the coordinator: a single command with its output redirected "
    "to a file, then read the tail."
)
REVIEW_SCOPE = "A review here is evidence, not a readiness verdict for an SDD change: that stays with `sdd-verify`."
OUTWARD = (
    "It asks before any outward action: push, publish, release. Only with the person's yes does it do that "
    "action, and afterwards it verifies what went out"
)
NOT_A_LICENCE = (
    "A single small change stays inline under the Direct Work Threshold, and this procedure is never a "
    "reason to delegate work that would cost less to do."
)

#: Appears in the procedure alone.
PROCEDURE_NEEDLE = "Fresh-context review.** One reviewer per repository"


def procedure_text() -> str:
    return PROCEDURE.read_text(encoding="utf-8")


class ProcedureCase(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PROCEDURE.is_file(), f"{PROCEDURE} does not exist")
        self.text = procedure_text()
        self.flat = collapsed(self.text)
        self.sections = sections(self.text)


class ConventionsTest(ProcedureCase):
    def test_house_shape(self):
        self.assertIn("Scope", self.sections)
        self.assertIn("Authority", self.sections)
        self.assertIn("Procedure", self.sections)

    def test_it_fails_open(self):
        self.assertIn("missing or unreadable", collapsed(self.sections.get("Fail-open", "")))

    def test_it_points_at_owners_that_resolve(self):
        scope_and_authority = self.sections["Scope"] + self.sections["Authority"]
        for owner in (
            "_shared/sub-delegation-criterion.md",
            "_shared/implementation-craft.md",
            "_shared/verification-craft.md",
        ):
            with self.subTest(owner=owner):
                self.assertIn(owner, scope_and_authority)
                self.assertTrue((SHARED.parent / owner).is_file(), f"{owner} does not resolve")

    def test_it_claims_no_authority_over_readiness(self):
        self.assertIsNone(AUTHORITY_CLAIM.search(self.text))
        self.assertEqual(self.flat.count(REVIEW_SCOPE), 1)

    def test_it_is_not_an_ftd_rule_and_names_no_program(self):
        self.assertIn("This is not an FTD rule.", self.flat)
        self.assertNotIn("{{", re.sub(r"\{\{skills_root\}\}", "", self.text))

    def test_it_stays_within_its_word_ceiling(self):
        self.assertLessEqual(len(self.text.split()), PARALLEL_DELIVERY_WORD_CEILING)


class TwelveStepsTest(ProcedureCase):
    def test_the_procedure_has_twelve_numbered_steps_in_order(self):
        body = self.sections.get("Procedure", "")
        numbers = [int(m.group(1)) for m in re.finditer(r"^(\d+)\. ", body, re.MULTILINE)]
        self.assertEqual(numbers, list(range(1, 13)))

    def test_the_steps_open_with_their_names_in_order(self):
        body = self.sections.get("Procedure", "")
        names = re.findall(r"^\d+\. \*\*([^*]+?)\.?\*\*", body, re.MULTILINE)
        self.assertEqual(
            names,
            [
                "Triage",
                "Partition by file ownership",
                "Base and merge plan",
                "Create the worktrees",
                "Launch everything in one message",
                "While units run",
                "Isolation check",
                "Integrate",
                "The coordinator's own suite run",
                "Fresh-context review",
                "One fix-up writer",
                "Close",
            ],
        )

    def test_triage_has_the_four_buckets(self):
        for bucket in ("doable now", "waiting on the person", "large features to decide separately", "research only"):
            with self.subTest(bucket=bucket):
                self.assertIn(bucket, self.flat)


class PinnedClausesTest(ProcedureCase):
    def test_each_pinned_clause_appears_exactly_once(self):
        for name, clause in (
            ("worktree add", WORKTREE_ADD),
            ("worktree path", WORKTREE_PATH),
            ("prune", PRUNE),
            ("deny floor and sensitive files", NO_FLOOR),
            ("hot documents", HOT_DOCUMENTS),
            ("strict disjoint", STRICT_DISJOINT),
            ("one message", ONE_MESSAGE),
            ("brief commit", BRIEF_COMMIT),
            ("brief suite", BRIEF_SUITE),
            ("brief report", BRIEF_REPORT),
            ("progress", PROGRESS),
            ("isolation", ISOLATION),
            ("cherry", CHERRY),
            ("cleanup", CLEANUP),
            ("suite run", SUITE_RUN),
            ("outward", OUTWARD),
            ("not a licence", NOT_A_LICENCE),
        ):
            with self.subTest(clause=name):
                self.assertEqual(self.flat.count(clause), 1, clause)

    def test_the_worktree_path_is_outside_the_repository_and_names_no_product(self):
        self.assertTrue(WORKTREE_PATH.startswith("`${XDG_STATE_HOME"))
        self.assertNotIn("pegasus", self.flat.lower())
        self.assertNotIn("opencode", self.flat.lower())
        self.assertNotIn("claude", self.flat.lower())

    def test_the_brief_carries_the_path_and_absolute_path_rules(self):
        for needle in (
            "the absolute worktree path",
            "every shell command runs in that path (workdir or `cd`) and every file path is absolute",
            "never touch the main checkout",
        ):
            with self.subTest(needle=needle):
                self.assertEqual(self.flat.count(needle), 1)

    def test_the_seam_cap_stays_the_criterions(self):
        self.assertIn("Keep the seam cap of the criterion file.", self.flat)
        self.assertNotIn("five or six", self.flat)


class ProcedureIsLazyTest(unittest.TestCase):
    """Closed world: the procedure is reached through the criterion only."""

    def test_no_always_on_body_names_the_procedure(self):
        for key, body in always_on_bodies().items():
            with self.subTest(body=key):
                self.assertNotIn(PROCEDURE_NAME, body)

    def test_the_only_content_file_naming_it_is_the_criterion(self):
        self.assertEqual(content_files_containing(PROCEDURE_NAME), {CRITERION})

    def test_the_criterion_names_it_once_in_writers_in_parallel(self):
        text = CRITERION.read_text(encoding="utf-8")
        self.assertEqual(text.count(PROCEDURE_NAME), 1)
        section = text.split("## Writers in parallel", 1)[1].split("\n## ", 1)[0]
        self.assertIn(PROCEDURE_NAME, section)

    def test_a_distinctive_phrase_lives_only_in_the_procedure(self):
        self.assertEqual(content_files_containing(PROCEDURE_NEEDLE), {PROCEDURE})


if __name__ == "__main__":
    unittest.main()
