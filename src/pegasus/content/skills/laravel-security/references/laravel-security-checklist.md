# Laravel Security Checklist

Use this checklist for both implementation and review. Apply controls to the actual Laravel version, authentication architecture, deployment topology, and data classification. Do not treat a passing item as proof without inspecting the relevant code and configuration.

## Secure Implementation

### Request Validation and Authorization

- Use dedicated Form Requests for externally supplied input. Define allowlisted rules, normalize only after validation, and use `validated()` or `safe()` rather than unfiltered request data.
- Implement each Form Request's `authorize()` when permission can be evaluated there. Otherwise authorize in middleware, a policy, or a gate before the action's side effects.
- Protect sensitive routes with the appropriate authentication and authorization middleware. Do not rely on hidden UI controls, client claims, route-model binding, or an identifier's obscurity.
- Create policies for model/resource actions and gates for non-model capabilities. Check the authenticated principal against the specific resolved model, including nested resources, to prevent IDOR/BOLA.
- Review bulk actions, export endpoints, relationship attach/detach operations, and background actions separately: their authorization scope often differs from a single-resource action.

### Persistence, Serialization, and Rendering

- Declare model `$fillable` deliberately, or use guarded models with explicit attribute assignment. Never pass `Request::all()` or unvetted arrays to `create`, `update`, `fill`, `forceFill`, or `updateOrCreate`.
- Avoid globally unguarding models outside tightly controlled local seeding. Ensure privileged flags, ownership keys, roles, balances, and workflow state cannot be mass assigned.
- Return API Resources or purpose-built DTOs for public responses. Set model `$hidden` for credentials and tokens, but do not rely on `$hidden` as the only response boundary; avoid serializing raw models where fields vary by audience.
- Prefer Eloquent/query-builder parameterized APIs. For `selectRaw`, `whereRaw`, `orderByRaw`, and other raw expressions, bind values and allowlist any dynamic SQL identifiers, sort fields, directions, or fragments. Bindings cannot secure identifiers.
- Use Blade `{{ }}` for untrusted output. Use `{!! !!}` only for intentionally supported HTML after context-appropriate server-side sanitization with an explicit allowed tag/attribute/protocol policy. Escape correctly for JavaScript, URLs, and attributes; do not concatenate untrusted values into executable contexts.

### CSRF, Authentication, Sessions, and Passwords

- Keep CSRF middleware enabled for browser session routes and include the framework token mechanism in state-changing forms/AJAX. Review exclusions individually; webhook endpoints need signature verification, not blanket CSRF disabling elsewhere.
- Configure production cookies as HTTPS-only, `HttpOnly` where JavaScript access is unnecessary, and an appropriate `SameSite` policy for the application's real cross-site flows. Scope cookie domain/path narrowly and rotate/regenerate session identifiers at login or privilege changes.
- Use Laravel's authentication guards/providers as designed; protect logout, email changes, credential changes, and recovery actions against CSRF and unauthorized use. Invalidate or revoke sessions/tokens according to the selected auth model.
- Use Laravel's password hashing facilities; never implement custom reversible, unsalted, or fast password storage. Use the framework password reset broker, avoid user enumeration in outward responses, validate reset flows, expire/consume reset tokens through the supported mechanism, and require reauthentication for sensitive changes when appropriate.
- Apply named rate limiters to authentication, reset, registration, verification, search, expensive operations, and public mutation endpoints. Key limits so one actor cannot trivially exhaust another's allowance, and choose limits from observed risk and product requirements rather than fixed universal values.

### Files, Paths, and External Calls

- Validate uploads by actual content, expected type, size appropriate to the product, and any dimension or structural constraints. Generate server-side filenames, store outside the web root unless public delivery is intentional, and authorize both upload and retrieval.
- Never trust client filenames, extensions, MIME headers, or paths. Block executable/active content where it can be served, prevent archive extraction hazards, and scan or quarantine files when the threat model requires it.
- Derive storage paths from trusted identifiers. Reject traversal sequences and canonicalize before verifying a path remains inside its intended base directory. Never pass user paths to filesystem, download, or archive APIs unchecked.
- For outbound HTTP, accept only configured/allowlisted schemes, hosts, ports, paths, and redirect behavior. Resolve and reject private, loopback, link-local, metadata, and otherwise disallowed destinations as appropriate to the environment; apply timeouts and response-size controls.
- Authenticate webhooks with a verified signature over the raw body, use constant-time comparison, validate timestamps/replay protection when supplied, and process idempotently. Do not treat a shared header name or source IP alone as proof.
- Validate redirect destinations against a local route or explicit allowlist. Do not redirect directly to user-supplied URLs or trust a `Referer` value.

