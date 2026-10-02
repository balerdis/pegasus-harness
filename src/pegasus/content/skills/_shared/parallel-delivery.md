# Parallel Delivery

## Scope

Owns how a coordinator delivers several genuinely independent units of pending work at once: sorting
them, giving each writer its own files and worktree, integrating, checking, and reviewing. It is for
that case only. A single small change stays inline under the Direct Work Threshold, and this
procedure is never a reason to delegate work that would cost less to do. Whether to fan out at all is
`_shared/sub-delegation-criterion.md`'s; this file is the how, and it narrows that file's "disjoint
files or independently mergeable" to strictly disjoint.

## Authority

Canonical owner of file ownership, the worktree location, integration and the coordinator's own
checks for a parallel delivery. Implementation craft is `_shared/implementation-craft.md`'s and
evidence is `_shared/verification-craft.md`'s. A review here is evidence, not a readiness verdict for
an SDD change: that stays with `sdd-verify`. This is not an FTD rule.

## Procedure

1. **Triage.** Sort the pending work into: doable now; waiting on the person (a decision, cases);
   large features to decide separately; research only. Only the first and the last are launched.
2. **Partition by file ownership.** Units are strictly file-disjoint: anything two units would share
   goes to exactly one of them. The coordinator owns the shared documents: the project's decision or
   architecture document, its release notes, and the FTD record if one exists. Workers never edit
   them; each returns a paste-ready paragraph for the coordinator to integrate. Keep the seam cap of
   the criterion file.
3. **Base and merge plan.** Note the base commit, and state the integration order before launching.
   Without a stated order there is no fan-out.
4. **Create the worktrees.** The coordinator makes one per writing unit, never relying on a CLI's own
   worktree isolation, which may place it inside the repository:
   `git worktree add -b <branch> <path> <base>`, with the path
   `${XDG_STATE_HOME:-$HOME/.local/state}/agent-worktrees/<repo-name>-<short hash of the toplevel path>/<run-id>/<unit>`.
   Run `git worktree prune` at the start of every run. Never put a worktree under a directory the
   deny floor names, and never copy a sensitive file into one.
5. **Launch everything in one message.** Read-only research units go in the same message, with no
   worktree. Each writer's brief carries: the absolute worktree path; that every shell command runs
   in that path (workdir or `cd`) and every file path is absolute; never touch the main checkout; one
   local commit, no push, no AI or tool attribution; run the project's test suite with its output
   redirected to a file, never piped and never backgrounded; and a fixed report: branch and commit,
   files changed, tests and their result, the paste-ready paragraph for the coordinator's documents,
   and anything found but not fixed.
6. **While units run.** When the CLI delivers results one at a time, give the person one short line
   per finished unit, then the consolidated report at the end. When all arrive together, give only
   the consolidated report.
7. **Isolation check.** Before integrating, confirm that `git status --porcelain` in the main
   checkout shows nothing the units wrote. A relative path that escaped lands there.
8. **Integrate.** In the stated order, with `git cherry-pick`. On a conflict, resolve it or stop and
   report. Then confirm with `git cherry <main> <branch>` that each commit is in; only after that run
   `git worktree remove`, `git branch -D` and `git worktree prune`.
9. **The coordinator's own suite run.** One full run on the integrated tree, by the coordinator: a
   single command with its output redirected to a file, then read the tail. Check that the test count
   adds up to the base count plus what the units added.
10. **Fresh-context review.** One reviewer per repository, in parallel, on the integrated diff, each
    with concrete points to attack. Verify every finding before acting on it.
11. **One fix-up writer** applies the confirmed findings on the integrated branch.
12. **Close.** The coordinator integrates the paste-ready paragraphs into the shared documents and
    reports to the person. It asks before any outward action: push, publish, release. Only with the
    person's yes does it do that action, and afterwards it verifies what went out, for example that no
    attribution appears in what was pushed.

## Fail-open

This file says how a parallel delivery runs, never whether one happens. If it is missing or
unreadable, fall back to the criterion file's rules, say that the procedure could not be read, and go
on.
