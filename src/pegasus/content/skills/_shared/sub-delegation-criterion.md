# Sub-Delegation Criterion

## Scope

Owns whether and how ANY agent, at ANY level, fans part of its own work out — to whatever target(s)
its own descriptor permits — once delegation is already on the table for this task. This file is read
only when that question is live — never eagerly, and never merely because an agent loaded some other
skill.

## Authority

This file is the canonical owner of the delegation criterion: the gates, the tests, how many parts to
cut work into, and the rule for writers working in parallel, for any agent applying it. Whatever
governs a given caller (a phase boundary, an agent's own body) owns only the compact IF — fan out or
not, and to which targets its own descriptor permits — and points here for the HOW.

## The criterion

The test behind every delegation decision in this engine, at any level: does doing this yourself
inflate your own context without need? Reading forty files has the same answer whether the reader is
the orchestrator or any other agent — the test is scale-free, and this file exists so any agent that
may fan out gets to use it too, not a permission-free-for-all in its place.

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
  signature. Whatever governs you already forbids handing off your whole assignment; this gate is the
  same reasoning applied to any one part of it.
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

## A brief is compression in the wrong direction

Every gate and test above binds the child's report back to you — many files read, one conclusion
returned, and that direction rewards compression without exception. The brief you send out runs the
other way, and the instinct that serves the report is a bug when applied to it. **Write every brief
complete: never trim it to save tokens or shorten the round trip.** What you leave out, the executor
invents, and an invented requirement becomes a gate someone else has to spend rounds negotiating down
— the exact cost compression exists to avoid. A brief is not made better by being shorter; it is made
better by being unambiguous, down to the words themselves: a brief compressed until its grammar breaks
has to be decompressed before it can be obeyed, so the tokens it saved going out are spent twice coming
back.

## Reconnaissance before a brief

"A brief is compression in the wrong direction" says write it complete; this is how completeness
becomes possible, and it is the missing half of that rule. Before delegating, ask one decidable
question: can I name the files the executor will touch, and the specific thing wrong or missing in
each? If the answer is no, that gap — and nothing else — is what you read for: look only at it,
nothing wider. The moment you can name them, stop: you are not reading to solve the problem, only to
know enough to hand it off complete. This is bounded below the threshold that governs delegating the
work itself: naming files and their gaps rarely takes more than a couple of targeted reads, and if it
genuinely needs four files or more, that already IS the threshold in force elsewhere — delegate that
exploration too, with a brief narrow enough to ask only this one question. What it buys, measured in a
real session: two targeted reads deleted a planned signature change, a new lookup, and a parameter
threaded through a call site before anyone wrote them, and in another case named the exact sentences
to fix instead of asking someone to go find the problem.

## Fan-out is help, never offloading

Gate 2 already implies this, and it is the first thing lost under pressure: fan-out is help, never
offloading. The agent that fans out keeps the central work and signs the result; it distributes parts,
never the whole. The failure this prevents is an agent that delegates everything and does none of the
work — it has become an orchestrator it was not asked to be.

## How many parts

As many as the work's natural seams, not a fixed number; the ceiling comes from test 4, not a
constant — the merge must fit in the window you were protecting. If more than five or six seem
necessary, the seams are cut wrong.

## Writers in parallel

One worktree per writing child, all from the same base commit. That relaxes the requirement from
"disjoint files" to "independently mergeable" — two writers touching the same file is a merge, not a
race. The cost moves to the merge, and resolving a conflict needs both children's context, which is
exactly test 4's failure; so the two tests are tied: if you cannot state how you will merge, there is
no write fan-out. The safety net stays: everything diffable against unmodified code. A brief that
asks for one local commit on the child's own worktree branch is the permission for that commit; a
child never pushes and its commit carries no attribution. How a delivery with several writers runs,
from partition to integration, is `_shared/parallel-delivery.md`: read it when the fan-out has
writers.

## Emit together, not one at a time

Independence is a property of the parts; concurrency is a property of how you call. Judging two parts
independent settles nothing by itself — the gates above decide whether and how to cut the work, not
how the calls reach the runtime. Parts run at the same time only if every independent `task` call goes
out in the same reply, before any of their results has come back. Issue one, wait to see what it
returns, then issue the next, and you have picked sequential execution regardless of what the gates
concluded — that is exactly what an agent with no instruction here defaults to: one call, a look at the
result, the next call, and the concurrency the gates bought is never spent. So emit every independent
call in the same turn, then wait for all of them, merge by the schema test 4 already committed to, and
report as one. Where results reach you one at a time, give the person one short line per finished
part first, then that one report; where they arrive together, only the report.

## Fail-closed behavior (deliberate departure)

This file governs whether a fan-out happens, not whether your own work happens. Unlike a required
loading gate elsewhere in this engine, an unreadable or missing copy of this file does not block your
assignment: it blocks delegation. Fall back to doing the work yourself, sequentially, and say so in
your report, rather than returning `blocked` for a decision you can make without this file at all.

## Runtime note: a refused `task` call

If a `task` call comes back with `Subagent depth limit reached`, that is a recoverable tool error, not
a reason to stop. Do the work yourself, sequentially, and say so in your report.
