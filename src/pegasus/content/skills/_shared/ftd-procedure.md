# FTD Procedure

## Scope

Owns how an FTD runs once `_shared/flow-applicability.md` has routed work to it: the record, the
evidence it must carry, and how the change closes. It decides no route and teaches no method.

## Authority

Canonical owner of the FTD record — where it lives, its sections, the states of what is left — and
of the evidence rules an FTD item must meet. How to implement is `_shared/implementation-craft.md`'s;
what counts as evidence in general is `_shared/verification-craft.md`'s; SDD's artifact store is
`_shared/persistence-contract.md`'s, and FTD never uses it. FTD imposes no branch, no worktree rule,
no SDD pipeline and no `sdd-verify`: delivery, Git and isolation follow the existing policy.

## Before writing

Ask only when the answer changes the scope, the acceptance criteria, a risk, a dependency or the
evidence, never as a ritual. Then confirm the scope once, and it becomes the record's Scope.

Whoever coordinates the FTD resolves Strict TDD Mode once per session with "Resolving Strict TDD
Mode" in `_shared/implementation-craft.md`, and sends it in every implementation brief as
`Strict TDD Mode: <enabled|disabled>`, filled with the value resolved.

## The record

One record per change, at `docs/ftd/<YYYY-MM-DD>-<slug>.md` in the project. Write it without
asking; it is versioned by default. The FTD that creates `docs/ftd/` says once where the record is
and that it can be kept out of the repository with `.gitignore`, or with `.git/info/exclude`, which
is not versioned; no later FTD repeats it.

One writer at a time: whoever coordinates the FTD keeps the record. Sub-agents return evidence, and
the coordinator writes it in.

```markdown
# <the change>

## Intent
<what the change is for>

## Scope
<the scope confirmed before writing>

## Decisions
<optional, only when the change takes decisions: topic, decision, reason — never the diff>

## Checklist
- [ ] <item> — done only with its observation in Evidence

## Evidence
<each command verbatim, its exit status, and what it produced>

## Next
- <what is left of this change> — <its state>
```

Next lists what is left of this change, not of everything, each item in one of three states. When
the project keeps its work queue as an Engram topic, Next links to it instead of copying it.

- **Open debt** — carries what unblocks it.
- **Resolved** — carries its evidence.
- **Accepted limitation** — carries nothing that unblocks it: it was decided to stay, and reopens
  only if that decision does.

## Promotion into FTD

When L0 work turns into FTD, the record starts from the current state: what was done, with what real
evidence, and what is left. Never write it as if FTD had been there from the start, and never mark a
check nobody observed.

## Graduation

The record is a change's log: it closes and is not corrected afterwards. A decision that outlives
the change — a convention, an accepted limitation, an invariant — graduates to the project's living
document, if it has one, or to a stable Engram topic, and the record links there. With neither, it
stays in the record, and the record says so.

## Engram

Engram is the link, not a second copy. When it is available, save the decisions, the outcome and
the record's exact path, `docs/ftd/<YYYY-MM-DD>-<slug>.md`, with its usual protocol, so the change
can be found again or promoted to SDD later. Without Engram, the record is the durable source:
report its exact path in the conversation.

## Evidence rules

**A checkbox is not evidence.** Each completed item points at a concrete observation: a test, a
build, an exit status, a runtime check, a parsed configuration, a confirmed search, a smoke test or
an appropriate visual check. A check that could not run is recorded `not-run`, `blocked` or
`failed`, never as done. Evidence keeps every command verbatim with its exit status. Never copy a
secret, or the content of a sensitive file, into Evidence: record the command and its exit status,
omit the output that carries it, and say it was omitted.

1. The exit status that counts is the command's, never a pipe's after it: `if cmd | tail; then`
   measures `tail`.
2. A search for X never runs where its own path contains X; if it must, verify the result before
   believing it.
3. A figure obtained under a declared limitation travels with it: "N, with limitation L" is one fact.
4. The artifact names, URLs and files a check uses come from the source that produced them, never
   from memory.
5. A probe needs a control arm and an observable the agent under test cannot fabricate.
6. An empty grep is weak evidence of absence, not proof.
7. A literal that matches today's identity is right by accident: derive the invariant from the source
   it protects.
8. A green test's name is a claim: audit that its body proves what the name promises.
9. Under `set -euo pipefail`, a pipe into `head -1` can kill its producer with SIGPIPE and abort the
   script silently.

## Closing

An item is done only when the record shows its observation. Whoever asked for the work declares it
ready, reading those observations; whoever signs something they also wrote says so, instead of
presenting it as independent verification. `pegasus-verifier` returns evidence, never that call.

## Fail-open

This file says how an FTD runs, never whether it happens. If it is missing or unreadable, keep the
checklist and its evidence in your reply, say that the procedure could not be read, and go on.
