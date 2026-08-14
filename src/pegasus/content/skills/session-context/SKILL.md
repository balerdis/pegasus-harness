---
name: session-context
description: Save or load a lightweight project session snapshot using context.md. Use when the user wants to preserve current work across OpenCode sessions without a formal SDD/OpenSpec workflow.
compatibility: opencode
---

# Session Context Skill

This skill manages a lightweight session snapshot using `context.md`.

It is intended for simple or puntual work where there is no formal SDD/OpenSpec process active.

It is different from `session-handoff`.

Use:

- `context.md` for lightweight project/session snapshots.
- `handoff.md` for formal handoff connected with OpenSpec, Engram and SDD.

## Purpose

Use this skill when the user wants to:

- save current project context before closing a session
- resume work after context compaction or a full new session
- capture what they were doing without creating a formal spec
- continue debugging, investigation or implementation later
- preserve a simple operational snapshot

## Source of truth hierarchy

Use this hierarchy:

1. Code
2. Tests
3. Git status
4. `context.md`

`context.md` is only a lightweight session snapshot. It may be stale.

---

# Save mode

Use this mode when the user asks to create, update, save or generate a session context snapshot.

Create or update `context.md` at the project root.

Before writing:

1. Inspect `git status --short`.
2. Inspect relevant modified files.
3. Inspect recently relevant files from the current session if they are known.
4. Identify the current goal from the conversation and project state.
5. Identify useful commands for testing, debugging or reproducing the issue.
6. If `git status --short` is clean, do not assume there is no useful context. Capture the current goal, recent decisions, conversation-backed operational evidence, open questions and next action from the active session.
7. Do not create OpenSpec artifacts.
8. Do not use this as formal documentation.
9. Do not invent facts.

Write `context.md` with this structure:

```md
# Context Snapshot

## Goal

Concrete objective of the current work.

## Current State

Where the work stands right now.

Include:

- what was being investigated or changed
- what currently works
- what is still pending
- current hypothesis, if any

## Files in Focus

Relevant files and why they matter.

Format:

- `path/to/file`: why it matters

## Git Status Summary

Brief summary of the working tree.

Include modified, added or deleted files if relevant.

## Changes Made

Concrete changes made so far.

Be specific and verifiable.

## Open Questions

Things that are still unclear.

## Session Evidence

Short facts from the current conversation/session that matter for continuation.

Include only if relevant:

- decisions just made
- production/test/debug validation mentioned in the session
- confirmed constraints
- blockers or caveats

Keep it short. Do not turn `context.md` into long-term documentation.

## Next Step

Exactly one next concrete action.

This should be the first thing the next session should do.

## Useful Commands

Commands for reproducing, testing, debugging or verifying.

## Notes

Any extra short notes that help the next session continue.
```

## Save mode rules

* Keep `context.md` short, technical and actionable.
* Prefer paths, commands and concrete facts.
* Do not include long explanations.
* Do not include unrelated history.
* Do not create SDD/OpenSpec artifacts.
* Do not treat `context.md` as a source of truth.
* If something is unknown, say it is unknown.
* Include exactly one `Next Step`.
* Repo-clean does not mean context-clean. The useful snapshot may come from the current conversation/session even when there are no file changes.
* Prefer conversation-backed facts over generic placeholders.

---

# Load mode

Use this mode when the user asks to load, resume, continue or restore from `context.md`.

Before doing implementation:

1. Read `context.md` from the project root.
2. Check `git status --short`.
3. Inspect files listed in `Files in Focus`.
4. Validate `context.md` against the actual code and working tree.
5. Detect stale, missing or inconsistent information.
6. Do not modify files automatically.
7. Do not overwrite `context.md`.

Then respond with:

```md
# Loaded Context

Brief summary of the current work.

## Verified State

What was confirmed from:

- `context.md`
- git status
- files in focus
- code inspection

## Possible Staleness

Anything outdated, uncertain or inconsistent.

## Recommended Next Action

One concrete next action.

## Before Editing

Anything that should be checked before modifying files.
```

## Load mode rules

* Do not modify files automatically in load mode.
* Do not continue implementation yet.
* Do not run destructive commands.
* Do not overwrite `context.md` in load mode.
* Wait for explicit user confirmation before applying changes.
* Do not invent facts.
* Keep the response brief, technical and actionable.

---

# Behavior when OpenSpec exists

This workflow is intentionally lightweight.

If OpenSpec exists, do not automatically enter SDD mode.

Only mention OpenSpec if it is clearly relevant to the current work.

If the user needs formal SDD/OpenSpec handoff, suggest using:

```txt
/handoff-save
/handoff-load
```

instead of:

```txt
/context-save
/context-load
```

---

# Behavior with Engram

This workflow should not depend on Engram.

If Engram is available, do not search it by default.

Only use Engram if the user explicitly asks for historical memory or if the missing context is clearly blocking. If Engram is used, include only a brief summary of the directly relevant memory and say why it was needed.

For normal usage, keep `context.md` local and lightweight.

---

# Final principle

`context.md` is not a spec, not documentation and not long-term memory.

It is a quick operational snapshot for continuing work in another OpenCode session.
