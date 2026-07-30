---
name: leannec-obra-social-api-service
description: "Trigger: Ospreviene obra-social API, ApiLeannec, X-Authorization, medicamentos service. Trace and implement Leannec cross-system API services."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use this skill when Ospreviene, Osfatun, or another Leannec project calls the Obra Social API through `ApiLeannec`, `ApiTroop`, `_URL_API`, `X-Authorization`, or routes like `/api/v1/{group}/`.

Do not assume the implementation lives in the caller repo. The caller usually wraps a service owned by `/var/www/html/leannec/obra-social/custom/api`.

## Hard Rules

- Identify the caller wrapper and the real API owner before editing.
- Treat the caller repo, `obra-social/`, and `obra-social/custom/api/` as separate git repos.
- Never copy real credentials, tokens, private URLs, or production headers into code, docs, tests, memories, or replies.
- Preserve API response field names and shapes; downstream backoffices depend on them.
- Prefer fixing the service endpoint in Obra Social API over patching caller-side fallbacks, unless the endpoint is unavailable or the behavior is caller-specific.
- Read project and nested `AGENTS.md` before touching a repo.

## Decision Gates

| Situation | Action |
|---|---|
| Caller uses `ApiLeannec::{method}` or `ApiTroop::get/post/put` | Trace route path and headers, then inspect Obra Social API implementation. |
| Endpoint exists in `obra-social/custom/api/public/v1/{group}` | Patch router/controller/model owner there. |
| Behavior is only presentation-specific | Patch caller-side view/controller after proving API contract should stay unchanged. |
| Change spans caller + service repos | Validate and publish each owning repo separately. |
| Need a request example | Use sanitized local curl placeholders; never include real secrets. |

## Execution Steps

1. In the caller repo, find the wrapper method (`custom/includes/ApiLeannec.php`, section controller, or service class) and record the HTTP method/path.
2. Map the path to Obra Social API: `/var/www/html/leannec/obra-social/custom/api/public/{version}/{group}/{group}_{router|controller|model}.php`.
3. Check git status/branch in every repo that may be touched.
4. Implement the smallest compatible change in the owning model/controller.
5. Validate with `php -l`, focused caller tests if available, and a sanitized local smoke request suggestion.
6. Report rollout order when multiple repos must be deployed.
7. Save non-obvious route ownership or contract discoveries to Engram.

## Output Contract

Return:
- Caller wrapper path/method and resolved API route.
- Owning repo and files changed.
- Contract fields preserved or added.
- Validation performed and smoke suggestion.
- Publish order across repos.

## References

- `/var/www/html/leannec/ospreviene/AGENTS.md`
- `/var/www/html/leannec/obra-social/AGENTS.md`
- `/var/www/html/leannec/obra-social/custom/api/AGENTS.md`