### Queues, Configuration, and Dependencies

- Put minimal primitive identifiers in jobs where feasible; re-fetch data and repeat authorization/state checks at execution time. Treat queued payloads and failed-job storage as sensitive data stores.
- Do not deserialize untrusted PHP objects. Validate queue, webhook, and imported data into known scalar/DTO shapes; avoid user-controlled class names, callable names, or dynamic container resolution.
- Keep secrets in environment-backed secret management, never in source or client responses. Review `.env` handling, example files, CI variables, config caches, and exception/logging integrations for leakage.
- Disable debug behavior and development-only tooling in production. Use generic client errors, protect diagnostic endpoints, and redact credentials, authorization headers, tokens, passwords, and sensitive payload fields from logs.
- Commit and review `composer.lock`. Run Composer's vulnerability audit and update or mitigate known vulnerable direct and transitive packages. Review package provenance, scripts/plugins, abandoned packages, and framework/PHP support status before adding dependencies.

### Tests and Production Readiness

- Add feature tests for invalid input, unauthenticated requests, forbidden ownership/tenant access, allowed access, mass-assignment attempts, sensitive-field omission, CSRF behavior for browser routes, throttling behavior, upload rejection, and signed-webhook failures as applicable.
- Test real policy/gate paths and route middleware, not only controller helpers. Assert forbidden access without leaking resource existence where that matters.
- Verify production configuration in the deployed environment: debug disabled, secret values present but not displayed, secure URL/cookie settings, trusted proxies configured correctly, safe logging, queue worker identity/transport, storage exposure, and dependency audit status.

## Audit Procedure and Findings

### Evidence Collection

- Establish scope: Laravel/PHP versions, entry points, guards, tenancy model, roles, API/browser surfaces, queues, storage disks, external services, and production-only configuration.
- Trace each high-risk flow from source to sink: request/route/job/webhook input; validation; authentication; authorization; query/storage/outbound call; serialization/rendering/logging.
- Inspect routes, middleware registration, Form Requests, policies/gates, models/resources, controllers/actions, jobs/listeners, `config/`, `.env.example`, Composer manifests/lockfile, tests, and deployment/CI configuration when available.
- Record reproducible evidence: exact file and line/range or route/command, relevant code/config excerpt, attacker-controlled input, required account/role or network position, observed behavior, and a safe reproduction or test proposal. Redact secrets.

### Review Areas

- **Validation and IDOR:** Missing Form Request rules, direct use of request input, missing `can`/policy checks, parent-child ownership mismatches, cross-tenant queries, and unauthorized bulk actions.
- **Injection and XSS:** Raw SQL interpolation, dynamically built identifiers, unsafe raw Blade output, unreviewed HTML sanitization, unsafe URL/JavaScript contexts, and query scope bypasses.
- **Data exposure:** Mass assignment, entity serialization, resource omissions, `$hidden` gaps, debug output, exception detail, cache/queue payloads, logs, and downloadable files.
- **Browser and identity controls:** CSRF exclusions, weak cookie/session settings, login/reset enumeration, unprotected account changes, missing throttles, and improper guard selection.
- **Files and integrations:** Upload validation/storage exposure, traversal, SSRF through URLs or redirects, webhook signature/replay handling, and unsafe outbound credentials forwarding.
- **Async and supply chain:** Untrusted deserialization, jobs acting on stale authorization, failed-job secrets, unsafe queue drivers, vulnerable Composer dependencies, and unreviewed Composer scripts/plugins.
- **Deployment:** `APP_DEBUG`, public diagnostic tools, secret exposure, trusted-proxy mistakes, insecure HTTPS/cookie configuration, permissive CORS where credentials are used, and insufficient test coverage for security boundaries.

### Severity and Reporting

- Assign **Critical** when exploitation plausibly enables broad compromise, remote code execution, authentication bypass, secret exfiltration, or unrestricted access to highly sensitive data with little resistance.
- Assign **High** for a realistic, material unauthorized action/data exposure, injection, SSRF to sensitive infrastructure, or account compromise requiring limited preconditions.
- Assign **Medium** for a meaningful defense failure that needs specific conditions, limited scope, or a chained weakness.
- Assign **Low** for defense-in-depth gaps with constrained impact and no demonstrated direct exploit. Use **Informational** for observations or hardening opportunities without a vulnerability.
- For every finding, report: title; severity and rationale; affected location; evidence; attacker preconditions; impact; safe reproduction or verification steps; precise remediation; and a retest criterion.
- State audit coverage and limitations separately. Label untestable or inferred concerns as hypotheses, not confirmed findings. Do not claim compliance, exploitability, or remediation verification without evidence.
