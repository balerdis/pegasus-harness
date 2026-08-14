---
description: Load context.md and prepare a safe continuation plan
agent: plan
subtask: true
---

Use the `session-context` skill in load mode.

Read `context.md` from the project root and prepare to continue the previous session safely.

Purpose:

- restore lightweight operational context from a previous session
- validate the snapshot against the real project state
- produce a safe next-step plan before editing anything

Follow the skill rules exactly:

1. Read `context.md`.
2. Check `git status --short`.
3. Inspect files listed in `Files in Focus`.
4. Validate the snapshot against the actual code.
5. Detect stale or inconsistent information.
6. Do not modify files automatically.
7. Do not overwrite `context.md`.
8. Return a concise continuation plan.

The response must include:

```md
# Loaded Context

## Verified State

## Possible Staleness

## Recommended Next Action

## Before Editing
```

Remember the source of truth hierarchy:

1. Code
2. Tests
3. Git status
4. `context.md`
