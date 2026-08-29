---
name: sdd-continue
description: Continue the next SDD phase in the dependency chain
runs_as: orchestrator
execution: inline
---

Follow the SDD orchestrator workflow to continue the active change.

HARD GATE:
SDD Session Preflight must already be complete for this session. It must include execution mode, artifact store, chained PR strategy, and review budget. If missing, ask the preflight prompt defined in `_shared/sdd-session-preflight.md` and STOP. Do not launch the next phase in the same turn.

WORKFLOW:

1. Under local `--native-review disable`, do NOT invoke or trust `legacy upstream dispatcher` or `legacy upstream dispatcher`. Produce structured status manually from the session's selected artifact backend: inspect OpenSpec proposal/specs/design/tasks/apply-progress/verify-report/archive files for `openspec`; inspect matching `sdd/{change-name}/...` topics with `mem_search` + `mem_get_observation` for `engram`; reconcile both for `hybrid`. A change is archive-ready only when persisted tasks and apply-progress are complete, a current fresh-context `sdd-verify` report passes, and no implementation/test blocker remains. Local archive routing does not require native receipts, ledgers, bundles, contexts, states, or review gates; their absence never routes to review resolution. If `$ARGUMENTS` is missing and more than one active change exists, ask the user to choose and STOP. Do not guess.
2. Produce or consume structured status before acting: schemaName, planningHome/changeRoot, artifactPaths/contextFiles, task progress, dependency states, next recommended action, blocked reasons, and actionContext.
3. Check which artifacts already exist for the active change (proposal, specs, design, tasks)
4. Determine the next phase needed based on the dependency graph:
   proposal → [specs ∥ design] → tasks → apply → verify → archive
5. Launch the appropriate sub-agent(s) for the next phase only if authoritative status says the dependency is ready. Route only by `nextRecommended` and dependency states; never infer from free text. If `blockedReasons` is non-empty, do not proceed to apply, archive, or terminal work. If `nextRecommended` is `verify`, verification/remediation may run only to refresh evidence; if `nextRecommended` is `resolve-blockers`, report `blockedReasons` and stop; if `nextRecommended` is a planning token (`propose`, `spec`, `design`, or `tasks`), launch the corresponding planning phase.
6. Present the result and ask the user to proceed

CONTEXT:

- Working directory: before doing anything else, run `git rev-parse --show-toplevel 2>/dev/null || pwd` with your bash tool and use the returned path as the authoritative workspace. In OpenCode Desktop (Electron) the parse-time interpolation resolves to the app data directory, not the project.
- Current project: the `basename` of the detected workspace above.
- Change name: $ARGUMENTS
- Execution mode: ask/cache per orchestrator
- Artifact store mode: ask/cache per orchestrator; do not hardcode Engram
- Delivery strategy: ask/cache per orchestrator
- Review budget: ask/cache per orchestrator

ENGRAM NOTE:
To check which artifacts exist in engram/hybrid, search: mem_search(query: "sdd/$ARGUMENTS/", project: "{project}") to list all artifacts for this change.
Sub-agents handle persistence automatically using the selected artifact store.

Read the orchestrator instructions to coordinate this workflow. Do NOT execute phase work inline — delegate to sub-agents.

STATUS CONTRACT:

Use the installed shared status contract and derive status from the selected artifact backend; never use native dispatcher output under local native-review-disabled mode. Carry `actionContext` and allowed edit roots into any sub-agent launch. If status reports `workspace-planning` with no allowed edit roots, do not launch apply/verify/archive work that would infer repo-local ownership.
