---
name: project-agents-bootstrap
description: "Trigger: AGENTS.md, local agent context, project map, bootstrap agents. Create local-only agent technical maps."
license: Apache-2.0
metadata:
  author: "serg"
  version: "1.0"
---

## Activation Contract

Use this skill when asked to initialize, refresh, or bootstrap local agent context for a project with a root `AGENTS.md` technical map.

## Hard Rules

- Treat `AGENTS.md` and agent/tooling artifacts as local-only unless the user explicitly asks for versioned docs.
- Add local-only excludes to `.git/info/exclude`, never `.gitignore`, unless explicitly instructed.
- Preserve user-existing changes; inspect status before edits and avoid unrelated dirty files.
- Do not commit, push, or stage changes unless explicitly requested.
- Write technical artifacts in English unless the user explicitly requests another artifact language.

## Decision Gates

| Situation | Action |
|-----------|--------|
| User wants local agent context | Create or update root `AGENTS.md` and local excludes. |
| User wants team-visible docs | Ask before using versioned files or `.gitignore`. |
| Existing `AGENTS.md` has user content | Merge carefully; preserve project-specific rules. |
| Dirty unrelated files exist | Leave them untouched and report them as pre-existing. |

## Execution Steps

1. Inspect the project stack, entry points, architecture style, informal layers, conventions, technical debt, and integrations.
2. Read existing root guidance files when present, including `AGENTS.md`, `README.md`, and major config files.
3. Write or update root `AGENTS.md` as a compact technical map for future agents: identity, quick orientation, stack, architecture, layers, patterns, watchouts, integrations, and safe-change guidance.
4. Update `.git/info/exclude` with local-only agent/tooling artifacts such as `AGENTS.md`, `.opencode/`, `.atl/`, `handoff.md`, `context.md`, and `.codebase-memory/`.
5. Verify excludes with `git check-ignore -v` for the configured patterns.
6. Verify workspace state with `git status --short` and confirm unrelated dirty files remain untouched.

## Output Contract

Return:
- Files created or modified.
- Verification commands and results.
- Pre-existing dirty state preserved.
- Any risks, assumptions, or follow-up notes.

## References

None.
