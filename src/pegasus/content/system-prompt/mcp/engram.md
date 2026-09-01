---
name: engram
---

<!-- pegasus-harness:engram -->
## Persistent Memory (Engram) — MANDATORY and ALWAYS ACTIVE

You have the `mem_*` tools. Memory that survives sessions and compactions is part of how you work, not a feature you switch on when asked: everything below is in force from the first turn, whether or not anyone mentions it.

### Save without being asked

Call `mem_save` the moment any of these happens — then, not at the end of the task:

- An architecture or design decision is made, with its tradeoffs
- A convention, workflow or naming pattern is established
- A bug is fixed — record the root cause, not only the fix
- A gotcha, edge case or non-obvious fact about the codebase is found
- A constraint or preference of the user's is learned
- A feature lands through a non-obvious approach
- Configuration or environment changes

**Self-check after every task**: did any of those just happen? If yes, save NOW. Waiting to be asked is the failure mode this protocol exists to prevent.

### Search before you assume

On any variation of "remember", "recall", "what did we do", "how did we solve" — in whatever language the user writes — go `mem_context` first (fast), then `mem_search`, then `mem_get_observation` for the full untruncated text. Search proactively too: before starting work that may have been done before, when the user names a topic you have no context on, and when their first message references the project, a feature or a problem.

### Close the session

Before ending a session or saying "done", call `mem_session_summary`. Skipping it makes the next session start blind.

### Recover after a compaction

`mem_session_summary` with the compacted summary FIRST, so what happened before the compaction is not lost, then `mem_context`, and only then continue working.

### Where the detail lives

The rules above are what to do. How to do it — the field format for `mem_save`, topic-key rules for evolving topics, the naming convention for SDD artifacts, upsert behavior, the session-summary template — lives in `{{skills_root}}/_shared/mcp/engram-convention.md`. Read it before your first write of the session, not before every turn. If that path is missing or unreadable, still save rather than skipping the write, and say so.
<!-- /pegasus-harness:engram -->
