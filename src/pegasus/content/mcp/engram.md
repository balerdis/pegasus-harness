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

## SDD Artifact Naming Convention

NOTE: Critical engram calls (`mem_search`, `mem_save`, `mem_get_observation`) are inlined directly in each skill's SKILL.md. This section is supplementary reference — sub-agents do NOT need to read it to function.

### Naming Rules

ALL SDD artifacts persisted to Engram MUST follow this deterministic naming:

```
title:     sdd/{change-name}/{artifact-type}
topic_key: sdd/{change-name}/{artifact-type}
type:      architecture
scope:     project
capture_prompt: false
```

Set `capture_prompt: false` when the Engram tool schema supports it; if an older schema rejects or does not expose the field, omit it rather than failing.

#### Artifact Types

| Artifact Type | Produced By | Description |
|---------------|-------------|-------------|
| `explore` | sdd-explore | Exploration analysis |
| `proposal` | sdd-propose | Change proposal |
| `spec` | sdd-spec | Delta specifications (all domains concatenated) |
| `design` | sdd-design | Technical design |
| `tasks` | sdd-tasks | Task breakdown |
| `apply-progress` | sdd-apply | Implementation progress (one per batch) |
| `verify-report` | sdd-verify | Verification report |
| `archive-report` | sdd-archive | Archive closure with lineage |
| `state` | orchestrator | DAG state for recovery after compaction |

#### State Artifact

```
mem_save(
  title: "sdd/{change-name}/state",
  topic_key: "sdd/{change-name}/state",
  type: "architecture",
  capture_prompt: false,
  content: "change: {change-name}\nphase: {last-phase}\nartifact_store: engram\nartifacts:\n  proposal: true\n  specs: true\n  design: false\n  tasks: false\ntasks_progress:\n  completed: []\n  pending: []\nlast_updated: {ISO date}"
)
```

Recovery: `mem_search("sdd/{change-name}/state")` → `mem_get_observation(id)` → parse YAML → restore state.

### Recovery Protocol (2 steps)

Memory lifecycle rule (when Engram exposes lifecycle metadata/tooling):
- At session start or before architecture-sensitive work, call `mem_review` with action `list` for the current project when the tool is available.
- If `mem_review` is unavailable, do not fail the task. Continue with normal `mem_context`/`mem_search`, and still apply lifecycle metadata from any returned observations when present.
- `active` memories may be used normally.
- `needs_review` memories are stale context, not trusted facts.
- Surface `needs_review` context and verify it against current evidence before relying on it.
- Do NOT call `mem_review` with action `mark_reviewed` automatically. Only call `mark_reviewed` after explicit user confirmation or through a dedicated memory maintenance command.

```
Step 1: mem_search(query: "sdd/{change-name}/{artifact-type}") → truncated preview + ID
Step 2: mem_get_observation(id: {observation-id}) → complete content
```

When retrieving multiple artifacts, group all searches first, then all retrievals:

```
STEP A — SEARCH (get IDs only):
  mem_search(query: "sdd/{change-name}/proposal", ...) → save ID
  mem_search(query: "sdd/{change-name}/spec", ...) → save ID
  mem_search(query: "sdd/{change-name}/design", ...) → save ID

STEP B — RETRIEVE FULL CONTENT (mandatory):
  mem_get_observation(id: {proposal_id})
  mem_get_observation(id: {spec_id})
  mem_get_observation(id: {design_id})
```

Loading project context:
```
mem_search(query: "sdd-init/{project}") → get ID
mem_get_observation(id) → full project context
```

### Writing SDD Artifacts

Standard write:
```
mem_save(
  title: "sdd/{change-name}/{artifact-type}",
  topic_key: "sdd/{change-name}/{artifact-type}",
  type: "architecture",
  capture_prompt: false,
  content: "{full markdown content}"
)
```

Concrete example — saving a proposal for `add-dark-mode`:
```
mem_save(
  title: "sdd/add-dark-mode/proposal",
  topic_key: "sdd/add-dark-mode/proposal",
  type: "architecture",
  project: "my-app",
  capture_prompt: false,
  content: "## Proposal\n\nAdd dark mode toggle..."
)
```

`capture_prompt: false` is REQUIRED for SDD artifacts when the Engram tool schema supports it. Engram v1.15.3 captures user prompts by default for human/proactive saves, but SDD artifacts are automated pipeline outputs. Do not infer this from `type` because both SDD artifacts and human architecture decisions use `architecture`. If an older schema rejects or does not expose `capture_prompt`, omit it rather than failing.

Update existing artifact (when you have the observation ID):
```
mem_update(id: {observation-id}, content: "{updated full content}")
```

Use `mem_update` when you have the exact ID. Use `mem_save` with same `topic_key` for upserts.

#### Browsing All Artifacts for a Change

```
mem_search(query: "sdd/{change-name}/")
→ Returns all artifacts for that change
```

### Project Name Resolution (engram v1.11.0+)

**Do not pass `project`. Engram already knows.** It resolves the project once, at
MCP startup, from the git remote of the tree it was started in, and every call
without the argument lands there. The `--project` flag and the `ENGRAM_PROJECT`
env var override that resolution; all names are normalized to lowercase and
trimmed.

Pass the argument only to reach a project other than the current one, and only
when you know that project already exists — `mem_save` refuses a name it does
not recognise rather than creating it, and the error is `unknown_project`. A
refused save is a memory lost with the turn, so the argument is the riskiest
field in the call: omitted it is always right, supplied it can only be wrong.
`mem_search` refuses the same way, and its error lists the projects that do
exist, which is the cheapest way to find the real name of one.

**A project name from another server is not a project name here.** Codebase
Memory derives its names from the filesystem path; engram derives its own from
the git remote. The same checkout is `home-serg-work-thing` to one and
`thing-api` to the other, and neither can resolve the other's spelling. Never
carry a name across from a tool that just handed you one.

If a memory is saved under a name that does not match existing observations,
engram warns about potential name drift. Use `mem_merge_projects` (MCP tool) or
`engram projects consolidate` (CLI) to merge variants.

### Upsert Behavior

Same `topic_key` + `project` + `scope` → UPDATE (overwrite), not INSERT. Previous content is lost — `revision_count` increments but old content is NOT saved. This is by design — engram is working memory, not an audit trail. For iteration history or team collaboration, use `openspec` or `hybrid` mode.

### Why This Convention

- Deterministic titles → recovery works by exact match
- `topic_key` → enables upserts without duplicates
- `sdd/` prefix → namespaces all SDD artifacts
- Two-step recovery → search previews are always truncated; `mem_get_observation` is the only way to get full content
- Lineage → archive-report includes all observation IDs for complete traceability
