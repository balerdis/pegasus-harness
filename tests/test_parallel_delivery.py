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
#: growth earns a deliberate bump, never a reflow. 718 -> 1124 after the review
#: of the first version: minimum of two units, SDD scope, clean tree, the
#: run-id/branch/hash definitions, conflict abort, the worktree environment,
#: failed units, proportional review and the close ordering. 1124 -> 1333 after
#: the live run: `git -C` everywhere, the commit message read from a file outside
#: the worktree, tests added in the report, the ignored-files snapshot, unit
#: names, partial abort and the `--force` rule. 1333 -> 1517 after the third
#: live run: the readable-commands rule, the refusal rule, root, run-id and hash
#: as separate simple steps, the test-run rule, the three-step message file, the
#: tests output file and the schema copied verbatim into each brief. 1517 -> 1580
#: after the fourth live run: the review statement and the run-directory cleanup. 1580 -> 1606 after the
#: OpenCode live run: the cleanup as a concrete `rm -r` with the literal path. 1606 -> 1656 after the
#: final review: the conditional, guarded `rm -r` and the empty-HOME stop. 1656 -> 1760 after the
#: failure-path measurement: the conflict diagnosis, the absolute test command, the interrupted-run
#: recovery, the launched-unit cleanup condition and the `$VAR`/`cd` rule. 1760 -> 1860 after the
#: review of that rewording: the live-session guard, merge-base and `--ignored` in recovery, the neutral
#: test command with a pinned import root, and the pipeline allowance in the readable-commands rule.
PARALLEL_DELIVERY_WORD_CEILING = 1860

