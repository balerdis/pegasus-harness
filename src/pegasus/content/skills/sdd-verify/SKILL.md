---
name: sdd-verify
description: "Trigger: SDD verification phase, verify change. Execute tests and prove implementation matches specs, design, and tasks."
disable-model-invocation: true
user-invocable: false
license: MIT
metadata:
  author: pegasus-balerdis
  version: "3.0"
---

## Language Domain Contract

Generated technical artifacts default to English. Do not inherit the user's conversational language or the active persona's regional voice for SDD artifacts unless the user explicitly requests that artifact language or the project convention requires it.

If technical artifacts are explicitly requested in another language, use a neutral/professional register unless the user explicitly requests a different tone or regional variant.

Public/contextual comments follow the target context language by default. Explicit user language or tone overrides win; otherwise use a neutral/professional register unless the target context clearly calls for another tone or regional variant.

## Activation Contract

Run when the orchestrator launches verification for an SDD change. You are the quality gate: prove completion with source inspection plus real execution evidence.

The orchestrator should provide structured status from `_shared/sdd-status-contract.md`. Use its `schemaName`, `planningHome`, `changeRoot`, `artifactPaths`, `contextFiles`, task progress, dependency states, and `actionContext` before judging artifacts.

## Hard Rules

- Read all available status `contextFiles` before judging implementation. Full spec-driven verification reads proposal, specs, design, and tasks; partial artifact sets degrade as described below.
- Run full verification only after all tasks are complete. If any task is pending, return `blocked` without running the full suite.
- Execute relevant tests; static analysis alone is never verification.
- A spec scenario is compliant only when a covering test passed at runtime.
- Compare specs first, design second, task completion third.
- Do not fix issues; report them for the orchestrator/user.
- Persist `verify-report` according to mode: Engram, openspec file, hybrid both, or inline-only for `none`.
- If Strict TDD is active, load `sdd-verify/strict-tdd-verify.md` from this skill directory; if inactive, never load it.
- Return the Section D envelope from `_shared/sdd-phase-common.md`.
- Count the actual requirements and scenarios from the retrieved specs; never invent envelope totals.
- Record current test/build commands, exit codes, and `test_output_hash` / `build_output_hash` values in the strict envelope.
- Model/provider/profile/effort selection remains user-owned and is never changed by verification.
- This is the one independent requirements/runtime final verification. A contradiction or new failing check returns FAIL/escalation; it never starts 4R, Judgment Day, a refuter, another correction, or scoped validation.

## Decision Gates

| Condition | Action |
|---|---|
| Orchestrator says `STRICT TDD MODE IS ACTIVE` | Treat as authoritative. |
| Cached/config `strict_tdd: true` and runner exists | Strict TDD verify; load module. |
| Strict TDD false or no runner | Standard verify; skip TDD checks. |
| `actionContext.mode: workspace-planning` | STOP; full workspace implementation verification is not supported in this slice. |
| Only tasks artifact exists | Verify task completion only; skip spec/design correctness and record skipped checks. |
| Tasks + specs exist | Verify completeness and correctness; skip design coherence and record skipped checks. |
| Proposal/specs/design/tasks exist | Verify all dimensions. |
| Task incomplete | CRITICAL for core task, WARNING for cleanup task. |
| Test command exits non-zero | CRITICAL. |
| Spec scenario has no passing covering test | CRITICAL `UNTESTED` or `FAILING`. |
| Design deviation exists | WARNING unless it breaks a spec. |

## Execution Steps

1. Load relevant skills via shared SDD Section A.
2. Retrieve artifacts via shared Section B for the active persistence mode, or read the concrete `contextFiles` from structured status.
3. Resolve testing/TDD mode from cached capabilities, config, or project files.
4. Count completed and incomplete tasks. Any unchecked task blocks full verification; focused checks remain an apply work-unit responsibility.
5. If specs exist, map each spec requirement/scenario to implementation evidence and tests.
6. If design exists, check design decisions against changed code. If design is missing, skip design coherence and record why.
7. Run test, build/type-check, and coverage commands when available. For full spec verification, preserve Pegasus baseline's stricter runtime evidence: source inspection alone does not prove spec scenario compliance.
8. Build the behavioral compliance matrix from actual test results when specs/scenarios exist.
9. Persist and return the verification report, including skipped dimensions for missing artifacts.

