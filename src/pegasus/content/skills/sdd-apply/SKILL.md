---
name: sdd-apply
description: "Implement SDD tasks from specs and design. Trigger: orchestrator launches apply for one or more change tasks."
disable-model-invocation: true
user-invocable: false
license: MIT
metadata:
  author: pegasus-balerdis
  version: "3.0"
  delegate_only: true
---

> **ORCHESTRATOR GATE**: If you loaded this skill via the `skill()` tool, you are
> the ORCHESTRATOR — STOP. Do NOT execute these instructions inline. Delegate to
> the dedicated `sdd-apply` sub-agent using your platform's delegation primitive
> (e.g., `task(...)`, sub-agent invocation, etc.). This skill is for EXECUTORS
> only.

## Executor Override

If you ARE the `sdd-apply` sub-agent (NOT the orchestrator), the gate above does NOT apply to you. Continue with the phase work below. Do NOT delegate. Do NOT call the Skill tool. You are the executor — execute.


## Language Domain Contract

Generated technical artifacts default to English. Do not inherit the user's conversational language or the active persona's regional voice for SDD artifacts unless the user explicitly requests that artifact language or the project convention requires it.

If technical artifacts are explicitly requested in another language, use a neutral/professional register unless the user explicitly requests a different tone or regional variant.

Public/contextual comments follow the target context language by default. Explicit user language or tone overrides win; otherwise use a neutral/professional register unless the target context clearly calls for another tone or regional variant.

## Purpose

You are a sub-agent responsible for IMPLEMENTATION. You receive specific tasks from `tasks.md` and implement them by writing actual code. You follow the specs and design strictly.

## What You Receive

From the orchestrator:
- Change name
- The specific task(s) to implement (e.g., "Phase 1, tasks 1.1-1.3")
- Artifact store mode (`engram | openspec | hybrid | none`)
- Structured status from `_shared/sdd-status-contract.md`: `schemaName`, `planningHome`, `changeRoot`, `artifactPaths`, `contextFiles`, `applyState`, task progress, dependency states, and `actionContext`
- Delivery strategy and resolved workload decision (`ask-on-risk | auto-chain | single-pr | exception-ok`, plus PR slice or `size:exception` when applicable)

## Execution and Persistence Contract

> Follow **Section B** (retrieval) and **Section C** (persistence) from `_shared/sdd-phase-common.md`.

- **engram**: Read `sdd/{change-name}/proposal`, `sdd/{change-name}/spec`, `sdd/{change-name}/design`, `sdd/{change-name}/tasks` (all required — keep tasks ID for updates). Mark tasks complete via `mem_update(id: {tasks-observation-id}, content: "...")`. Save progress as `sdd/{change-name}/apply-progress`.
- **openspec**: Read and follow `_shared/openspec-convention.md`. Update `tasks.md` with `[x]` marks.
- **hybrid**: Follow BOTH conventions — persist progress to Engram (`mem_update` for tasks) AND update `tasks.md` with `[x]` marks on filesystem.
- **none**: Return progress only. Do not update project artifacts.

## Status and Workspace Guard

Before reading implementation files or writing code, consume the structured status provided by the orchestrator or build the equivalent status from artifacts.

- If `applyState` is `blocked`, STOP and return `blocked` with the missing artifacts or unsafe context.
- If `applyState` is `all_done`, do not edit. Return `success` with `next_recommended: sdd-verify` or `sdd-archive` based on dependency state.
- If `applyState` is `ready`, proceed only on the assigned pending tasks.
- Read context from `contextFiles` / `artifactPaths` instead of assuming fixed filenames. For spec-driven OpenSpec, these normally map to proposal, specs, design, and tasks.
- If `actionContext.mode` is `workspace-planning` and `allowedEditRoots` is empty, STOP before editing. Treat linked repos and folders as read-only planning context.
- If `allowedEditRoots` is present, edit only files under those roots. If a needed edit is outside the allowed roots, STOP and report the unsafe path.

## What to Do

### Step 1: Load Skills
Follow **Section A** from `_shared/sdd-phase-common.md`.

### Step 2: Read Context

Before writing ANY code:
1. Read the structured status and confirm `applyState: ready`
2. Read every applicable artifact path/topic in `contextFiles`
3. Follow the "Read Before You Write" order in `_shared/implementation-craft.md` (specs, design,
   existing code, conventions). If that reference is missing or unreadable, read in your own
   judgement's order and say so in your report — an unreadable craft reference never blocks the phase.

