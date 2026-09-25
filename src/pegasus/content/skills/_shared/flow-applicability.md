# Flow Applicability

## Scope

Owns one question and only that one: **which route does this request take?** There are four — a
query, an L0 direct change, FTD and formal SDD — and this file decides between them without teaching
how any of them runs.

## Authority

Canonical owner of the route ladder: the routing facts, their order, the ambiguous cases, the
promotions, and work that grows mid-flight. Whatever governs a given caller — an orchestrator body, a
command file — owns only the compact IF and the clear cases, and points here for the rest.

This file never softens a gate. Once the answer is SDD, `_shared/sdd-session-preflight.md` and the
init guard apply in full, exactly as their own owners define them.

## Routing facts

Four facts, each true or false and backed by evidence. When the route is not obvious, get only the
missing ones: investigate within your own threshold, or delegate a narrow exploration that returns
the facts with their evidence, never a route.

- `output_is_information` — is the output sought information, a recommendation, an investigation or a
  check, with nothing changed yet?
- `asked_for_sdd` — did the person ask for SDD, a spec or a plan explicitly, by command or in their
  own words?
- `needs_reviewable_contract` — must a contract or a decision be fixed before code, reviewable by
  someone who will not be in the implementation, or is it a spec others will build against?
- `needs_continuity` — does the work need continuity, a checklist, a handoff or durable evidence?

**Size is never a fact.** Files, lines and urgency decide nothing here; file count may inform whether
to delegate, never which route to take.

## Decision order

Ask in this order and stop at the first fact that is true:

1. `output_is_information` → **query**.
2. `asked_for_sdd` → **SDD**; the explicit request is the acceptance.
3. `needs_reviewable_contract` → **SDD** is proposed, and entered only on explicit acceptance.
4. `needs_continuity` → **FTD**.
5. None of the above → **L0**.

## The routes

- **Query** when the output ends the work: explain, compare, investigate, audit, review, run a check,
  or propose without authorization to implement. It changes nothing.
- **L0** when the change is one trivial, atomic, known intervention with no decision to settle,
  provable with one proportionate piece of evidence. It leaves a diff, that evidence and an honest
  report, and no record.
- **FTD** when the change is decided enough to apply, needs no reviewable contract, and does need
  continuity, a checklist, durable evidence or a handoff. Ask until the scope is closed, then confirm
  once before writing.
- **SDD** when someone absent from the implementation must review a contract or a decision before
  code; when others build against its spec, API, authorization or data model; when others will
  execute its ordered units; or when it was asked for.

## Ambiguous cases

Resolve them by what the OUTPUT has to be and who must review it before code, never by size:

- **A small change to a contract others build against.** Two lines can still need a spec: when
  consumers outside the change build against them, it is **SDD**.
- **A decision or a trade-off to settle.** On its own it is not SDD: decide it with the person, write
  it down with the work, and go on as **FTD**.
- **Work that crosses sessions or leaves a record behind.** A checklist the next session picks up, or a
  record that outlives the session, is continuity: **FTD**.
- **A bug fix with an unclear cause.** Investigate before routing; once the cause is confirmed, the fix
  routes by its own facts.
- **Large but already decided.** A dependency upgrade with known fallout, a mechanical migration, a
  cross-cutting rename or a refactor whose behaviour the tests already state is **FTD** however many
  files it touches; one trivial operation repeated across many files stays **L0**.

Genuinely undecidable? Ask in one line, naming both routes and what each costs; never pick the heavier
one silently because it is safer to be wrong about — a cycle nobody wanted is a real cost paid by a
real person.

## Promotions

A route moves only up the ladder, and every move is named out loud:

- **Query → L0, FTD or SDD** when the investigation leaves an executable proposal. A query authorizes
  no change: ask once whether to go ahead, and the investigation becomes the new route's input.
- **L0 → FTD** when the change stops being atomic: several tasks, another session or a handoff,
  grouped evidence, more surface than planned, or a decision worth recording. Carry over what was done
  as it really happened, never as if FTD had been there from the start.
- **L0 → SDD** when a `needs_reviewable_contract` appears. A decision taken and landed in the same work
  promotes to FTD instead.
- **FTD → SDD** when a `needs_reviewable_contract` appears or SDD, a spec or a plan is asked for. Two
  reasonable designs or a trade-off, on their own, do not promote: they are decided, written down,
  and the FTD goes on.

Entering SDD because a reviewable contract appeared needs explicit acceptance; an explicit request is
its own acceptance. Nothing leaves SDD on its own.

## When work grows mid-flight

Work that started as a question and turned into a change, or as a direct change that turned into
more, is the common case, not a mistake. Do not retrofit: the work already done is the exploration.
Name the moment out loud, propose the switch, and resolve preflight then if the switch is to SDD —
the gates apply from that point forward, never retroactively to work already delivered. If the person
declines, keep going on the current route and say what will be missing without the new one.

## Fail-open

This file decides a route, never whether work happens. If it is missing or unreadable, judge from the
clear cases you already carry, say which way you judged and why, and proceed — a router nobody can
read is not a reason to refuse the request, and it is not licence to skip a gate that does apply once
the answer is SDD.
