# Lazy-Load Prompt Audit Framework

## Scope

This reference governs audits and safe corrections of agent prompts, command prompts, eager or global instructions, result/status contracts, and lazy-loaded instruction graphs. It applies across projects; project policy and project-specific deterministic tooling override its default budgets, never its preservation and evidence requirements.

## Authority

This file is the canonical owner of the detailed audit, extraction, correction, incident, evidence, and verification procedure for `lazy-load-prompt-audit`. The primary `SKILL.md` owns activation, mode selection, hard gates, and the output contract. Do not duplicate these detailed procedures into a target macro.

## Macro Versus Reference

| Concern | Macro may own | Focused reference owns |
| --- | --- | --- |
| Identity and role | Agent identity, role, concern ownership | Role-specific workflow and examples |
| Authorization and input | Gates deciding whether work or loading may occur | Derivation, validation, recovery, and normalization |
| Loading and delegation | IF a reference or delegate is allowed/required; exact path, WHEN, load order | HOW work runs after the gate opens |
| Conflict handling | Precedence and ambiguous-conflict escalation | Detailed reconciliation procedure |
| Missing content | Required-path fail-closed behavior | Recovery mechanics for optional resources |
| Results | Exact result identifier and truthfulness requirement | Status/readiness state machine, persistence, schemas, transport |
| Domain behavior | Only a compact gate that controls whether execution occurs | Workflow, edge cases, examples, exact literals, and recovery |

Gate details may remain inline only when they determine IF loading, work, or delegation occurs. Move derivation, persistence, recovery, transport, schemas, examples, edge cases, and readiness/status mechanics to a focused canonical owner.

## Default Role Budgets

Project policy overrides these defaults. Measure the primary prompt body, excluding frontmatter where applicable.

| Role | Lines | Words | Estimated tokens |
| --- | ---: | ---: | ---: |
| Router or dispatcher | 45 | 450 | 600 |
| Specialist agent | 80 | 800 | 1,050 |
| Command entry prompt | 40 | 400 | 525 |
| Eager/global instruction | 70 | 700 | 925 |

Estimate tokens as `ceil(words * 1.33)` unless project tooling provides a tokenizer. A budget breach is evidence of risk, not permission to delete semantics.

## Smells And Severity

| Smell | Severity | Required response |
| --- | --- | --- |
| Broken required reference, load cycle, hand-edited generated copy, false result/status, changed wire literal | Critical | Block correction success; restore canonical behavior and verify |
| Contradictory normative rules, capability-role mismatch, eager loading of phase/detail references, ambiguous ownership | High | Correct only when authority is clear; otherwise request human decision |
| Duplicate normative rule, stale rule, macro over budget, package/template/generated mismatch | Medium | Replace, generalize, extract, or regenerate from canonical source |
| Orphan optional reference, verbose example, weak WHEN wording | Low | Consolidate or clarify without changing behavior |

Macro growth without removal or generalization of equivalent text fails unless the report records a measured exception, its necessity, and why extraction would weaken a gate.

## Audit Procedure

1. Record mode, target macro, canonical source, runtime/package copies, generators, tests, project policy, and forbidden paths.
2. Measure baseline lines, words, and estimated tokens. Record project budget and role classification.
3. Parse every explicit reference path and load condition. Build directed edges from macros and references to their required or optional dependencies.
4. Walk the graph without broad eager loading. Check missing paths, unreadable required paths, cycles, orphan references, and references loaded before their gate.
5. Map each normative concern to one owner. Detect repeated MUST/NEVER/required semantics, near-duplicate paraphrases, stale rules, and conflicting precedence.
6. Check the macro against the decision table. Flag workflow, persistence, readiness/status, schemas, examples, edge cases, recovery, or transport detail left inline.
7. Verify every tool/capability mentioned belongs to the executing role and every delegation gate matches available capabilities.
8. Compare canonical sources with templates, package manifests/assets, generated/runtime copies, and tests. Determine the generation command; do not hand-edit outputs.
9. Run project-specific audit tooling first. For Pegasus, use `tests/audit_instruction_architecture.py` or `tests/smoke.sh audit-instructions` when present. Remain generic elsewhere.
10. Report findings by severity with exact path and line, owner, behavioral risk, and safe remediation. Audit mode stops here.

## Extraction And Correction Algorithm