WORKTREE_ADD = "`git -C <main checkout> worktree add -b <branch> <path> <base>`"
WORKTREE_PATH = (
    "`<state>/agent-worktrees/<repo-name>-<short hash of the toplevel path>/<run-id>/<unit>`"
)
PRUNE = "Run `git -C <main checkout> worktree prune` at the start of every run;"
NO_FLOOR = "Never put a worktree under a directory the deny floor names, and never copy a sensitive file into one."
HOT_DOCUMENTS = (
    "The coordinator owns the shared documents: the project's decision or architecture document, its "
    "release notes, and the FTD record if one exists. Workers never edit them; each returns a "
    "paste-ready paragraph for the coordinator to integrate."
)
STRICT_DISJOINT = "Units are strictly file-disjoint: anything two units would share goes to exactly one of them."
ONE_MESSAGE = "**Launch everything in one message.** Read-only research units go in the same message, with no worktree."
BRIEF_COMMIT = "one local commit, no push, no AI or tool attribution"
BRIEF_SUITE = (
    "run the project's test suite with its output redirected to a file, never piped and never backgrounded, "
    "the file being `<root>/<run-id>/<unit>-tests.txt`"
)
BRIEF_REPORT = (
    "a fixed report: branch and commit, files changed, tests and their result, tests added, as a count, the "
    "paste-ready paragraph for the coordinator's documents, anything found but not fixed, and the commands "
    "refused, with the reason"
)
READABLE_RULE = (
    "No command, the coordinator's or a writer's, contains `$(...)`, `${...}` or a `$VAR`, and none uses `cd`: use "
    "git -C and absolute paths. Compute each value in its own command, a simple command or one pipeline of read-only filters, then write the "
    "literal result into the next command. Permission systems can only judge a command they can read."
)
REFUSAL_RULE = (
    "If a command is refused, the agent stops and reports which command was refused and why, and never works "
    "around a refusal. A writer's report lists its refusals, and so does the coordinator's."
)
VERBATIM_SCHEMA = (
    "The coordinator copies this report schema into each brief verbatim, including the paste-ready paragraph, "
    "and the two rules above, on readable commands and on refusals."
)
STATE_DIR = (
    "`<state>` is the output of `printenv XDG_STATE_HOME`; if that prints nothing, it is `<home>/.local/state`, "
    "with `<home>` from `printenv HOME`, and if that prints nothing too, it stops and asks the person for the state directory."
)
RUN_ID_STEPS = (
    "The run-id is the output of `date -u +%Y%m%dT%H%M%SZ` and the output of "
    "`head -c3 /dev/urandom | od -An -tx1`, run as two commands and joined by the coordinator with a hyphen, "
    "spaces removed; the branch is `<run-id>/<unit>`, so re-runs never collide."
)
HASH_STEPS = (
    "The short hash comes from `git -C <main checkout> rev-parse --show-toplevel`, then "
    "`printf %s <that path> | sha1sum`, keeping the first 8 characters."
)
LITERAL_ROOT = (
    "The root is then the literal path `<state>/agent-worktrees/<repo-name>-<short hash>`, and every later "
    "command carries the literal."
)
ONE_AT_A_TIME = "The coordinator assembles every value itself, one simple command at a time."
TEST_RUN_RULE = (
    "the test suite runs as the literal command with absolute paths into the unit's worktree, never "
    "relative to the shell's location, with the shell tool's working-directory parameter, if any, set to it and "
    "the import root pinned to it (a literal absolute `PYTHONPATH`-style value or the runner's root option), since "
    "an editable install or a `src` layout can import the main checkout's package; a writer that cannot pin it "
    "says so in its report"
)
MESSAGE_FILE_SEQUENCE = (
    "made in three steps: the message is written with the file-writing tool to `<root>/<run-id>/<unit>.msg`, "
    "outside the worktree; then `git -C <absolute worktree path> commit -F <that path>`; then the message file "
    "is removed; so the message text never reaches the command line"
)
PROGRESS = (
    "When the CLI delivers results one at a time, give the person one short line per finished unit, then "
    "the consolidated report at the end. When all arrive together, give only the consolidated report."
)
ISOLATION = (
    "Before integrating, confirm that `git -C <main checkout> status --porcelain` shows nothing the units wrote, "
    "and that `git -C <main checkout> status --porcelain --ignored` equals the one recorded at base time."
)
BASE_IGNORED = "Also record `git -C <main checkout> status --porcelain --ignored` now, for the isolation check."
COORDINATOR_GIT_C = "Every git command of the coordinator is `git -C <main checkout> ...`, never `cd` chained with git."
UNIT_NAMES = "Unit names are lowercase letters, digits and hyphens, so they are valid ref components."
BRIEF_GIT_C = "every git command is `git -C <absolute worktree path> ...` and never chains `cd` with git;"
PARTIAL_ABORT = (
    "Picks already integrated stay; the remaining worktrees stay in place, each reported with its path."
)
NO_FORCE = (
    "`worktree remove` refuses a worktree holding untracked files that are not ignored: never add `--force` "
    "without first listing what would be lost and having the person agree."
)
TESTS_ADDED_SUM = "adds up to the base count plus the units' reported tests added;"
CHERRY = "For a clean pick, confirm with `git -C <main checkout> cherry <integration branch> <branch>` that each commit is in;"
CLEANUP = (
    "Only after that run `git -C <main checkout> worktree remove`, `git -C <main checkout> branch -D` and "
    "`git -C <main checkout> worktree prune`."
)
MIN_TWO = (
    "It needs at least two genuinely independent writing units after triage; with fewer, it does not "
    "apply: return to the criterion's ordinary path."
)
SDD_SCOPE = "An SDD apply batch is not parallelised by this procedure: its task and progress artifacts are shared state."
CRIT_QUOTE = (
    "which keeps its general \"independently mergeable\" rule; this file is the how, and for a delivery "
    "run under it, units are strictly file-disjoint."
)
CLEAN_TREE = (
    "The integration branch's checkout must be clean (`git -C <main checkout> status --porcelain` prints nothing); if it is "
    "not, stop and ask the person, and never stash. Units branch from the recorded base, so they will not "
    "see uncommitted work: say so."
)
PRUNE_MEANING = "it drops only entries whose directory is gone."
ABORTED_RUN = (
    "After an interrupted run, find it with `git -C <main checkout> worktree list` and a listing of `<root>`. "
    "Remove nothing from a run this session did not start without the person's explicit yes, after showing what "
    "was found; a live session's fresh worktrees look the same. For each worktree check `git -C <worktree> "
    "status --porcelain --ignored` and `git -C <worktree> log --oneline <base>..HEAD`, with `<base>` from "
    "`git -C <main checkout> merge-base <integration branch> <unit branch>` or from the person, and ask about "
    "anything uncommitted, ignored or not integrated. Remove only a worktree with none of these "
    "(`worktree remove`, `branch -D`, `prune`), and `<root>/<run-id>` only when no worktree is left in it, under "
    "the step 8 cleanup guard."
)
WAVES = "With more units than the CLI's concurrency cap, run them in waves."
WORKTREE_ENV = (
    "A worktree has none of the main checkout's untracked or ignored files: dependency directories, build "
    "output, environment files. The writer never copies sensitive files; if the tests cannot run there it "
    "reports that instead of improvising, and if the repository has no test suite it says so."
)
HOOK_BLOCKED = (
    "If a commit hook, signing or a missing git identity blocks the commit, it reports that and leaves the "
    "change uncommitted in the worktree, never bypassing a hook."
)
WAIT_ALL = "In background delivery, wait until every unit has reported before integrating."
FAILED_UNIT = (
    "A unit that fails or returns nothing is reported as not delivered: integrate the rest, leave its "
    "worktree in place and give the person its path."
)
ABORT_CONFLICT = (
    "On a conflict run `git -C <main checkout> cherry-pick --abort`, then `git -C <main checkout> log --oneline "
    "<base>..HEAD`: a conflict means the partition was wrong or the integration branch moved since the base; "
    "say which, and stop, never resolving blind. The same message gives the path of every remaining worktree "
    "and of `<root>/<run-id>`."
)
VERIFY_BY_DIFF = (
    "if the person decides to resolve a conflict, verify that pick by diff instead, because `git cherry` "
    "prints `+` after it."
)
NO_SUITE = "without a test suite, skip the count check."
PROPORTIONAL = (
    "Proportional to the integrated diff's size and risk: a trivial diff needs no separate reviewer."
)
REVIEW_STATED = (
    "The report states whether a review ran; if none did, it says why: a trivial diff, and what made it "
    "trivial. A diff that adds new modules or new logic is not trivial."
)
RUN_DIR_CLEANUP = (
    "Only when every launched unit integrated, none failed or was aborted, every worktree and branch was removed, and `worktree prune` has run, and only after confirming that `<root>` (ending in `agent-worktrees/<repo-name>-<short hash>`) and the run-id are non-empty and exactly the recorded literals, run `rm -r <root>/<run-id>` with the literal path, never an expansion: the output files and the coordinator's own message files for fix-up commits live there, so they go with it. A unit held back at triage has nothing in the run directory and does not block it. Otherwise leave the run directory in place and name its path in the report."
)
NO_FIXUP = "with no confirmed finding there is no fix-up writer."
CLOSE_ORDER = (
    "The coordinator integrates the paste-ready paragraphs into the shared documents after review, re-runs "
    "the project's docs checks if it has them, then reports to the person, so the edits are part of what is "
    "approved."
)
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
PROCEDURE_NEEDLE = "Otherwise one reviewer per repository"


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
            ("minimum two units", MIN_TWO),
            ("sdd scope", SDD_SCOPE),
            ("criterion quote", CRIT_QUOTE),
            ("clean tree", CLEAN_TREE),
            ("readable commands rule", READABLE_RULE),
            ("refusal rule", REFUSAL_RULE),
            ("schema copied verbatim", VERBATIM_SCHEMA),
            ("state directory", STATE_DIR),
            ("run id in separate steps", RUN_ID_STEPS),
            ("hash in separate steps", HASH_STEPS),
            ("literal root", LITERAL_ROOT),
            ("one simple command at a time", ONE_AT_A_TIME),
            ("test run rule", TEST_RUN_RULE),
            ("message file sequence", MESSAGE_FILE_SEQUENCE),
            ("prune meaning", PRUNE_MEANING),
            ("aborted run", ABORTED_RUN),
            ("waves", WAVES),
            ("worktree environment", WORKTREE_ENV),
            ("hook blocked", HOOK_BLOCKED),
            ("wait for all", WAIT_ALL),
            ("failed unit", FAILED_UNIT),
            ("abort on conflict", ABORT_CONFLICT),
            ("verify by diff", VERIFY_BY_DIFF),
            ("no suite", NO_SUITE),
            ("proportional review", PROPORTIONAL),
            ("review stated", REVIEW_STATED),
            ("run directory cleanup", RUN_DIR_CLEANUP),
            ("no fix-up", NO_FIXUP),
            ("close order", CLOSE_ORDER),
            ("base ignored snapshot", BASE_IGNORED),
            ("coordinator git -C", COORDINATOR_GIT_C),
            ("unit names", UNIT_NAMES),
            ("brief git -C", BRIEF_GIT_C),
            ("partial abort", PARTIAL_ABORT),
            ("no force", NO_FORCE),
            ("tests added sum", TESTS_ADDED_SUM),
        ):
            with self.subTest(clause=name):
                self.assertEqual(self.flat.count(clause), 1, clause)

    def test_the_worktree_path_is_outside_the_repository_and_names_no_product(self):
        self.assertTrue(WORKTREE_PATH.startswith("`<state>/agent-worktrees/"))
        self.assertNotIn("pegasus", self.flat.lower())
        self.assertNotIn("opencode", self.flat.lower())
        self.assertNotIn("claude", self.flat.lower())

    def test_the_brief_carries_the_path_and_absolute_path_rules(self):
        for needle in (
            "the absolute worktree path",
            "every file path is absolute",
            "never touch the main checkout",
        ):
            with self.subTest(needle=needle):
                self.assertEqual(self.flat.count(needle), 1)

    def test_no_git_command_chains_cd_and_none_lacks_dash_c(self):
        self.assertNotIn("(workdir or `cd`)", self.flat)
        for m in re.finditer(r"`(git [^`]*)`", self.text):
            cmd = m.group(1)
            if cmd == "git cherry":
                continue
            with self.subTest(cmd=cmd):
                self.assertTrue(cmd.startswith("git -C "), cmd)

    def test_no_prescribed_command_expands_or_substitutes(self):
        """Only the rule that forbids the forms may name them."""
        without_rule = self.text.replace(READABLE_RULE, "")
        self.assertNotIn("$(", without_rule)
        self.assertNotIn("${", without_rule)
        for m in re.finditer(r"`([^`]*)`", without_rule):
            with self.subTest(cmd=m.group(1)):
                self.assertNotRegex(m.group(1), r"\bcd\b.*>")

    def test_the_old_cd_test_wording_is_gone(self):
        self.assertNotIn("cd <path> && <test command>", self.flat)
        self.assertNotIn("Expand the root in the shell", self.flat)

    def test_the_commit_message_comes_from_a_file_outside_the_worktree(self):
        self.assertNotIn("commit -m", self.flat)
        self.assertEqual(self.flat.count("commit -F <that path>"), 1)
        self.assertIn("<root>/<run-id>/<unit>.msg", self.flat)

    def test_the_criterion_is_quoted_only_as_it_is_written(self):
        criterion = collapsed(CRITERION.read_text(encoding="utf-8"))
        self.assertIn('"independently mergeable"', criterion)
        self.assertNotIn("disjoint files or independently mergeable", self.flat)
        self.assertNotIn("<main>", self.flat)

    def test_the_seam_cap_stays_the_criterions(self):
        self.assertIn("Keep the seam cap of the criterion file.", self.flat)
        self.assertNotIn("five or six", self.flat)


