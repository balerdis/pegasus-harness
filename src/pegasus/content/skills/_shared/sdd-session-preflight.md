# SDD Session Preflight

## Scope

Owns the definition of **SDD Session Preflight**: the four decisions the orchestrator
resolves once per session before any SDD phase runs, their exact option literals, their
defaults, the caching rules, and what to ask.

## Authority

Canonical owner of the term *SDD Session Preflight*. Every SDD command file asserts that
preflight "must already be complete for this session" and must "include execution mode,
artifact store, chained PR strategy, and review budget". Those files own the GATE --
whether work may proceed. This file owns WHAT preflight is. Do not restate these
definitions in a command or an agent prompt.

Not to be confused with the Pegasus installer's preflight, which is an unrelated check
about journal writability while installing.

## When preflight runs

On the first SDD command of a session, or on an equivalent natural-language SDD request
("do SDD for X"). Ask once, cache for the session, and do not ask again unless the user
changes a choice or the scope of the work changes.

A natural-language request triggers preflight exactly like a command. Do not skip it
because no command file was involved -- that path is how preflight gets silently missed.

## The four decisions

### 1. Execution mode

| Value | Meaning |
|---|---|
| `interactive` | After each phase, show the result and ask before continuing. **Default.** |
| `auto` | Run phases back to back; show the final result only. |

Interactive approval is phase-scoped: "go on" approves the immediate next phase, never the
rest of the pipeline.

### 2. Artifact store

| Value | Meaning |
|---|---|
| `engram` | Artifacts live in Engram only. No files. Re-running a phase overwrites the previous version. **Default when Engram is available.** |
| `openspec` | File based. Creates the full artifact trail, committable and shareable. |
| `hybrid` | Both. Files for sharing plus Engram for cross-session recovery. Higher token cost. |
| `none` | Results returned inline only. Nothing persisted. Default only when Engram is unavailable. |

Pass the resolved value to every sub-agent launch as `Artifact store mode`. Never hardcode
a store in a phase prompt -- read it from the cached preflight.

### 3. Chained PR strategy

Two settings. Resolve the delivery strategy always; resolve the chain strategy only when
delivery results in chained PRs.

Delivery strategy:

| Value | Meaning |
|---|---|
| `ask-on-risk` | Stop and ask when the workload forecast signals risk. **Default.** |
| `auto-chain` | Split into chained slices without asking. |
| `single-pr` | Keep one PR; requires recording `size:exception` before apply. |
| `exception-ok` | Proceed over budget; apply runs under `size:exception`. |

Chain strategy, asked only if chaining is chosen:

| Value | Meaning |
|---|---|
| `stacked-to-main` | Each PR merges to main in order. Fast iteration, independent slices. |
| `feature-branch-chain` | Only the tracker branch merges to main; child PRs target the previous branch so review diffs stay focused. |
| `size-exception` | No chaining; the change proceeds over budget under a recorded exception. |
| `pending` | Not decided yet. Tasks may record this; apply must not run on it. |

Pass both onward as `Delivery strategy` and `Chain strategy`. Apply returns `blocked` when
neither a delivery decision nor a chain strategy is present, so leaving them unresolved
stops implementation rather than guessing.

### 4. Review budget

The maximum changed lines the user accepts in a single review, default **400**. It is the
threshold the Review Workload Guard compares against the `Review Workload Forecast`
produced by the tasks phase, before apply runs. Exceeding it triggers the cached delivery
strategy. When work proceeds over budget, record `size:exception` and pass it onward.

## What to ask

Ask all four in the user's own language, then STOP until answered. Offer the defaults
explicitly, because accepting them is the common case and a user who does not know the
vocabulary still needs a way through:

> Before starting SDD I need four decisions for this session:
>
> 1. **Execution mode** -- `interactive` (I show you each phase and ask before continuing)
>    or `auto` (I run everything and show the final result). Default: `interactive`.
> 2. **Artifact store** -- `engram` (no files, fast), `openspec` (versionable files),
>    `hybrid` (both) or `none` (inline only). Default: `engram`.
> 3. **PR strategy** -- `ask-on-risk` (I ask if the change goes over budget), `auto-chain`
>    (I split it into slices myself), `single-pr` (one PR, exception recorded) or
>    `exception-ok` (proceed over budget). Default: `ask-on-risk`.
> 4. **Review budget** -- the most changed lines you want to review at once. Default: 400.
>
> Answering "the defaults" is a complete answer.

Accepting the defaults is an explicit preflight, not a skipped one. Record it as answered.

## If preflight is incomplete

Ask, and STOP. Do not run the requested phase in the same turn, and do not infer any of
the four values from context, from a previous session, or from what seems convenient. A
value cached in an earlier session does not carry over: preflight is session-scoped.

## Relationship to the init guard

Preflight and the init phase are different gates, in this order:

1. **Preflight** -- the four session decisions above.
2. **Init guard** -- SDD context must already exist for this project, or be initialised
   after preflight and before any other phase.

Init needs the resolved artifact store, so preflight always comes first.
