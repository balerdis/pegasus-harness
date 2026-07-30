# CBM Index Coherence

## Scope

This reference owns the post-apply CBM index-coherence workflow. It is loaded only by the `sdd-apply` post-apply gate; it does not replace direct source inspection or runtime tests.

## Trigger Derivation

Run the gate only when at least one deterministic signal applies to the current apply batch:

- The Review Workload Forecast is High.
- Delivery is chained, stacked, or an accepted `size:exception`.
- Apply-owned files include structural or generated changes.
- Apply-owned files change a public/shared API, route, or module boundary.
- The apply-owned manifest contains five or more files.

Use the orchestrator-provided pre-apply dirty-worktree baseline and apply-owned manifest when present. A dirty global diff cannot be attributed blindly to the apply batch. Without those inputs, count only files whose ownership is clear from the assigned work and record the result as scope-limited rather than treating every local change as apply-owned.

## Index And Coverage Evidence

Check `index_status` first. Reindex with `index_repository` in `moderate` mode before collecting graph evidence. Escalate to `full` only when moderate indexing cannot provide usable structural evidence for the changed surface, and record why; do not reindex routine local edits that did not trigger this gate.

`check_index_coverage` is unavailable and MUST NOT be required. Adequate CBM evidence is `index_status` plus representative `search_graph` and/or `search_code` results for the apply-owned changed surface. Use direct files and focused tests when the graph is missing, stale, or cannot represent the relevant surface; direct inspection and tests remain authoritative.

## Apply-Progress Reporting

Persist a concise `apply-progress` coherence record: trigger signal(s), baseline/manifest source or scope limitation, indexing mode and result, `index_status`, representative query evidence, any escalation, and the direct-file/test fallback used. State `adequate`, `provisional`, or `unavailable` truthfully. Never claim index coverage from status alone.
