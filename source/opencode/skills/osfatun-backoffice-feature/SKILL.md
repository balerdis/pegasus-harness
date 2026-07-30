---
name: osfatun-backoffice-feature
description: "Trigger: Osfatun admin feature, backoffice section, CRUD, módulo admin. Create features following Osfatun legacy conventions."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use this skill when creating or extending an Osfatun backoffice feature under `custom/admin/secciones/`: new admin sections, CRUDs, list/detail screens, modal actions, or module extractions from `admin_solicitudes`.

Do not use it for API-only work under `custom/api`, global `common` changes, or generic PHP refactors.

## Hard Rules

- Verify the real owner repo before editing: root, `common`, `custom/api`, `custom/api/src/common`, or `custom/utils` may be separate Git repos.
- Do not assume parity with Ospreviene. Use it as reference only after validating Osfatun code.
- Preserve legacy inheritance: `admin_{section}_controller extends admin_layout_controller`, model extends `admin_layout_model`, view extends `admin_layout_view`.
- Keep naming exact: `custom/admin/secciones/admin_{section}/admin_{section}_{controller|model|view}.php` and classes `admin_{section}_{controller|model|view}`.
- Controllers must call `parent::__construct()`, `controlar_session()`, and `permisos_seccion_accion()` unless the local section proves a different convention.
- Use existing helpers: `admin_listados_controller`, `admin_formularios_controller`, `$this->mysql`, `$this->alertas_push()`, `$this->page()`.
- Preserve AJAX modal contracts: usually `json_encode(["status" => 1, "body" => $html, "title" => $title])` or list JSON `{status, html}`.
- Avoid broad refactors in `common`, `custom/utils`, bootstrap, or shared monolith code.
- Never expose local config values, credentials, cron secrets, or DB connection strings.

## Decision Gates

| Situation | Action |
|---|---|
| Simple CRUD | Scaffold MVC from `assets/` templates and adapt to an existing similar section. |
| Extracting from `admin_solicitudes` | Prefer additive coexistence: create new section, keep monolith intact, validate manually, then migrate navigation. |
| Shared selector/modal endpoint | Reuse or proxy first; only duplicate after proving callbacks, z-index/backdrop, and validation rules. |
| Change touches `common` or `custom/utils` | Treat as shared high-blast-radius change and inspect consumers first. |
| No product test runner | Use focused syntax checks and explicit manual validation checklist; do not run global builds. |

## Execution Steps

1. Identify surface: admin, API, cron, common, or utils.
2. Locate a local Osfatun reference section with the same interaction style.
3. Create or update MVC files using strict naming and inheritance.
4. Implement list/filter/actions first, then modal forms/detail/process actions.
5. Wire menu/redirect only after the target route loads.
6. For module extraction, preserve old routes until manual validation passes.
7. Validate with focused PHP syntax checks on changed PHP files and a manual route checklist.
8. Save non-obvious conventions, risks, or decisions to memory.

## Output Contract

Return:
- Files changed and owning repo.
- Routes added or changed.
- Permissions/menu changes.
- Manual validation checklist.
- Any compatibility wrappers or legacy routes intentionally kept.

## References

- `AGENTS.md` — Osfatun architecture, nested repos, risks, and operating rules.
- `assets/controller.template.php` — MVC controller starting point.
- `assets/model.template.php` — MVC model starting point.
- `assets/view.template.php` — MVC view starting point.
