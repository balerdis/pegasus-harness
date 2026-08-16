---
name: session-handoff
description: "Trigger: save, load, resume, or restore session context. Manage a brief handoff.md using live context, OpenSpec, Engram, git, code, and tests."
license: Apache-2.0
compatibility: opencode
metadata:
  author: gentleman-programming
  version: "1.4"
---

## Activation Contract

- **Save:** preserve work before session change, compaction, or context loss.
- **Load:** evaluate project-root `handoff.md` before resuming.

## Hard Rules

- Use authority: code/tests > OpenSpec > Engram > `handoff.md`. Newer live evidence overrides stale evidence at any level. OpenSpec governs intent; Engram and handoff are historical until revalidated. In save mode `handoff.md` leaves this chain entirely: it is not evidence, only the file about to be replaced.
- Save uses three roles: the parent synthesizes an authoritative snapshot from its actual conversation; a fresh subagent verifies external evidence and writes from that snapshot; the parent reads back and gates success. Fresh agents have no implicit parent context.
- Before delegation, the parent snapshot MUST contain: Goal; user constraints; work completed; decisions; failures/incidents; runtime/operational evidence; pending work/blockers; exactly one next action; relevant paths/commits/branches/IDs/links; restricted/sensitive files.
- Snapshot restrictions override generic inspection: never read a restricted/sensitive file merely because it is modified, untracked, or relevant.
- Inject the complete snapshot verbatim into the writer prompt. If inline transfer is unreliable, use one secret-safe, uniquely named file in the OS temp directory or an approved temp root; pass its path explicitly, let the writer read only it as conversational evidence, and delete it after writer success or failure. Never place it in the project, use `handoff.md`, stage/commit it, retain it as memory, or hardcode a user path. Report missing files and cleanup failures.
- In delegated save mode, absent, empty, generic, or missing Goal, work completed, or exact next action means STOP: do not create/overwrite `handoff.md`; report missing parent-session context. Preserve the existing handoff whenever verification cannot safely complete; never replace it with a generic repository-only handoff.
- `handoff.md` is a photograph of one handover, not a document that accumulates. The writer composes a complete draft from the parent snapshot plus evidence it verified itself. Rewriting the old file in place is how a claim nobody re-checked survives session after session, gathering authority it never earned.
- The writer MUST NOT read `handoff.md` at all, in save mode. It is not an input, not a template, and not a tie-breaker: it is a photograph taken against a different snapshot, so it can neither confirm nor contradict a fresh fact. Live evidence is the only arbiter.
- Anything still true beyond this session belongs in a durable store: project documentation for decisions and debts, Engram for history. The handoff references it and does not restate it, and every such reference NAMES its store. Content that lives only in `handoff.md` dies with the session, and that is correct.
- The parent snapshot is incomplete by design -- it does not restate what is already known -- so replacing the handoff destroys whatever the parent did not carry. The comparison at the gate is the safety net on that destruction, not a second opinion about durability.
- The writer writes its draft to a secret-safe, uniquely named file in the OS temp directory, and does not touch `handoff.md` at all. Never draft inside the project: an exclusion covering `handoff.md` does not extend to a sibling draft, and a wide `git add` will commit it. Only after the parent gate passes does the parent replace `handoff.md` with the draft, so a failed gate leaves the previous handoff intact and no reader ever meets a half-written mixture of two sessions.
- The writer treats the snapshot as authoritative conversational evidence and independently verifies external claims. Classify claims as `parent-supplied`, `independently verified`, `Engram historical`, or `not revalidated`. Fresh external evidence may correct stale operational facts but MUST NOT silently erase parent decisions or incidents.
- Repo-clean is not session-clean. Never infer no session work from no Git changes.
- Reconcile contradictions in goal/work, branch/HEAD, remote/target baseline, deploy/sync, tests, PR/MR, blockers, and next step. Prefer authoritative fresh evidence; otherwise record unknown. History never replaces newer live facts.
- Never expose secrets, credentials, tokens, cookies, database URLs, environment values, or credential-bearing output; redact/summarize them.
- Preserve uncertainty. Unresolved gaps prohibit broad completion/validation claims. Reference, never copy, detailed OpenSpec or Engram content.
- Save MUST write, reread, and audit. During audit read `session-handoff/references/anti-stale-checklist.md`. The parent may request one corrective rewrite; a second failed gate MUST stop without save success.
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
| Writer is tempted to open `handoff.md` | Refuse. It is not an input in save mode. Ask the parent for anything the snapshot lacks. |
| Old handoff holds durable content that names no store | Parent persists it, then appends to the draft a one-line reference naming that store -- never the migrated content itself -- or states plainly that it is being dropped. Appending after the gate is not a violation: the gate passed on the draft's substance, and a reference is not the restatement it guards against. |
| Parent gate fails twice | Delete the draft; leave `handoff.md` exactly as it was; report no save success. |

