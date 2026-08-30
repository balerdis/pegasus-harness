---
name: engram
description: Persistent memory that survives across sessions and compactions
distribution: download
endpoint: https://github.com/Gentleman-Programming/engram/releases/download/v1.20.0/engram_1.20.0_linux_amd64.tar.gz
version: 1.20.0
checksum: sha256:7dc3003318e303bee269a4772144f3ce01c8ec700bfd524aaec76770acd389ca
archive_members: [CHANGELOG.md, LICENSE, README.md, engram]
archive_executable: engram
argv: [mcp, --tools=agent]
---

# Engram Convention (persistent memory)

Engram is a persistent memory system that survives across sessions and compactions,
reached through the `mem_save`, `mem_search`, `mem_context`, and the rest of the
`mem_*` family. This protocol is mandatory and always active whenever those tools
are present in your session — not something you activate on demand.

## Proactive Save Triggers (mandatory — do not wait for the user to ask)

Call `mem_save` immediately and without being asked after any of these:

- Architecture or design decision made
- Team convention documented or established
- Workflow change agreed upon
- Tool or library choice made with tradeoffs
- Bug fix completed (include root cause)
- Feature implemented with non-obvious approach
- Notion/Jira/GitHub artifact created or updated with significant content
- Configuration change or environment setup done
- Non-obvious discovery about the codebase
- Gotcha, edge case, or unexpected behavior found
- Pattern established (naming, structure, convention)
- User preference or constraint learned

Self-check after EVERY task: "Did I make a decision, fix a bug, learn something
non-obvious, or establish a convention? If yes, call `mem_save` NOW."

## Save Format

Format for `mem_save`:

- **title**: Verb + what — short, searchable (e.g. "Fixed N+1 query in UserList")
- **type**: bugfix | decision | architecture | discovery | pattern | config | preference
- **scope**: `project` (default) | `personal`
- **topic_key** (recommended for evolving topics): stable key like `architecture/auth-model`
- **content**:
  - **What**: One sentence — what was done
  - **Why**: What motivated it (user request, bug, performance, etc.)
  - **Where**: Files or paths affected
  - **Learned**: Gotchas, edge cases, things that surprised you (omit if none)

## Topic Update Rules

- Different topics MUST NOT overwrite each other
- Same topic evolving → use same `topic_key` (upsert)
- Unsure about key → call `mem_suggest_topic_key` first
- Know exact ID to fix → use `mem_update`

## When To Search Memory

On any variation of "remember", "recall", "what did we do", "how did we solve", or
references to past work (in any language the user writes in):

1. Call `mem_context` — checks recent session history (fast, cheap)
2. If not found, call `mem_search` with relevant keywords
3. If found, use `mem_get_observation` for full untruncated content

Also search PROACTIVELY when:

- Starting work on something that might have been done before
- User mentions a topic you have no context on
- User's FIRST message references the project, a feature, or a problem — call
  `mem_search` with keywords from their message to check for prior work before
  responding

## Session Close Protocol (mandatory)

Before ending a session or saying "done" / "listo" / "that's it" (or the
equivalent in the user's language), call `mem_session_summary` with this shape:

```markdown
## Goal
[What we were working on this session]

## Instructions
[User preferences or constraints discovered — skip if none]

## Discoveries
- [Technical findings, gotchas, non-obvious learnings]

## Accomplished
- [Completed items with key details]

## Next Steps
- [What remains to be done — for the next session]

## Relevant Files
- path/to/file — [what it does or what changed]
```

This is NOT optional. If you skip it, the next session starts blind.

## After Compaction

If you see a compaction message or "FIRST ACTION REQUIRED":

1. IMMEDIATELY call `mem_session_summary` with the compacted summary content —
   this persists what was done before compaction
2. Call `mem_context` to recover additional context from previous sessions
3. Only THEN continue working

Do not skip step 1. Without it, everything done before compaction is lost from
memory.
