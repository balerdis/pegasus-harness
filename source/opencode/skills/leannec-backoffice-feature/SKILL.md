---
name: leannec-backoffice-feature
description: "Trigger: Leannec admin, backoffice, CRUD, section, módulo admin. Implement legacy admin features following Leannec monolith conventions."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use this skill when creating or extending Leannec backoffice/admin work under `custom/admin/`: new sections, CRUDs, listados, modal actions, or section-level feature changes.

Do not use it for `ws/`, cron-only work, public web/panel, or API-global-only changes.

## Hard Rules

- Verify the owning repo before editing or committing: root, `common/`, `custom/api_global/`, and `custom/api_global/src/common/` are separate git repos.
- Default admin structure is `custom/admin/secciones/admin_{section}/admin_{section}_{controller|model|view}.php` unless local evidence proves a different convention.
- Preserve legacy contracts: `parent::__construct()`, session checks, `permisos_seccion_accion()`, `_seccion` / `_accion`, and existing AJAX/listado/modal response shapes.
- Reuse `admin_listados_controller`, `admin_formularios_controller`, `admin_layout_*`, and nearby section patterns before inventing new flows.
- Prefer additive coexistence over broad refactors.
- Avoid shared-runtime edits in `common/` or `custom/api_global/src/common/` for ordinary backoffice feature work.
- Never copy or expose secrets, credentials, tokens, or server-only config values.

## Decision Gates

| Situation | Action |
|---|---|
| New CRUD/section | Copy the closest local admin section pattern and keep naming exact. |
| Existing section with unusual constructor/permissions | Match the local section after verifying why it differs. |
| Change seems to require `common/` or API-global shared runtime | Stop and prove the feature cannot stay local before editing shared code. |
| Modal/listado/AJAX change | Verify current JSON/html response shape from a nearby working section first. |
| Validation options are unclear | Prefer narrow lint/manual route checks; avoid repo-wide tests/builds. |

## Execution Steps

1. Confirm the owning repo for every touched file.
2. Inspect a nearby `custom/admin/secciones/admin_*` section with the same interaction style.
3. Implement with strict naming, inheritance, and constructor/session/permission patterns.
4. Preserve dynamic dispatch compatibility with `_seccion` and `_accion` routes.
5. Keep listados, modals, and redirects compatible with existing helpers and response payloads.
6. Make the smallest additive change that solves the feature.
7. Validate with focused file checks, narrow PHP lint/manual verification, and git status.
8. Record non-obvious Leannec conventions, risks, or repo-boundary decisions to memory.

## Output Contract

Return:
- Files changed and owning repo.
- Routes/sections/actions added or changed.
- Constructor/session/permission conventions preserved.
- Validation performed.
- Risks or shared-runtime areas intentionally avoided.

## References

- `/var/www/html/leannec/leannec_backend/AGENTS.md`
- `/var/www/html/leannec/leannec_backend/common/AGENTS.md`
- `/var/www/html/leannec/leannec_backend/custom/api_global/AGENTS.md`
- `/var/www/html/leannec/leannec_backend/custom/api_global/src/common/AGENTS.md`
