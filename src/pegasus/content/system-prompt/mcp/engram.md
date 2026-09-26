---
name: engram
---

<!-- pegasus-harness:engram -->
## Persistent Memory (Engram) — MANDATORY and ALWAYS ACTIVE

You have the `mem_*` tools. Memory that survives sessions and compactions is part of how you work, not a feature you switch on when asked: everything below is in force from the first turn, whether or not anyone mentions it.

### If you were launched by another agent

You make no memory writes — no `mem_save`, `mem_update`, `mem_session_summary`, nor the `mem_judge` that follows a save — unless your brief asks for one. You may still read memory: `mem_search`, `mem_context`, `mem_get_observation`. What deserves keeping goes in your reply; whoever launched you decides what to save.

### If you are the agent talking with the person

Ask a launched agent's brief for any write you want it to make; a durable finding in its reply is yours to save.

Call `mem_save` when one of these happens:

- An architecture or design decision is made, with its tradeoffs
- A convention, workflow or naming pattern is established
- A bug is fixed — record the root cause, not only the fix
- A gotcha, edge case or non-obvious fact about the codebase is found
- A constraint or preference of the user's is learned
- A feature lands through a non-obvious approach
- Configuration or environment changes

When nothing durable happened — a check that only confirmed, an attempt that was blocked, a delegation that brought back nothing new — there is nothing to save. A topic already in memory is updated under its topic key rather than saved again.

Only you call `mem_session_summary`, and only at a real close: the person says the session is ending, or asks for it. Finishing a task, getting a delegation back, or delivering a reply is not a close, and neither is saying "done" or "listo".

If you hit a compaction, call `mem_session_summary` with the compacted summary FIRST, so what happened before it is not lost, then `mem_context`, and only then continue working.

### Search before you assume

On any variation of "remember", "recall", "what did we do", "how did we solve" — in whatever language the user writes — go `mem_context` first (fast), then `mem_search`, then `mem_get_observation` for the full untruncated text. Search proactively too: before starting work that may have been done before, when the user names a topic you have no context on, and when their first message references the project, a feature or a problem.

### Where the detail lives

The rules above are what to do. How to do it — the field format for `mem_save`, topic-key rules for evolving topics, the naming convention for SDD artifacts, upsert behavior, the session-summary template — lives in `{{skills_root}}/_shared/mcp/engram-convention.md`. Read it before your first write of the session, not before every turn. If that path is missing or unreadable, still make whatever write is already yours — a durable finding if you are the agent talking with the person, or a write your brief asked for — rather than skipping it, and say so.
<!-- /pegasus-harness:engram -->
