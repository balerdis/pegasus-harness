# SDD Session Preflight

## Scope

Owns the definition of **SDD Session Preflight**: the decisions the orchestrator resolves
once per session before any SDD phase runs, their option literals, their defaults, the
caching rules, and what to ask.

## Authority

Canonical owner of the term *SDD Session Preflight*. Every SDD command file asserts that
preflight "must already be complete for this session" and must "include execution mode,
artifact store, chained PR strategy, and review budget". Those files own the GATE --
whether work may proceed. This file owns WHAT preflight is.

A command may describe how it behaves under a resolved value; it must not define the
vocabulary or set a default. Where semantics belong to another shared document, this file
points at it rather than restating it:

- `_shared/persistence-contract.md` owns what each artifact store mode does.
- `_shared/sdd-phase-common.md` owns the review workload guard the budget feeds.

Not to be confused with the Pegasus installer's preflight, which is an unrelated check
about journal writability while installing.

## When preflight runs

On the first SDD command of a session, or on an equivalent natural-language SDD request
("do SDD for X"). Ask once, cache for the session, and do not ask again unless the user
changes a choice or the scope of the work changes.

A natural-language request triggers preflight exactly like a command. Do not skip it
because no command file was involved -- that path is how preflight gets silently missed.

## The decisions

### 1. Execution mode

| Value | Meaning |
|---|---|
| `interactive` | After each phase, show the result and ask before continuing. **Default.** |
| `auto` | Run phases back to back; show the final result only. |

Interactive approval is phase-scoped: "go on" approves the immediate next phase, never the
rest of the pipeline.

### 2. Artifact store

One of `engram`, `openspec`, `hybrid` or `none`. `_shared/persistence-contract.md` defines
what each one does and which is the default; do not restate it here or in a phase prompt.

Pass the resolved value to every sub-agent launch as `Artifact store mode`. Never hardcode
a store in a phase prompt -- read it from the cached preflight.

### 3. Chained PR strategy

**Preflight resolves the delivery strategy only.**

| Value | Meaning |
|---|---|
| `ask-on-risk` | Stop and ask when the workload forecast signals risk. **Default.** |
| `auto-chain` | Split into chained slices without asking. |
| `single-pr` | Keep one PR. Above budget, requires recording `size:exception` before apply. |
| `exception-ok` | Proceed over budget; apply runs under `size:exception`. |

The **chain strategy** -- how the slices relate to each other -- is not a session decision
and is not asked here. The tasks phase asks it, and only when its forecast recommends
chaining, because it is the first point at which the shape of the work is known. Its
values are `stacked-to-main`, `feature-branch-chain`, `size-exception` and `pending`; the
tasks phase owns their meaning and records the answer in the tasks artifact.

Pass the delivery strategy onward as `Delivery strategy`, and the chain strategy, once the
tasks phase has recorded one, as `Chain strategy`. When the forecast signals risk and
neither is present, apply returns `blocked` rather than guessing. Below budget it proceeds
with neither, which is why an unresolved chain strategy is not a reason to stop at session
start.

### 4. Review budget

The maximum changed lines the user accepts in a single review, default **400**. It is the
threshold the review workload guard compares against the `Review Workload Forecast`
produced by the tasks phase, before apply runs; `_shared/sdd-phase-common.md` owns that
guard. Exceeding the budget triggers the cached delivery strategy. When work proceeds over
budget, record `size:exception` and pass it onward.

## What to ask

Ask all four in the user's own language, then STOP until answered. The wording below is
canonical in the sense that it fixes *what is asked* and *which literals are offered* --
translate it, do not re-scope it. Offer the defaults explicitly, because accepting them is
the common case and a user who does not know the vocabulary still needs a way through:

> Before starting SDD I need four decisions for this session:
>
> 1. **Execution mode** -- `interactive` (I show you each phase and ask before continuing)
>    or `auto` (I run everything and show the final result). Default: `interactive`.
> 2. **Artifact store** -- `engram` (no files, fast), `openspec` (versionable files),
>    `hybrid` (both) or `none` (inline only).
> 3. **Delivery strategy** -- `ask-on-risk` (I ask if the change goes over budget),
>    `auto-chain` (I split it into slices myself), `single-pr` (one PR) or `exception-ok`
>    (proceed over budget). Default: `ask-on-risk`.
> 4. **Review budget** -- the most changed lines you want to review at once. Default: 400.
>
> Answering "the defaults" is a complete answer.

Accepting the defaults is an explicit preflight, not a skipped one. Record it as answered.

## If preflight is incomplete

Ask, and STOP. Do not run the requested phase in the same turn, and do not infer any of
the four values from context, from a previous session, or from what seems convenient. A
value cached in an earlier session does not carry over: preflight is session-scoped.

An unresolved *chain* strategy is not an incomplete preflight. It is resolved later, by the
tasks phase, and only when chaining is on the table.

## Relationship to the init guard

Preflight and the init phase are different gates, in this order:

1. **Preflight** -- the session decisions above.
2. **Init guard** -- SDD context must already exist for this project, or be initialised
   after preflight and before any other phase.

Init needs the resolved artifact store, so preflight always comes first.
