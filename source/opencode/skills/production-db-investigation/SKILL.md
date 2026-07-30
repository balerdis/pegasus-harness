---
name: production-db-investigation
description: "Trigger: production DB investigation, SSH production, real data comparison, SQL filter reproduction. Investigate Leannec production read-only."
license: Apache-2.0
metadata:
  author: "serg"
  version: "1.0"
---

## Activation Contract

Use for direct production database investigation, production SSH access, real-data comparison, or reproduction of SQL filters against Leannec, Ospreviene, or Osfatun. Do not use when preparing SQL for manual user execution; use `prod-query-handoff` instead.

## Hard Rules

- Operate strictly READ-ONLY. Never correct production or invoke application tools, scripts, jobs, endpoints, hooks, events, or persistence paths.
- Require exactly one explicit target system and resolve its production host and document root from the authoritative table below before access. Require one explicit target database on that host. Do not cross hosts or databases unless explicitly necessary.
- Never expose credentials, DSNs, secrets, PII, or sensitive result values.
- Read `references/read-only-procedure.md` before any production access. It owns the SSH, bootstrap, SQL-validation, execution, and evidence procedure. If missing, unreadable, or any guard cannot be proven, stop; do not improvise.

## Decision Gates

| Gate | Action |
| --- | --- |
| Target system | Resolve exactly one allowlisted tuple: Osfatun -> `osfatun-prod` -> `~/web`; Ospreviene -> `ospreviene-prod` -> `~/web`; Obra Social / obra-social -> `obrasocial-prod` -> `~/web/www`; Leannec -> `leannec-prod` -> `~/web/www`. Never infer or derive another host or document root. |
| Target system, target DB, or bounded purpose missing or ambiguous | Ask before access. |
| SSH, deployed-code, bootstrap, or read-only guard fails | Stop closed and report. |
| Bootstrap may trigger side effects | Stop before loading or querying. |
| Statement is not provably read-only and bounded | Reject it. |

## Execution Steps

1. Confirm exactly one target system, resolve its host and document root from the decision table, then confirm target database, exact investigation purpose, identifiers, and safe output fields.
2. Follow `references/read-only-procedure.md` exactly; inspect deployed schema and code before forming assumptions.
3. Execute only the minimum bounded statements needed and record sanitized evidence.
4. Stop after diagnosis; never mutate, repair, or broaden scope.

## Output Contract

Return separate sections for facts, hypotheses, and next step. Include target system, resolved host, resolved document root, target DB, sanitized query/evidence summary, limits applied, and any stopped guard. Never include credentials, DSNs, secrets, or sensitive rows.

## References

- `references/read-only-procedure.md` - authoritative production access and read-only execution procedure.
