# Sub-Delegation Criterion

## Scope

Owns whether and how an SDD phase agent fans work out to `pegasus-general` once its own boundary
(`_shared/sdd-phase-common.md`) has decided that delegation is even on the table for this task. This
file is read only when that gate is open — never eagerly, and never by an agent merely loading its
phase skill.

## Authority

This file is the canonical owner of the delegation criterion: the gates, the tests, how many parts to
cut work into, and the rule for writers working in parallel. The phase boundary owns only the
compact IF — fan out to `pegasus-general` or not — and points here for the HOW.

## The criterion

The test behind every delegation decision in this engine, at any level: does doing this yourself
inflate your own context without need? Reading forty files has the same answer whether the reader is
the orchestrator or a phase agent — the test is scale-free, and this file exists so a phase agent
gets to use it too, not a permission-free-for-all in its place.

Three gates, checked in order; fail any one and do not delegate. Then two tests decide.

- **Gate 0 — is there already a tool that returns the compressed answer?** Delegating is compression
  by proxy; a tool compresses for free. Order of preference: a tool, then a child that compresses,
  then doing it yourself. A tool whose freshness you cannot confirm is not a compressor — a stale
  index is evidence not available, never licence to invent; if you cannot confirm it, fall through to
  the child.
- **Gate 1 — can I write each part's brief without naming another part's result?** If one subtask's
  input includes another's output they are sequential, and there is nothing to parallelise. One rule
  covers reading and writing alike: a writer that needs another writer's changes to exist is the same
  case.
- **Gate 2 — do I have at least two genuinely independent parts?** A fan-out of width 1 is a
  hand-off: handing your task to one other agent and signing a result you did not produce. Fan-out
  distributes work and keeps accountability; a hand-off transfers the work without transferring the
  signature. The phase boundary already forbids handing off the whole phase; this gate is the same
  reasoning applied to any one part of it.
- **Test 3 — does my report to my parent name what I had to read, or only the conclusion I drew?**
  Do not estimate a ratio; classify the deliverable. An **answer mission** (find, verify, explore,
  review, decide) has an output that is a conclusion, so everything read is noise by construction —
  high compression, always, without measuring. An **artifact mission** (write, edit, generate) has an
  output that IS the work, so what was read is material, not noise. Decidable from the brief with
  zero tool calls. Where a number is needed, the brief gives the numerator and one cheap count gives
  the denominator. Corollary worth stating: even an implementation phase has a high-compression phase
  (understanding) and a low-compression one (writing) — the natural fan-out of a writer is to split
  the reading, not the writing.
- **Test 4 — can I write my children's output schema before launching them?** Do not anticipate the
  merge; pre-commit to it ("I will receive N verdicts of the form `{file, line, verdict}` and
  concatenate them"). If the schema can be stated, the merge is composable; if it cannot be stated
  without "and then I'll see how they fit", it is not — and that merge will reconstruct the
  children's context, which is paying twice for nothing. This is also the real depth limit, with no
  counter: every level must compress, a child that fans out makes its parent's merge a merge of
  merges, and a level that does not compress is the wrong level to delegate at.

## How many parts

As many as the work's natural seams, not a fixed number; the ceiling comes from test 4, not a
constant — the merge must fit in the window you were protecting. If more than five or six seem
necessary, the seams are cut wrong.

## Writers in parallel

One worktree per writing child, all from the same base commit. That relaxes the requirement from
"disjoint files" to "independently mergeable" — two writers touching the same file is a merge, not a
race. The cost moves to the merge, and resolving a conflict needs both children's context, which is
exactly test 4's failure; so the two tests are tied: if you cannot state how you will merge, there is
no write fan-out. The safety net stays: nothing committed, everything diffable against unmodified
code, and nothing is committed without permission.

## Fail-closed behavior (deliberate departure)

This file governs whether a fan-out happens, not whether the phase's own work happens. Unlike a
required loading gate elsewhere in this engine, an unreadable or missing copy of this file does not
block the phase: it blocks delegation. Fall back to doing the work yourself, sequentially, and say so
in your report, rather than returning `blocked` for a decision the phase can make without this file at
all.