## Output Contract

Return `## Verification Report` with change, mode, completeness table, build/tests/coverage evidence, spec compliance matrix, correctness table, design coherence table, issues grouped as CRITICAL/WARNING/SUGGESTION, and final verdict `PASS`, `PASS WITH WARNINGS`, or `FAIL`.

## Graceful Artifact Handling

- **Tasks only**: verify objective task completion only. Do not claim spec correctness or design coherence. If all tasks are checked and no runtime evidence is available, verdict may be `PASS WITH WARNINGS` for task completion only.
- **Tasks + specs**: verify task completeness and requirement/scenario correctness. Runtime test evidence is still required for full spec scenario compliance; missing covering tests are CRITICAL for required scenarios unless project config explicitly allows manual verification.
- **Full artifacts**: verify completeness, correctness, and coherence.
- **Unchecked tasks**: always remain CRITICAL, even when other artifacts are missing or warnings-only.

## References

- [references/report-format.md](references/report-format.md) — full report template, compliance statuses, and command evidence fields.
- [strict-tdd-verify.md](strict-tdd-verify.md) — load only when Strict TDD is active.
- `_shared/sdd-phase-common.md` — skill loading, retrieval, persistence, and return envelope.

<!-- pegasus-local:sdd-verify-executor-boundary -->
## Executor Boundary

You are already the dedicated `sdd-verify` executor. Perform source inspection, CBM analysis, test/build commands, and verification report production directly. Never launch subagents, call `task(...)` or any delegation primitive, or bounce verification back because delegation permission is unavailable. Orchestrator routing delegates work to you; it is not part of this executor prompt.
<!-- /pegasus-local:sdd-verify-executor-boundary -->

<!-- pegasus-local:cbm-protocol -->
## Local Codebase Memory Protocol for Verification

Use CBM to focus verification when implementation touched shared logic or when affected tests are not obvious.

Preferred checks:
- Use `detect_changes` to summarize changed surface and impact since the relevant base ref.
- Use `trace_path` to identify affected callers, routes, services, or modules.
- Use `search_code` to find tests, fixtures, literals, or edge-case references tied to the change.
- Use `index_status` to note whether graph evidence may be stale.

Do NOT replace the actual project test runner with CBM. CBM guides verification; tests prove behavior.

## CBM Index Evidence Gate

Index-based evidence is provisional unless `apply-progress` recorded adequate coherence evidence or verification establishes current evidence. Tests and direct inspection remain authoritative; do not reject or pass behavior solely from graph status.
<!-- /pegasus-local:cbm-protocol -->

<!-- pegasus-local:sdd-evidence-maintenance-policy -->
## Evidence Maintenance and Verification Precedence

Verification evidence is ranked in this order:

1. Current runtime/test command results and current Git/filesystem state.
2. Current source and configuration inspection.
3. Persisted SDD progress/report claims, including `apply-progress`, `verify-report`, and task notes.

Persisted claims are historical metadata; they cannot override contradictory live evidence.

When an isolated persisted factual claim is stale or inaccurate, while current code, tests, and state satisfy the specification, classify it as stale documentation/evidence metadata rather than a product or test blocker. When the selected artifact backend and `actionContext.allowedEditRoots` allow it, correct that artifact directly and transparently: retain the surrounding history/context, identify the corrected claim, record the live evidence used, and run only the focused validation needed for the correction. Do not create a new SDD change or restart proposal, specs, design, tasks, or the full apply cycle solely for this bounded evidence-maintenance correction. After correction and focused verification, stale wording alone does not block commit readiness.

If the proposed correction would change scope or requirements, or could conceal an implementation, runtime, test, or specification failure, do not edit it. Report the blocker and use normal remediation for the real failure.

The orchestrator treats a qualifying correction as one atomic evidence-maintenance operation. It may perform or delegate one focused correction and a fresh focused `sdd-verify`; it must not restart the SDD pipeline for that correction alone.
<!-- /pegasus-local:sdd-evidence-maintenance-policy -->