#### Step 2a: Enforce Review Workload Decision

Before implementing, inspect the tasks artifact for `Review Workload Forecast`. The budget, the
chain strategies, and how to keep a slice reviewable are owned by "Keeping a Diff Reviewable" in
`_shared/implementation-craft.md`.

If the forecast says any of `400-line budget risk: High`, `Chained PRs recommended: Yes`, or
`Decision needed before apply: Yes`, confirm the orchestrator/user provided a resolved delivery path
before implementing:

1. **`auto-chain` or chosen chained/stacked PR mode**: follow the `Chain strategy` from the tasks artifact.
2. **`exception-ok` or single PR with exception**: continue only if the prompt explicitly says the maintainer accepts `size:exception`.
3. **`single-pr` above budget**: continue only after the prompt explicitly records `size:exception`.

Also check for `Chain strategy` in the tasks artifact. If it is `pending` the question was reached and
left open, which is not an answer: STOP and return `blocked`.

If neither delivery decision nor chain strategy is present, STOP before writing code and return `blocked` with: `Workload decision required before apply: estimated work may exceed 400 changed lines. Ask the user which chain strategy to use (stacked-to-main, feature-branch-chain, or size-exception).`

#### Step 2b: Read Previous Apply-Progress (if exists)

Before starting work, check for existing apply-progress:

1. `mem_search(query: "sdd/{change-name}/apply-progress")`
2. If found: `mem_get_observation(id)` → read the full content
3. Parse which tasks are already marked complete
4. Skip those tasks — start from the first incomplete task
5. When saving your apply-progress in Step 6, MERGE: include all previously completed tasks PLUS your newly completed tasks in a single combined artifact

**CRITICAL**: If the orchestrator told you previous progress exists, you MUST read it. If you overwrite without reading, completed work from prior batches is permanently lost.

### Step 3: Resolve Strict TDD Mode

Take `Strict TDD Mode` from your brief first. Without it, resolve the mode with "Resolving Strict TDD
Mode" in `_shared/implementation-craft.md`, which also says what a brief with no recognized spelling
means.

```
Resolved mode:
├── active   → STRICT TDD MODE → Load and follow the Strict TDD module
│              (read the file: sdd-apply/strict-tdd.md)
├── inactive → STANDARD MODE → use Step 4 below (no TDD module loaded)
└── Cache the resolved mode for the return summary
```

**Key principle**: If Strict TDD Mode is not active, ZERO TDD instructions are loaded. The `sdd-apply/strict-tdd.md` module is never read, never processed, never consumes tokens.

The Strict TDD hard gate, its evidence table, and the all-modes Work Unit Evidence table are owned
by "Test-Driven Discipline" in `_shared/implementation-craft.md`. If that reference is missing or
unreadable, apply your own judgement for evidence discipline and say so in your report — an
unreadable craft reference never blocks the phase.

When all implementation work units finish, return control to the parent orchestrator. The executor never launches 4R, Judgment Day, a refuter, a correction actor, or a scoped validator. The parent may delegate fresh-context `sdd-verify` when requirements, tests, or change impact need verification.

### Step 4: Implement Tasks (Standard Workflow)

This step is used when Strict TDD Mode is NOT active. Follow the "Standard Task Loop" in
`_shared/implementation-craft.md`, marking each task complete `[x]` in the persisted tasks artifact
immediately as you go.

### Step 5: Mark Tasks Complete

Update `tasks.md` — change `- [ ]` to `- [x]` for completed tasks:

```markdown
## Phase 1: Foundation

- [x] 1.1 Create `internal/auth/middleware.go` with JWT validation
- [x] 1.2 Add `AuthConfig` struct to `internal/config/config.go`
- [ ] 1.3 Add auth routes to `internal/server/server.go`  ← still pending
```

### Step 6: Persist Progress

**This step is MANDATORY — do NOT skip it.**

Follow **Section C** from `_shared/sdd-phase-common.md`.
- artifact: `apply-progress`
- topic_key: `sdd/{change-name}/apply-progress`
- type: `architecture`
- Also update the tasks artifact with `[x]` marks via `mem_update` (engram) or file edit (openspec/hybrid).

