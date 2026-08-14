---
name: handoff-save
description: Save current session context into handoff.md
runs_as: default
execution: inline
---

Act as the current primary-session orchestrator. Use the `session-handoff` skill in save mode, but do not write `handoff.md` yourself.

1. Synthesize a secret-safe `Parent Session Snapshot` from this actual live conversation with every skill-required field. Validate it before delegation. If Goal, work completed, or exactly one next action cannot be recovered concretely, fail closed without delegating or changing `handoff.md`; Git, Engram, and an existing handoff are not substitutes.
2. Delegate one fresh writer with the native task/subagent primitive. Instruct it to load the `session-handoff` skill, verify external evidence, write and audit `handoff.md`, and return the exact delegated coverage fields. Inject the COMPLETE snapshot verbatim into its task prompt.
3. Snapshot restrictions override generic inspection. The writer MUST NOT read any restricted/sensitive path because it is modified, untracked, or otherwise relevant.
4. If inline injection cannot reliably carry the complete snapshot, create one secret-safe, unambiguously named temporary file in the OS temp directory or an OpenCode-approved temp root, never the project. Pass its exact path to the writer, which may read only that file as conversational evidence. Delete it after the writer returns or fails. Never use `handoff.md` as transport; never stage, commit, or retain the temporary file. Report absence or cleanup failure. Do not use this fallback merely to shorten the prompt.
5. Read back `handoff.md` after the writer returns. Apply the skill's coverage and critical-fact gate against the original snapshot, including restricted paths, incidents, identifiers, exactly one next action, and secret safety. On failure, request at most one corrective rewrite from the writer; read back and gate again. Stop without success after the second failure.
6. Only after the parent gate passes, perform/report the skill's Engram sync step and report success.

Return the writer's exact coverage fields verbatim, plus `Parent read-back: passed|failed`, `Anti-stale audit: pass|fail`, `Engram sync: saved|unavailable|failed`, the handoff path, next-step status, and temporary-snapshot cleanup status (`not used|deleted|failed|missing`).
