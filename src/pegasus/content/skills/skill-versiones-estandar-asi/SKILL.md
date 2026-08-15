---
name: skill-versiones-estandar-asi
description: "Trigger: ASI versions, homologated technology, dependency version, framework version. Enforce organization-private ASI v6.4 technology policy."
license: Apache-2.0
metadata:
  author: Pegasus Harness
  version: "1.0"
---

## Activation Contract

Load this organization-private policy skill only when authorized work uses, selects, adds, upgrades, configures, scaffolds, or recommends commands for a technology named in the ASI v6.4 matrix.

## Hard Rules

- Read `skill-versiones-estandar-asi/references/version-matrix.md` before changing dependencies, runtime/build/test/tool configuration, framework scaffolding, or commands.
- Use only a listed homologated branch and its stated minimum patch. Do not select deprecated or obsolete versions for new work.
- Never infer a version from upstream releases, lockfiles, templates, or general knowledge.
- Stop and ask for clarification if a technology is absent, its version is not explicit, sources conflict, or an exception needs approval.
- For Node.js projects, use NPM only. Do not recommend or run Yarn commands.

## Decision Gates

| Condition | Required action |
| --- | --- |
| Technology has a homologated entry | Use its branch and minimum patch under the matrix rules. |
| Existing application needs Node.js 20 | Confirm it is support-only before using it. |
| New database, .NET, PostgreSQL, Nginx, or conditional product | Apply its recorded approval or justification rule; otherwise ask. |
| Technology is absent, ambiguous, or contradictory | Stop. State the gap and ask for the required ASI decision. |

## Execution Steps

1. Identify every affected runtime, framework, dependency, database, migration tool, server, OS, and design system.
2. Match each named technology against the matrix and record its provenance before editing or suggesting a command.
3. Apply the matrix's compatibility, approval, and exception rules.
4. If no exact compliant choice is available, do not scaffold, edit configuration, or recommend an install or upgrade command.

## Output Contract

Report each selected technology, approved version branch/minimum patch, source page, and any required approval. For a blocked choice, ask one precise clarification question and provide no invented version.

## References

- `skill-versiones-estandar-asi/references/version-matrix.md` - authoritative extracted ASI v6.4 matrix and document/page provenance.
- `skill-versiones-estandar-asi/references/provenance.md` - package-local provenance and distribution boundary.