#### Merge Protocol

When saving apply-progress:
1. If you read previous progress in Step 2b, your artifact MUST include ALL previously completed tasks (copy their status and evidence) PLUS your new completions
2. The final artifact should show the cumulative state of ALL tasks across ALL batches
3. Format: keep the same structure but ensure no completed task is lost from prior batches

### Step 7: Return Summary

Before returning, re-read the persisted tasks artifact and confirm every task you report as completed is marked `[x]` there. If the artifact still shows a completed task as `- [ ]`, fix the checkbox before returning. Do not report `Ready for verify` while completed work is only reflected in internal todos or apply-progress.

Return to the orchestrator:

```markdown
## Implementation Progress

**Change**: {change-name}
**Mode**: {Strict TDD | Standard}

### Completed Tasks
- [x] {task 1.1 description}
- [x] {task 1.2 description}

### Files Changed
| File | Action | What Was Done |
|------|--------|---------------|
| `path/to/file.ext` | Created | {brief description} |
| `path/to/other.ext` | Modified | {brief description} |

{IF Strict TDD Mode → include TDD Cycle Evidence table from sdd-apply/strict-tdd.md}

### Deviations from Design
{List any places where the implementation deviated from design.md and why.
If none, say "None — implementation matches design."}

### Issues Found
{List any problems discovered during implementation.
If none, say "None."}

### Remaining Tasks
- [ ] {next task}
- [ ] {next task}

### Workload / PR Boundary
- Mode: {single PR | chained PR slice | stacked PR slice | size:exception}
- Current work unit: {unit name or "N/A"}
- Boundary: {what this apply batch starts from and ends with}
- Estimated review budget impact: {brief note}

### Status
{N}/{total} tasks complete. {Ready for next batch / Ready for verify / Blocked by X}
```

## Rules

The implementation rules — reading specs and design, matching conventions, not freelancing, noting
deviations instead of hiding them, stopping when blocked, PR-slice discipline — are owned by
`_shared/implementation-craft.md`. If that reference is missing or unreadable, apply your own
judgement and say so in your report.

This phase adds, on top of that:

- ALWAYS consume or produce structured status before implementation; do not infer readiness from conversation alone
- STOP on `applyState: blocked` and do not edit; STOP on unsafe `actionContext` or edit roots
- In `openspec` mode, mark tasks complete in `tasks.md` AS you go, not at the end
- Before returning, re-read the persisted tasks artifact and ensure completed tasks are visibly marked `[x]`; internal todos are not completion evidence
- Skill loading is handled in Step 1 — follow any loaded skills strictly when writing code
- Apply any `rules.apply` from `openspec/config.yaml`
- If Strict TDD Mode is active (Step 3), load `sdd-apply/strict-tdd.md` and follow its cycle INSTEAD of Step 4
- When Strict TDD is active, the `sdd-apply/strict-tdd.md` module's rules OVERRIDE Step 4 entirely
- Return envelope per **Section D** from `_shared/sdd-phase-common.md`.

<!-- pegasus-local:cbm-protocol -->
## Local Codebase Memory Protocol for Implementation

Use CBM before writing code when the task changes central/shared symbols, public APIs, controllers/handlers, service methods, routing, persistence flows, or anything likely to have non-obvious callers. Follow the tool priority order and the index-repair rule in `_shared/mcp/cbm-convention.md`. If that path is missing or unreadable, say so and proceed without claiming graph evidence; do not invent your own tool order or fallback conditions.

Do NOT call CBM for simple one-file mechanical edits where the affected surface is obvious.

## CBM Index Coherence Gate

After implementation and before persisting `apply-progress`, trigger only for a High workload forecast, chained/exception delivery, apply-owned structural/generated changes, an apply-owned public/shared API/route/module boundary, or five or more apply-owned files. Do not attribute a dirty global diff blindly: use the orchestrator baseline and apply-owned manifest when present. When triggered, read `sdd-apply/references/cbm-index-coherence.md` before collecting coherence evidence; it owns derivation, moderate-first indexing, coverage evidence, escalation, dirty-baseline handling, and `apply-progress` reporting. If it is missing or unreadable, record coherence as unavailable and do not claim index evidence.
<!-- /pegasus-local:cbm-protocol -->
