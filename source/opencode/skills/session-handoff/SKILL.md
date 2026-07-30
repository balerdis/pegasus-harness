---
name: session-handoff
description: "Trigger: save, load, resume, or restore session context. Manage a brief handoff.md using live context, OpenSpec, Engram, git, code, and tests."
license: Apache-2.0
compatibility: opencode
metadata:
  author: gentleman-programming
  version: "1.3"
---

## Activation Contract

- **Save:** preserve work before session change, compaction, or context loss.
- **Load:** evaluate project-root `handoff.md` before resuming.

## Hard Rules

- Use authority: code/tests > OpenSpec > Engram > `handoff.md`. Newer live evidence overrides stale evidence at any level. OpenSpec governs intent; Engram and handoff are historical until revalidated.
- Save uses three roles: the parent synthesizes an authoritative snapshot from its actual conversation; a fresh subagent verifies external evidence and writes from that snapshot; the parent reads back and gates success. Fresh agents have no implicit parent context.
- Before delegation, the parent snapshot MUST contain: Goal; user constraints; work completed; decisions; failures/incidents; runtime/operational evidence; pending work/blockers; exactly one next action; relevant paths/commits/branches/IDs/links; restricted/sensitive files.
- Snapshot restrictions override generic inspection: never read a restricted/sensitive file merely because it is modified, untracked, or relevant.
- Inject the complete snapshot verbatim into the writer prompt. If inline transfer is unreliable, use one secret-safe, uniquely named file in the OS temp directory or an approved temp root; pass its path explicitly, let the writer read only it as conversational evidence, and delete it after writer success or failure. Never place it in the project, use `handoff.md`, stage/commit it, retain it as memory, or hardcode a user path. Report missing files and cleanup failures.
- In delegated save mode, absent, empty, generic, or missing Goal, work completed, or exact next action means STOP: do not create/overwrite `handoff.md`; report missing parent-session context. Preserve the existing handoff whenever verification cannot safely complete; never replace it with a generic repository-only handoff.
- The writer treats the snapshot as authoritative conversational evidence and independently verifies external claims. Classify claims as `parent-supplied`, `independently verified`, `Engram historical`, or `not revalidated`. Fresh external evidence may correct stale operational facts but MUST NOT silently erase parent decisions or incidents.
- Repo-clean is not session-clean. Never infer no session work from no Git changes.
- Reconcile contradictions in goal/work, branch/HEAD, remote/target baseline, deploy/sync, tests, PR/MR, blockers, and next step. Prefer authoritative fresh evidence; otherwise record unknown. History never replaces newer live facts.
- Never expose secrets, credentials, tokens, cookies, database URLs, environment values, or credential-bearing output; redact/summarize them.
- Preserve uncertainty. Unresolved gaps prohibit broad completion/validation claims. Reference, never copy, detailed OpenSpec or Engram content.
- Save MUST write, reread, and audit. During audit read `references/anti-stale-checklist.md`. The parent may request one corrective rewrite; a second failed gate MUST stop without save success.
- Call Engram `mem_session_summary` only after audit pass. Accurately report `unavailable` or `failed`; never imply sync. Use `mem_save` only when proactive-memory rules require it.
- Load mode is read-only: do not edit files, overwrite handoff, continue implementation, or run destructive commands without explicit user confirmation.

## Decision Gates

| Condition | Required action |
| --- | --- |
| Parent snapshot invalid in delegated save | Stop before writing; preserve existing handoff and report missing fields. |
| OpenSpec absent/misconfigured or tree clean | Report exact condition; continue from snapshot, other live evidence, and relevant Engram. Never infer no session context. |
| Operational state not freshly verified | Label `not revalidated`; do not promote history to current state. |
| Engram unavailable, not searched, or no match | Continue and report the exact condition; for no match, report queries. |
| Snapshot conflicts with external evidence | Correct stale operational state explicitly; preserve live decisions/incidents and name unresolved contradictions. |

## Execution Steps

### Save

1. Parent builds and validates the structured snapshot from the conversation before delegation; existing handoff and Engram are verification/history, never substitutes.
2. Fresh writer validates snapshot coverage, then inspects git branch/HEAD/status, code/tests, OpenSpec, and operational baselines.
3. Writer searches Engram with task anchors; reads old `handoff.md` last; reconciles claims with provenance/freshness.
4. Writer writes project-root `handoff.md`, rereads it, applies the reference checklist, and returns the delegated coverage contract.
5. Parent rereads `handoff.md`; require readable file, exact next action, critical constraints/incidents/identifiers, no fabrication/secrets, and passed snapshot coverage. Request one corrective rewrite on failure; after the second failure stop/report.
6. After parent gate passes only, call `mem_session_summary` with a matching secret-safe summary.

### Load

1. Read `handoff.md`, git status/HEAD, referenced OpenSpec, and files in flight.
2. Use Engram only as needed. Label handoff-reported, Engram-supplied, independently verified, and not-revalidated facts.
3. Return the load report without changing state.

## Output Contract

Save handoff sections: `# Goal`, `## OpenSpec Context`, `## Session Snapshot`, `## Current State`, `## Files in Flight`, `## Changed`, `## Failed Attempts`, `## Operational Evidence`, conditional `## Diagnostic Starting Point`, `## Next Step`, `## Useful Commands`, `## Engram Notes`.

`Next Step` MUST contain exactly one action. `Session Snapshot` is required unless no useful work exists; report omission. Save response MUST report path, `Anti-stale audit: pass|fail`, `Engram sync: saved|unavailable|failed`, and one next-step status.

Delegated writer MUST return exactly these coverage fields: `Parent snapshot received: yes`; `Parent snapshot coverage: passed|blocked`; `Repository verification: passed|partial|not applicable`; `OpenSpec verification: passed|partial|not applicable`; `Engram verification: passed|partial|unavailable|not applicable`; `Critical facts omitted: none|<list>`; `Handoff write: completed|not performed`. A blocked coverage result prohibits success.

Load sections: `# Loaded Context`, `## Verified State`, `## Possible Staleness`, `## Recommended Next Action`, `## Before Editing`. Recommend exactly one action; do not implement it.

## References

- `references/anti-stale-checklist.md` - mandatory save audit checks and contradiction examples.
