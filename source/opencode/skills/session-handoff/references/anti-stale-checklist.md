# Anti-Stale Audit

Use this checklist after writing and rereading `handoff.md`.

## Required Checks

- Every continuation-critical fact agrees with reconciled `live_session_facts` or is explicitly unknown/not revalidated.
- `Session Snapshot`, `Current State`, operational evidence, blockers, and `Next Step` agree.
- Branch, HEAD, remote/target baseline, deploy/sync state, tests, and PR/MR status use the freshest available evidence and identify its source.
- Historical Engram or handoff evidence is not presented as current without independent revalidation.
- Successful later evidence supersedes earlier pending, failed, or timed-out state.
- Work already completed is not described as absent, pending, or the next action.
- Unresolved gaps do not coexist with broad complete, validated, or end-to-end claims.
- Exactly one concrete `Next Step` remains.
- Required sections exist; the diagnostic section appears only when useful.
- No secret or credential-bearing value appears.

## Failure Handling

Name each contradiction and perform at most one corrective rewrite. Reread the complete file and run every check again. If any contradiction or hard-rule violation remains, stop, report `Anti-stale audit: fail`, do not claim save success, and do not call `mem_session_summary`.