## Execution Steps

### Save

1. Parent builds and validates the structured snapshot from the conversation before delegation; existing handoff and Engram are verification/history, never substitutes.
2. Fresh writer validates snapshot coverage, then inspects git branch/HEAD/status, code/tests, OpenSpec, and operational baselines.
3. Writer searches Engram with task anchors and reconciles the snapshot against live evidence. It never opens `handoff.md`.
4. Writer writes its draft to the OS temp directory, rereads it, applies the reference checklist, and returns the delegated coverage contract and the draft path. It does not touch `handoff.md`.
5. Parent reads the draft; require readable file, exact next action, critical constraints/incidents/identifiers, no fabrication/secrets, and passed snapshot coverage. Request one corrective rewrite on failure; after the second failure delete the draft, leave `handoff.md` untouched, and report no save success -- nothing was lost, because nothing was replaced.
6. Gate passed: parent compares the existing `handoff.md` against the draft. The only candidates are items present in the old and absent from the draft -- that is exactly what the replacement is about to destroy. For each, ask whether it outlives the session: judge it by its nature first (branch, HEAD, counts, open PRs and pending steps are state that ends; debts, decisions with a rationale, measured facts about a tool, and user constraints are not), then read its named store. Persist anything durable that names no store: call `mem_save` for history, or write decisions and debts directly into project documentation. Then append to the draft the one-line reference naming that store -- never the migrated content itself -- in the section whose subject it belongs to, or under `## Engram Notes` when no section fits, and let the rest go explicitly. Items present in both need nothing: the parent already carried them.
7. Migration first, replacement second, never the reverse: parent replaces `handoff.md` with the draft and deletes the draft.
8. After the replacement only, call `mem_session_summary` with a matching secret-safe summary.

### Load

1. Read `handoff.md`, git status/HEAD, referenced OpenSpec, and files in flight.
2. Use Engram only as needed. Label handoff-reported, Engram-supplied, independently verified, and not-revalidated facts.
3. Return the load report without changing state.

## Output Contract

Save handoff sections: `# Goal`, `## OpenSpec Context`, `## Session Snapshot`, `## Current State`, `## Files in Flight`, `## Changed`, `## Failed Attempts`, `## Operational Evidence`, conditional `## Diagnostic Starting Point`, `## Next Step`, `## Useful Commands`, `## Engram Notes`.

Every durable reference NAMES its store, so a later gate reads a label instead of hunting: a documentation path, `Engram #NNNN`, or an explicit `not stored anywhere`.

`Next Step` MUST contain exactly one action. `Session Snapshot` is required unless no useful work exists; report omission. Save response MUST report path, `Anti-stale audit: pass|fail`, `Engram sync: saved|unavailable|failed`, `Documentation sync: saved|unavailable|failed|not applicable`, `Draft cleanup: deleted|failed`, one next-step status, and -- from the parent's own comparison -- `Durable content migrated: none|<list with the store each went to>` and `Dropped with the session: none|<list>`.

Delegated writer MUST return exactly these coverage fields: `Parent snapshot received: yes`; `Parent snapshot coverage: passed|blocked`; `Repository verification: passed|partial|not applicable`; `OpenSpec verification: passed|partial|not applicable`; `Engram verification: passed|partial|unavailable|not applicable`; `Critical facts omitted: none|<list>`; `Old handoff read: no`; `Draft path: <absolute path>`; `Handoff write: draft only`. A blocked coverage result prohibits success, and any value other than `no` for the old handoff is a failed gate.

Load sections: `# Loaded Context`, `## Verified State`, `## Possible Staleness`, `## Recommended Next Action`, `## Before Editing`. Recommend exactly one action; do not implement it.

## References

- `session-handoff/references/anti-stale-checklist.md` - mandatory save audit checks and contradiction examples.
