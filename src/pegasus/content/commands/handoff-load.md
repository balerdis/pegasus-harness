---
name: handoff-load
description: Load handoff.md and prepare continuation plan
runs_as: planner
execution: isolated
---

Use the `session-handoff` skill in load mode.

Read `handoff.md` from the project root and prepare to continue the previous session safely.

Purpose:

- restore the operational context from the previous session
- restore the previous session's `Session Snapshot` when present
- validate the handoff against the real project state
- reconnect the work with OpenSpec and Engram if available
- produce a safe next-step plan before editing anything

Follow the skill rules exactly:

1. Read `handoff.md`.
2. Check `git status --short`.
3. Read `Session Snapshot` if present and treat it as short-term session context to validate, not final truth.
4. Inspect referenced OpenSpec files.
5. Inspect `openspec/config.yaml` if present.
6. Inspect files listed in `Files in Flight`.
7. Use Engram only if needed for directly relevant historical context or if the handoff references memories/session summaries.
8. Detect possible stale or inconsistent information by comparing the handoff with git, code, OpenSpec, and Engram when used.
9. Do not modify files automatically.
10. Do not overwrite `handoff.md`.
11. Return a concise continuation plan.

The response must include:

```md
# Loaded Context

## Verified State

Include the `Session Snapshot` validation when present.

## Possible Staleness

## Recommended Next Action

## Before Editing
```

Remember the source of truth hierarchy:

1. Code
2. Tests
3. OpenSpec
4. Engram
5. `handoff.md`
