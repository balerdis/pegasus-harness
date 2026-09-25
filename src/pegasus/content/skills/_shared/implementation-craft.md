# Implementation Craft

## Scope

Owns how to implement well once the work to do is known — reading before writing, the test-driven
discipline (Strict TDD and its evidence), and keeping a diff reviewable — independent of any
change-lifecycle machinery. An agent with no SDD context can follow this file on its own; it says
nothing about artifact stores, phase envelopes, or how progress is persisted between batches.

## Authority

This file is the canonical owner of the implementation method: the reading order before code is
written, the Strict TDD hard gate and its evidence table, the Work Unit Evidence table required in
every mode, and the review-workload / chained-PR discipline that keeps a diff reviewable. A calling
skill states which tasks are assigned and how progress is tracked; it does not restate how to
implement.

## Read Before You Write

Before writing any code:
1. Read the specs — understand WHAT the code must do
2. Read the design — understand HOW to structure the code
3. Read existing code in affected files — understand current patterns
4. Check the project's coding conventions

## Test-Driven Discipline

### Resolving Strict TDD Mode

Resolve the mode once, in this order, and say which step decided it:

1. **A marker in the instructions already in context**, opening no file for it. A marker is a line
   whose whole content is `Strict TDD Mode: enabled` or `Strict TDD Mode: disabled`, or that line
   with its label in bold, `**Strict TDD Mode**: enabled`; no other shape is one. A project's marker
   beats the person's; contradictory markers of unclear origin count as none: say so and go on.
2. **The project flag** `sdd-init` wrote: `strict_tdd` in `openspec/config.yaml`, or Engram's
   `sdd/{project}/testing-capabilities`.
3. **The runner default**: a test runner means active; none means inactive, and say so.

`enabled` without a test runner is inactive, and say so. A brief carrying the marker's spelling has
already resolved the mode; a brief with no spelling this rule recognizes is resolved here, never
silently as standard mode. A change with no behavior to test records `N/A: no behavior changed` as
its gate result, never FAILED.

### Strict TDD Hard Gate (when Strict TDD Mode is active)

- You MUST produce a **TDD Cycle Evidence** table in your progress report
- Each task row MUST have: RED (test written first) → GREEN (implementation passes) → REFACTOR columns
- If you complete a task WITHOUT writing tests first, mark it as FAILED in the evidence table
- Verification WILL reject the work if the TDD Evidence table is missing or incomplete

**There is no silent fallback.** If Strict TDD is active, follow it or report failure. Do not
quietly switch to standard mode.

### Work Unit Evidence (all modes)

Every assigned work unit, including standard mode, MUST produce a **Work Unit Evidence** table
before its tasks are marked complete:

| Evidence | Required value |
|---|---|
| Focused test command and exact result | Smallest command proving this unit; command, exit/result, and relevant counts |
| Runtime harness command/scenario and exact result | Real integration/runtime path; explicit `N/A` only when no runtime boundary exists, with reason |
| Rollback boundary | Exact files/behavior that can be reverted without removing unrelated work |

If design/tasks contain applicable threat-matrix cases, write and run each mapped RED test before
the corresponding production change even in standard mode. Preserve Strict TDD's full
RED → GREEN → REFACTOR evidence when active; this table supplements it and never replaces it. Do not
mark the work unit complete if focused tests or an applicable runtime harness fail.

### Standard Task Loop (when Strict TDD Mode is NOT active)

```
FOR EACH TASK:
├── Read the task description
├── Read relevant spec scenarios (these are your acceptance criteria)
├── Read the design decisions (these constrain your approach)
├── Read existing code patterns (match the project's style)
├── Write the code
├── Mark the task as complete immediately
└── Note any issues or deviations
```

## Keeping a Diff Reviewable

- The default PR review budget is **400 changed lines** (`additions + deletions`), counting authored
  text additions plus deletions only; generated goldens are excluded from that count.
- When the forecast for the assigned work is High risk, or chained/stacked PRs are recommended, or a
  decision is needed before implementing, confirm a resolved delivery path before writing code:
  1. **Chained/stacked PR mode**: implement only the assigned work-unit slice, keep scope autonomous,
     and report the intended PR boundary. Follow the chain strategy (`stacked-to-main` or
     `feature-branch-chain`) for branch targeting.
  2. **Exception**: continue only if it is explicit that the maintainer accepts the size exception.
- Chain strategies:
  - `stacked-to-main`: each PR targets the previous PR's branch (or `main` after the previous merges).
  - `feature-branch-chain`: PR #1 targets the feature/tracker branch; later PRs target the immediate
    previous PR branch. The tracker PR aggregates the feature branch to `main`; child PR diffs must
    stay focused on only the current work unit and must never target `main` directly.
- If neither a delivery decision nor a chain strategy is available, stop before writing code and ask
  which chain strategy to use rather than guessing.

## Rules

- Always read specs before implementing — specs are your acceptance criteria
- Always follow the design decisions — don't freelance a different approach
- Always match existing code patterns and conventions in the project
- If you discover the design is wrong or incomplete, note it in your return summary — don't silently deviate
- If a task is blocked by something unexpected, stop and report back
- When applying a chained/stacked PR slice, keep the batch autonomous: one deliverable scope,
  verification included, and a clear rollback boundary
- When applying a size exception, state it explicitly in the progress report and the return summary
- Never implement tasks that weren't assigned to you