class DocsStateTheLimitsTest(unittest.TestCase):
    """The remaining false positive, the `-F` protection and the unmeasured
    depth-two hang are stated where the person reads."""

    def test_both_manuals_and_the_architecture_state_them(self):
        for name in ("MANUAL.md", "MANUAL-claude-code.md", "docs/arquitectura/arquitectura.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(doc=name):
                self.assertIn("commit -F", text)
                self.assertIn("git log --grep push", text)
        for name in ("MANUAL.md", "docs/arquitectura/arquitectura.md"):
            text = (ROOT / name).read_text(encoding="utf-8")
            with self.subTest(doc=name):
                self.assertIn("FOO=1 git push", text)
                self.assertIn("#39112", text)
        self.assertIn("Las diez incertidumbres", (ROOT / "docs/arquitectura/arquitectura.md").read_text(encoding="utf-8"))


class ProcedureIsLazyTest(unittest.TestCase):
    """Closed world: exactly two places name the procedure, the orchestrator
    body (once, because the live run showed the criterion alone is not reached)
    and the criterion (once, in "Writers in parallel")."""

    ORCH = CONTENT / "agents" / "pegasus-orchestrator.md"
    ORCH_SENTENCE = (
        "Before launching two or more sub-agents that write, read "
        "`{{skills_root}}/_shared/parallel-delivery.md` and follow it, and never use a CLI's own "
        "built-in worktree isolation."
    )

    def test_no_other_always_on_body_names_the_procedure(self):
        for key, body in always_on_bodies().items():
            if key == "agent:pegasus-orchestrator":
                continue
            with self.subTest(body=key):
                self.assertNotIn(PROCEDURE_NAME, body)

    def test_exactly_the_orchestrator_and_the_criterion_name_it(self):
        self.assertEqual(content_files_containing(PROCEDURE_NAME), {self.ORCH, CRITERION})

    def test_the_orchestrator_names_it_once_in_the_pinned_sentence(self):
        text = self.ORCH.read_text(encoding="utf-8")
        self.assertEqual(text.count(PROCEDURE_NAME), 1)
        self.assertEqual(text.count(self.ORCH_SENTENCE), 1)

    def test_the_criterion_names_it_once_in_writers_in_parallel(self):
        text = CRITERION.read_text(encoding="utf-8")
        self.assertEqual(text.count(PROCEDURE_NAME), 1)
        section = text.split("## Writers in parallel", 1)[1].split("\n## ", 1)[0]
        self.assertIn(PROCEDURE_NAME, section)

    def test_a_distinctive_phrase_lives_only_in_the_procedure(self):
        self.assertEqual(content_files_containing(PROCEDURE_NEEDLE), {PROCEDURE})


if __name__ == "__main__":
    unittest.main()
