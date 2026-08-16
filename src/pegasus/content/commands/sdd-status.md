---
name: sdd-status
description: Show structured SDD status for an active change
runs_as: orchestrator
execution: inline
---

You are the `pegasus-orchestrator`. This command is read-only. Do not launch SDD executors and do not edit files.

HARD GATE:

SDD Session Preflight must already be complete for this session. It must include execution mode, artifact store, chained PR strategy, and review budget. If missing, ask the preflight prompt defined in `_shared/sdd-session-preflight.md` and STOP. Do not inspect status in the same turn.

CONTEXT:

- Working directory: before doing anything else, run `git rev-parse --show-toplevel 2>/dev/null || pwd` with your bash tool and use the returned path as the authoritative workspace.
- Current project: the `basename` of the detected workspace above.
- Change name: $ARGUMENTS

TASK:

1. Under local `--native-review disable`, do NOT invoke or trust `legacy upstream dispatcher` or `legacy upstream dispatcher`. Produce structured status manually from the session's selected artifact backend: inspect OpenSpec proposal/specs/design/tasks/apply-progress/verify-report/archive files for `openspec`; inspect matching `sdd/{change-name}/...` topics with `mem_search` + `mem_get_observation` for `engram`; reconcile both for `hybrid`. A change is archive-ready only when persisted tasks and apply-progress are complete, a current fresh-context `sdd-verify` report passes, and no implementation/test blocker remains. Local archive routing does not require native receipts, ledgers, bundles, contexts, states, or review gates; their absence never routes to review resolution. If `$ARGUMENTS` is missing and more than one active change exists, ask the user to choose and STOP. Do not guess.
2. Resolve the active change:
   - If `$ARGUMENTS` is provided, validate that exact change in the selected artifact store.
   - If omitted and exactly one active change exists, select it and say how it was selected.
   - If omitted or ambiguous with multiple active changes, ask the user to choose and STOP. Do not guess.
3. Inspect the selected artifact store from session preflight. Do not hardcode Engram.
4. Return structured status with:
   - Active change selection and schemaName.
   - planningHome, changeRoot, artifactPaths, and contextFiles.
   - Artifact statuses for proposal, specs, design, tasks, apply-progress, and verify-report.
   - Task progress: total, completed, pending, and allComplete.
   - Dependency states for proposal, specs, design, tasks, apply, verify, and archive.
   - Next recommended action.
   - actionContext mode, workspace root, and allowed edit roots.

READ-ONLY RULES:

- Do not create, update, or delete artifacts.
- Do not mark tasks complete.
- Do not launch apply, verify, archive, or continue.
- Do not infer routing from free text. Use `nextRecommended` and dependency states. If `blockedReasons` is non-empty, do not proceed to apply, archive, or terminal work. If `nextRecommended` is `verify`, verification/remediation may run only to refresh evidence; if `nextRecommended` is `resolve-blockers`, report `blockedReasons` and stop; if `nextRecommended` is a planning token (`propose`, `spec`, `design`, or `tasks`), launch the corresponding planning phase.
- If status cannot be resolved safely, return `status: blocked` with the missing information.
