---
name: prod-query-handoff
description: "Trigger: production queries, querys para producción, SQL to run in prod. Prepare one-time SQL handoff files outside the repo."
license: Apache-2.0
metadata:
  author: "serg"
  version: "1.0"
---

# Production Query Handoff

## Activation Contract

Use this skill whenever the user asks for SQL/query statements that they will execute manually in production, staging-like production, or another protected database.

## Hard Rules

- Never paste production queries only in chat. Write them to a dedicated `.sql` file and give the user the full absolute path.
- Store handoff files outside the git repository/worktree so they are never committed.
- Never reuse a query handoff file for a new execution step. Every dependent batch, follow-up batch, or post-result batch gets a new file.
- Treat user-provided execution results as belonging to the same file only when the user says they appended/pasted results there.
- Do not invent production results. Read the returned result file before deciding the next query batch.
- Prefer read-only/select queries unless the user explicitly asks for data changes. Mark destructive or mutating statements clearly.

## Decision Gates

| Situation | Action |
|---|---|
| First production query batch | Create a new file outside the repo. |
| Query depends on previous execution | Create a second file after results are reviewed. |
| Results require more investigation | Create another new file; never append new queries to the old one. |
| User asks where to run queries | Return the full path and brief execution instructions. |

## Execution Steps

1. Choose a safe directory outside the repo, preferably `/home/serg/tmp/prod-query-handoffs/{project}/`.
2. Create a uniquely named `.sql` file using timestamp or short task slug, for example `2026-07-08_check_member_status_01.sql`.
3. Add a header with project, purpose, creation time, dependency note, and a results section marker for the user.
4. Put only the current independent query batch in that file.
5. Tell the user the full absolute path and ask them to paste execution results back into the same file, below the marker.
6. When the user says execution is complete, read that same file, analyze results, and create a new file if more queries are needed.

## Output Contract

Return:
- Full absolute path to the query file.
- Whether the batch is independent or depends on a prior file.
- A short instruction for the user to paste results into the same file.
- If applicable, a warning for mutating/destructive queries.

## References

None.
