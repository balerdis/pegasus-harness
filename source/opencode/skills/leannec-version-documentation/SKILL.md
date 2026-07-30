---
name: leannec-version-documentation
description: "Trigger: custom/versiones, api/versiones, README.md, changelog.md, mysql.sql. Document Leannec releases in the user's natural style."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

# Skill: Leannec Version Documentation

## Activation Contract

Use when writing or correcting release documentation for Leannec-family projects: Leannec admin, Leannec panel, Obra Social/OS, Ospreviene, and Osfatun.

Route docs by surface:

| Change area | Documentation path |
|---|---|
| Backoffice / admin / cron / custom app | `custom/versiones/<version>/` |
| API | `api/versiones/<version>/` or the repo's existing API versiones folder |

## Hard Rules

- Preserve the user's natural, non-polished voice. Do NOT convert it into corporate/product prose.
- Use the v1.14 user-edited style as the model: practical, direct, explanatory, slightly conversational.
- Prefer explaining **why this exists** before listing files.
- Use words the user uses: `info`, `data`, `via cli php`, `cron`, `features`, `cosas a revisar`, `recapitulando`, `rollback de todo esto`.
- Keep technical paths, commands, table names, flags, and SQL names exact.
- Do not mention AI, assistants, generated content, or tooling attribution.
- For `mysql.sql`, use one short human comment describing the business purpose of the schema change; avoid meta-comments like “idempotencia” unless the user wrote them.
- Do not use older version docs as style source when the user explicitly points to a newer edited version.

## Decision Gates

| Need | Do |
|---|---|
| Explain a process | Start with the operational reason and pain avoided. |
| List deliverables | Use `### El proceso incluye estas features` and numbered `1-`, `2-` items when it fits. |
| Write README sections | Prefer `## Resumen`, `### Objetivo`, `## Componentes`, `## Comportamiento`, `## Operación`, `## resultados`, `## Recapitulando`, `## Rollback de todo esto`, `## cosas a revisar`. |
| Correct docs | Preserve voice first; only fix clarity blockers, broken commands, wrong paths, or misleading domain facts. |
| Technical precision conflicts with casual wording | Keep casual wording, but make the fact correct. |

## Execution Steps

1. Read `git status` and the current diff for the version docs being edited.
2. Identify whether the change is backoffice/custom or API and choose the correct `versiones` folder.
3. Read only the user-edited target version as style input unless the user asks for older versions.
4. Draft docs with this shape:
   - title with concrete business goal;
   - short paragraph explaining the problem/process in human terms;
   - bullets for objective;
   - component table when files/processes matter;
   - commands and cron examples exactly runnable;
   - recap/rollback/checklist in plain language.
5. Before finishing, scan for over-polished phrases and replace them with the user's natural wording.

## Output Contract

Return:

- Files created or modified.
- Any factual assumption corrected from the code/diff.
- Any remaining question that blocks accurate docs.

## References

- Current style source when present: `custom/versiones/v1.14/README.md`, `custom/versiones/v1.14/changelog.md`, `custom/versiones/v1.14/mysql.sql`.
- If the current repo does not have v1.14, use the user-edited Ospreviene reference: `/var/www/html/leannec/ospreviene/custom/versiones/v1.14/README.md`, `/var/www/html/leannec/ospreviene/custom/versiones/v1.14/changelog.md`, `/var/www/html/leannec/ospreviene/custom/versiones/v1.14/mysql.sql`.
