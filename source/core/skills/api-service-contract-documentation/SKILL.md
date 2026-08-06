---
name: api-service-contract-documentation
description: "Trigger: documentar services, documentar servicios implementados, especificar request response, API request response contract, document API services, subamos estos services al repo, ya funcionan los services. Document verified API service contracts."
license: Apache-2.0
metadata:
  author: gentleman-programming
  version: "1.0"
---

## Activation Contract

Use when completed API services need a repository Markdown contract, including the stated Spanish and English trigger variants.

## Hard Rules

- Create one document per completed implementation session or cycle at `<active-project>/docs/services/YYYY-MM-DD-<concise-topic>.md`.
- Verify every assertion against current routes, controllers, models, tests, and applicable API documentation before writing. Do not invent fields, headers, auth, statuses, error shapes, or side effects.
- Include no secrets, credentials, tokens, real personal data, or environment values.
- Document only. Do not change application code, tests, configuration, or API behavior unless separately requested.
- Use the repository documentation language or the user's explicit language. If a project client-voice skill applies, load and follow it; do not impose a regional voice globally.

## Decision Gates

| Situation | Action |
| --- | --- |
| Fact is unverified | Omit it or use a clearly labeled placeholder only; never imply a contract. |
| Endpoint is review/status/supporting | Place it after core flow under `Servicios complementarios o de revisión`. |
| No completed service is verified | Report the gap; do not create a speculative contract. |

## Execution Steps

1. Identify the completed session scope and trace each service from route through controller/model; inspect focused tests and existing docs.
2. Document the happy path first. For each core service, state method, path, auth, headers when verified, request payload, representative successful response, actionable errors, and practical client behavior.
3. Use exactly these headings for every documented service, in this order:
   1. Para qué sirve
   2. Quién lo usa
   3. Request
   4. Response esperado
   5. Errores
   6. Qué tiene que hacer la persona usuaria de estos servicios
4. Add complementary or review endpoints only in their separate final section, with the same six-heading structure.

## Output Contract

Return the document path, verified sources, core versus complementary split, and any labeled placeholders or omitted facts.

## References

- Current project routes, controllers, models, tests, and API documentation.
