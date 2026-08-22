# Codebase Memory Convention (reference documentation)

This convention applies only when the `codebase-memory` MCP tools are present in your
session. If they are absent, do not attempt them, do not claim graph evidence, and
proceed with direct file and text search instead.

This project uses `codebase-memory-mcp` to maintain a knowledge graph of the codebase.
ALWAYS prefer MCP graph tools over grep/glob/file-search for code discovery: structural
relationships, callers/callees, architecture, dependency graphs, impact analysis, and
symbol lookup.

CBM is code intelligence, not behavioral proof. It informs discovery; it never substitutes
for runtime tests, builds, or other executed evidence when behavior must be proven.

Never invoke CBM through a shell command or a hard-coded binary path — use the MCP tools
only.

## Tool Priority Order

1. `search_graph` — find functions, classes, routes, variables by pattern
2. `trace_path` — trace who calls a function or what it calls
3. `get_code_snippet` — read specific function/class source code. Use it only after
   `search_graph` has found the exact qualified name; never call it speculatively with a
   guessed name.
4. `query_graph` — run Cypher queries for complex patterns
5. `get_architecture` — high-level project summary

Use `search_code` for text patterns that are not represented well as graph symbols, and
`list_projects` alongside `index_status` to check which project's index is in scope. Use
`detect_changes` to compare current work against a base branch or previous ref and to
summarize changed surface and impact, not only as a pre-reindex check.

## Index Freshness — Repair, Don't Skip

Check `index_status` (or `list_projects`) before relying on graph evidence. A missing or
stale index is a repairable condition, not a permanent loss of capability for the session:

- **Index missing or not indexed** — run `index_repository`, then continue with CBM.
- **Graph stale** — run `index_repository` to refresh it (use `detect_changes` first to
  confirm scope when useful), then continue with CBM.
- **Genuinely unrecoverable CBM failure** — only when the repair itself fails or the MCP
  tools are unavailable, fall back to direct file or text search, stating the reason.

Do not treat "unindexed or stale" as an excuse to skip CBM. Repair it first; only an
unrecoverable failure earns the fallback.

## When to Fall Back to Direct Read/Search

- Searching for string literals, error messages, config values
- Searching non-code files (Dockerfiles, shell scripts, configs)
- A genuinely unrecoverable CBM failure, per the rule above
- When MCP tools return insufficient results after a proper attempt
- Active edits and live edited files: a file being changed in the current turn is read
  directly, because the index cannot reflect an edit that has not been indexed yet. This is
  not an unrecoverable CBM failure and reindexing does not fix it — an edit made seconds ago
  has nothing to repair.
