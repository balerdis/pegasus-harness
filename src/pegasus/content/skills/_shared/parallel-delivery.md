# Parallel Delivery

## Scope

Owns how a coordinator delivers several genuinely independent units of pending work at once: sorting
them, giving each writer its own files and worktree, integrating, checking, and reviewing. It is for
that case only. A single small change stays inline under the Direct Work Threshold, and this
procedure is never a reason to delegate work that would cost less to do. It needs at least two
genuinely independent writing units after triage; with fewer, it does not apply: return to the
criterion's ordinary path. Writers here are general or implementer agents. An SDD apply batch is not
parallelised by this procedure: its task and progress artifacts are shared state. Whether to fan out
at all is `_shared/sub-delegation-criterion.md`'s, which keeps its general "independently mergeable"
rule; this file is the how, and for a delivery run under it, units are strictly file-disjoint.

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
   Without a stated order there is no fan-out. Every git command of the coordinator is `git -C <main checkout> ...`, never `cd` chained with git. The integration branch's checkout must be clean
   (`git -C <main checkout> status --porcelain` prints nothing); if it is not, stop and ask the person, and never stash.
   Units branch from the recorded base, so they will not see uncommitted work: say so. Also record `git -C <main checkout> status --porcelain --ignored` now, for the isolation check.
4. **Create the worktrees.** The coordinator makes one per writing unit, never relying on a CLI's own
   worktree isolation, which may place it inside the repository:
   `git -C <main checkout> worktree add -b <branch> <path> <base>`, with the path
   `${XDG_STATE_HOME:-$HOME/.local/state}/agent-worktrees/<repo-name>-<short hash of the toplevel path>/<run-id>/<unit>`.
   Compute the short hash with `git rev-parse --show-toplevel | sha1sum | cut -c1-8`. The run-id is
   `$(date -u +%Y%m%dT%H%M%SZ)-$(head -c3 /dev/urandom | od -An -tx1 | tr -d ' \n')` and the branch is
   `<run-id>/<unit>`, so re-runs never collide. Expand the root in the shell and pass only the absolute
   result to any tool, never `${...}` text. Unit names are lowercase letters, digits and hyphens, so they are valid ref components. Run `git -C <main checkout> worktree prune` at the start of every run; it
   drops only entries whose directory is gone. After an aborted run, list this repository's
   directories under the root and remove one only with the person's agreement if it holds commits
   that were not integrated. With more units than the CLI's concurrency cap, run them in waves. Never
   put a worktree under a directory the deny floor names, and never copy a sensitive file into one.
5. **Launch everything in one message.** Read-only research units go in the same message, with no
   worktree. Each writer's brief carries: the absolute worktree path; that every git command is
   `git -C <absolute worktree path> ...` and never chains `cd` with git; other commands, such as the test
   suite, run with the CLI's working-directory parameter where it has one, or as a single
   `cd <path> && <test command>` with no git in the chain; every file path is absolute; never touch the main checkout; one
   local commit, no push, no AI or tool attribution, made with `git -C <absolute worktree path> commit -F <message file>`,
   the message written first to `<root>/<run-id>/<unit>.msg` outside the worktree and removed after the commit, so the
   message text never reaches the command line; run the project's test suite with its output
   redirected to a file, never piped and never backgrounded; and a fixed report: branch and commit,
   files changed, tests and their result, tests added, as a count, the paste-ready paragraph for the coordinator's documents,
   and anything found but not fixed. A worktree has none of the main checkout's untracked or ignored
   files: dependency directories, build output, environment files. The writer never copies sensitive
   files; if the tests cannot run there it reports that instead of improvising, and if the repository
   has no test suite it says so. If a commit hook, signing or a missing git identity blocks the
   commit, it reports that and leaves the change uncommitted in the worktree, never bypassing a hook.
6. **While units run.** When the CLI delivers results one at a time, give the person one short line
   per finished unit, then the consolidated report at the end. When all arrive together, give only
   the consolidated report. In background delivery, wait until every unit has reported before
   integrating. A unit that fails or returns nothing is reported as not delivered: integrate the
   rest, leave its worktree in place and give the person its path.
7. **Isolation check.** Before integrating, confirm that `git -C <main checkout> status --porcelain` shows nothing the units wrote, and that `git -C <main checkout> status --porcelain --ignored` equals the one recorded at base time. A relative path that escaped lands there, ignored files included.
8. **Integrate.** In the stated order, with `git -C <main checkout> cherry-pick`. On a conflict run
   `git -C <main checkout> cherry-pick --abort`, stop and report to the person: strictly disjoint units cannot
   conflict, so the partition was wrong, and it is not resolved blind. Picks already integrated stay; the remaining worktrees stay in place, each reported with its path. For a clean pick, confirm with
   `git -C <main checkout> cherry <integration branch> <branch>` that each commit is in; if the person decides to
   resolve a conflict, verify that pick by diff instead, because `git cherry` prints `+` after it.
   Only after that run `git -C <main checkout> worktree remove`, `git -C <main checkout> branch -D` and `git -C <main checkout> worktree prune`. `worktree remove` refuses a worktree holding untracked files that are not ignored: never add `--force` without first listing what would be lost and having the person agree.
9. **The coordinator's own suite run.** One full run on the integrated tree, by the coordinator: a
   single command with its output redirected to a file, then read the tail. Check that the test count
   adds up to the base count plus the units' reported tests added; without a test suite, skip the count check.
10. **Fresh-context review.** Proportional to the integrated diff's size and risk: a trivial diff
    needs no separate reviewer. Otherwise one reviewer per repository, in parallel, on the integrated
    diff, each with concrete points to attack. Verify every finding before acting on it.
11. **One fix-up writer** applies the confirmed findings on the integrated branch; with no confirmed
    finding there is no fix-up writer.
12. **Close.** The coordinator integrates the paste-ready paragraphs into the shared documents after
    review, re-runs the project's docs checks if it has them, then reports to the person, so the
    edits are part of what is approved. It asks before any outward action: push, publish, release.
    Only with the person's yes does it do that action, and afterwards it verifies what went out, for
    example that no attribution appears in what was pushed.

## Fail-open

This file says how a parallel delivery runs, never whether one happens. If it is missing or
unreadable, fall back to the criterion file's rules, say that the procedure could not be read, and go
on.
