---
name: laravel-security
description: "Trigger: Laravel security, secure Laravel, security audit, security review, vulnerability audit. Implement and audit Laravel applications securely."
license: Apache-2.0
metadata:
  author: "serg"
  version: "1.0"
---

## Activation Contract

Load for Laravel or PHP/Laravel work involving authentication, authorization, requests, persistence, rendering, files, integrations, deployment configuration, dependency risk, or a security review/audit.

## Hard Rules

- Treat all request, route, queue, webhook, and third-party data as untrusted.
- Enforce authorization server-side for every resource action; authentication, UI state, and model binding never prove ownership.
- Prefer framework protections and explicit allowlists. Never disable or bypass them without a documented, scoped reason.
- Do not expose secrets, credentials, tokens, passwords, PII, stack traces, or internal paths in responses, logs, commits, or test fixtures.
- In audit mode, report only evidenced findings; distinguish confirmed vulnerabilities, risks, and unverified hypotheses. Do not create an analysis file unless requested.

## Decision Gates

| Condition | Required action |
| --- | --- |
| Creates, updates, deletes, or reads a scoped resource | Validate input and prove policy/gate or equivalent ownership authorization. |
| Uses raw SQL, raw expressions, dynamic identifiers, HTML, URLs, files, or serialized payloads | Apply the relevant checklist control before proceeding. |
| Audit evidence is incomplete | State the limitation, affected code, and verification needed; do not assign a confirmed finding. |

## Execution Steps

1. Identify Laravel version, auth model, request boundary, trust boundary, and production configuration.
2. Load and apply [the local checklist](references/laravel-security-checklist.md) for the affected scope.
3. Implement the smallest secure change, or trace input, authorization, side effects, storage, and output paths during an audit.
4. Add or run focused feature tests for validation, authorization/IDOR, abuse controls, and sensitive output where applicable.
5. Review Composer lockfile and production-safe configuration when dependencies or deployment are in scope.

## Output Contract

For implementation, state controls added, tests run, and residual assumptions. For audits, list findings by severity with file/line or route, exploit preconditions, concrete evidence, impact, remediation, and verification. Report tested areas and coverage gaps.

## References

- [Laravel security checklist](references/laravel-security-checklist.md)