1. Reconfirm explicit correction authority. Treat post-adjustment remediation invocation as Correct mode.
2. For each misplaced detail block, search nearby and project references plus the ownership map before creating anything.
3. Reuse an existing canonical owner when it covers the concern. Do not duplicate the rule.
4. Otherwise create one focused `.md` reference in the established project taxonomy. If no taxonomy exists, use a sibling `references/<concern>.md` subdirectory; use the macro directory only when project convention requires it.
5. Add explicit `Scope` and `Authority` sections. Move, rather than summarize, all semantics, edge cases, exact literals, wire labels, precedence, and failure behavior belonging to the concern.
6. Replace the old block with a short instruction naming the exact path, WHEN it must be read, the concern it owns, and fail-closed behavior if a required path is missing or unreadable.
7. Remove overlapping normative text from the macro and other non-owners. Keep one canonical owner and references to it.
8. Group a coherent concern per file. Never fragment one sentence, case, or literal into its own reference.
9. Update canonical source pipelines, package manifests/assets, generated copies through their generator, and tests as applicable. Never hand-edit generated copies.
10. Measure after changes and compare with baseline. Macro growth requires the measured exception described above.
11. Run negative probes and project audits after the final edit. If verification changes files, rerun against that new final state. Do not rerun after a final no-change verification pass.
12. Report every moved rule, old location, new owner/path, macro replacement, metrics, generation action, and verification result.

## Macro Replacement Pattern

Use a compact instruction shaped like this:

> When `<condition>`, read `<exact/path.md>` before `<work>`. It owns `<concern>`. If this required path is missing or unreadable, stop and return `<exact blocked result>`; do not infer, search for substitutes, or proceed.

Preserve the project's exact blocked result and wire labels. Do not invent them.

## Incident Handling

Runtime failure is evidence of a missing or incorrect generalized contract, not a reason to append the observed case. Reproduce and classify the failure, trace it to the canonical owner, then replace, generalize, or extract the governing rule. Preserve the incident's exact literals in the owning reference or tests when they are part of the contract. If two authoritative rules conflict and precedence does not resolve them, stop and request a human decision.

## Negative Probes

- Remove or rename a required reference in an isolated fixture; the macro must fail closed without searching for substitutes.
- Trigger a condition that should not load a reference; prove the reference remains unloaded.
- Introduce an isolated cycle; deterministic audit must reject it.
- Place the same normative rule in macro and reference; duplication audit must reject it.
- Alter an exact result/status or transport label; contract tests must fail.
- Give a role an unavailable tool or delegation action; capability audit must reject it.
- Change only a canonical template; generation/package checks must detect stale copies before regeneration and equivalence afterward.

Never mutate production inputs to run a negative probe. Use fixtures, temporary copies, or existing self-test modes.

## Package And Generated Checks

Identify canonical source, generator, generated destination, package inclusion rule, and runtime installation path. Verify:

- generated and packaged copies derive from the canonical source;
- every required reference is included at the same relative path;
- no orphan or stale reference is shipped;
- templates, global installations, and alternate runtime formats preserve exact semantics and wire labels;
- tests exercise both source-tree and independently built package artifacts when the project supports packaging.

Run generation through the canonical command. A textual difference is acceptable only when the format intentionally differs and contract-equivalence tests prove semantics.

## Evidence Template

```markdown
Mode: Audit | Correct
Scope: <canonical macro and graph roots>
Role/budget: <role; project or default budget>
Before: <lines> lines, <words> words, <estimated tokens> tokens
After: <lines> lines, <words> words, <estimated tokens> tokens
Delta: <signed values and justified exception, if any>

Findings:
- <severity> <path:line> - <smell, owner, risk, disposition>

Moved rules:
- Rule: <preserved normative behavior and exact literals>
  Old location: <path:lines>
  New owner: <path and section>
  Macro replacement: <exact compact instruction>

Graph: <broken/orphan refs, cycles, eager loads, ownership result>
Equivalence: <template/generated/package/runtime result>
Verification: <commands and fresh results>
Human decisions: <ambiguous conflicts or none>
skill_resolution: <loaded skill path and mode>
```

## Examples

### Bad: Append-Only Incident Patch

```markdown
Run the deployment workflow.
If status says READY but upload failed with E_UPLOAD_17, retry twice, rewrite the manifest,
clear the cache, and return upload_partial unless the mirror also failed.
```

This grows the macro with case-specific workflow, recovery, status, and transport mechanics.

### Good: Structural Extraction

Primary prompt:

```markdown
When deployment is authorized, read `references/deployment-transport.md` before acting.
It owns upload status, recovery, and transport literals. If required and unreadable,
stop and return `blocked-missing-reference`; do not infer or proceed.
```

`references/deployment-transport.md`:

```markdown
# Deployment Transport

## Scope
Own upload status, retries, manifest recovery, cache handling, and mirror transport.

## Authority
Canonical owner of `READY`, `E_UPLOAD_17`, `upload_partial`, and related behavior.

When status is `READY` but upload fails with `E_UPLOAD_17`, retry twice, rewrite the
manifest, clear the cache, and return `upload_partial` unless the mirror also failed.
```

The correction preserves every semantic and exact literal while leaving only the loading gate and truthful blocked result in the macro.
