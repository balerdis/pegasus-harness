---
name: lazy-load-prompt-audit
description: "Trigger: agent prompt, lazy-load, prompt audit, instruction refactor, contradiction, prompt length. Audit or correct prompt architecture."
license: Apache-2.0
compatibility: opencode
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Load after modifying agent or command prompts, eager/global instructions, result/status contracts, or lazy-loaded references. Also load when asked to audit or refactor prompt length, duplication, contradictions, ownership, or lazy-load architecture.

## Hard Rules

- Default to audit-only; edit only when correction is explicit or this is a post-adjustment remediation gate.
- Preserve behavior and exact wire contracts. Escalate ambiguous conflicts for human decision.
- Never repair runtime failures by appending case-specific prose. Prefer replace, generalize, or structurally extract; unjustified macro growth fails.
- Keep macros limited to identity, ownership, authorization/input/loading/delegation gates, exact references and load order, precedence, missing-reference failure, and truthful result identity.
- Audit canonical sources and never hand-edit generated copies.

## Decision Gates

| Mode | Action |
| --- | --- |
| Audit | Inspect the target macro and reference graph; report only. |
| Correct | Apply the extraction and correction algorithm, then verify fresh. |

## Execution Steps

1. Read `references/lazy-load-framework.md` before inspection or edits; fail closed if unavailable.
2. Establish canonical paths, ownership, project policy, generation pipelines, and available audit tooling.
3. Measure and audit using the framework. Prefer project tooling; for Pegasus use its instruction audit when present.
4. In Correct mode, extract coherent detail to canonical focused references, update source pipelines/tests, and rerun fresh verification after the last change.

## Output Contract


## References

- `references/lazy-load-framework.md` - authoritative audit, correction, extraction, evidence, and probe framework.
