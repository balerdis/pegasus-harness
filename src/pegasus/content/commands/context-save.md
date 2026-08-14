---
name: context-save
description: Save a lightweight current project snapshot into context.md
runs_as: builder
execution: isolated
---

Use the `session-context` skill in save mode.

Generate or update `context.md` at the project root so this work can be continued in a new OpenCode session.

Purpose:

- preserve the current operational state
- avoid losing context when the session is long or context is full
- save a lightweight snapshot without creating a formal SDD/OpenSpec process
- make the next session start from a concrete next step

Follow the skill rules exactly:

1. Inspect `git status --short`.
2. Inspect modified and relevant files.
3. Identify the current goal.
4. Summarize the current state.
5. Include files in focus.
6. Include changes made.
7. Include open questions.
8. If the working tree is clean, still capture the current goal, recent decisions, session-backed evidence, constraints and next action from the active conversation.
9. Include useful commands.
10. Include exactly one `Next Step`.
11. Do not create OpenSpec artifacts.
12. Do not use Engram by default. Use it only if the user explicitly asks or if missing context is clearly blocking, and then summarize only the directly relevant memory.
13. Write a brief, technical and actionable `context.md`.

Remember the source of truth hierarchy:

1. Code
2. Tests
3. Git status
4. `context.md`
