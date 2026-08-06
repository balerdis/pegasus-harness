# Tasks: V3 Additive Harness Engine

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 950–1,250 authored lines |
| 400-line budget risk | High |
| Chained PRs recommended | Yes, but the accepted exception keeps one release line |
| Suggested split | One release line/tag `v3.1.0` with five-user RC acceptance; four work-unit commits |
| Delivery strategy | size-exception |
| Chain strategy | size-exception |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: size-exception
400-line budget risk: High

## Current Status

Baseline engine, payload, and the five-profile acceptance laboratory are implemented. **14/14 tasks are complete.** No runtime/local system changes were run as part of this update.

### Suggested Work Units

| Unit | Goal | Commit | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | CBM/MCP integrity and Playwright lock install | Commit 1 | `python -m unittest tests.test_pegasus_bootstrap` | N/A: fixtures/temp paths | manifests, lockfile, verifier tests |
| 2 | Plan, strict compatibility, remote confirmation | Commit 2 | `python -m unittest tests.test_pegasus_bootstrap` | N/A: isolated temp homes | `bin/pegasus`, `install.sh` gates |
| 3 | Apply and ownership lifecycle | Commit 3 | `python -m unittest tests.test_pegasus_bootstrap` | N/A: isolated temp homes | applier, journal, rollback |
| 4 | Five-user RC acceptance and host provisioning | Commit 4 | `python tools/validate_snapshot.py && python -m unittest` | Manual RC only: five named users/homes | operator scripts, docs, evidence |

## Phase 1: Safety and Contract Foundation

- [x] 1.1 **RED** Playwright committed-lock tests cover private-temp `npm ci --ignore-scripts`, lifecycle-script rejection, complete graph/SRI, cleanup, and atomic runtime promotion with fake local npm fixtures.
- [x] 1.2 **RED** threat fixtures accept only catalog-listed executable `install.sh`/`bin/pegasus`; reject executable docs/config classes, outside selectors, and non-annotated tags.
- [x] 1.3 **GREEN** v3 catalog/contract/tooling records the complete fixed Playwright package/lock graph and direct runtime argv; CBM provenance remains unchanged.

## Phase 2: Plan-First Detection and Preflight

- [x] 2.1 **RED** test write-free detection, inspectable plans, conflict skips, and confirmation gating.
- [x] 2.2 **GREEN** `detect`/`plan`/confirm and wrapper delegation exist in `bin/pegasus`/`install.sh`.
- [x] 2.3 **RED** existing decline/browser/link tests; add strict config-shape, resolved-path, `--version`, required-probe, and Context7 confirmation/decline tests.
- [x] 2.4 **GREEN** browser preflight/cancel/retry stays before apply; Playwright materializes only through locked `npm ci --ignore-scripts`, verified direct Node CLI execution, and atomic `node_modules` promotion.

## Phase 3: Granular Apply and Lifecycle Safety

- [x] 3.1 **RED** test granular merges, apply-failure rollback, edited/uncertain ownership preservation, and unchanged-entry removal only.
- [x] 3.2 **GREEN** transactional apply, target journal, validation, uninstall, and baseline-gated rollback exist in `bin/pegasus`.

## Phase 4: Payload, Documentation, and Acceptance

- [x] 4.1 **RED** update catalog tests for `context-load`, `skill-creator`, `skill-registry`, `engram.ts`, notifier `0.2.4`, exclusions, and explicitly absent `tui.json`.
- [x] 4.2 **GREEN** baseline payload exists; add the command/plugin/catalog delta, locked notifier install, `source/opencode/plugins/engram.ts`, and remove `source/opencode/tui.json` from distribution.
- [x] 4.3 Implement the single test-only `scripts/accept-v3-isolated.sh` orchestrator for `cbm` → `pegasus-harness`, `engram` → `pegasus-harness-engram`, `playwright` → `pegasus-harness-playwright`, `context7` → `pegasus-harness-context7`, and `final` → `pegasus-harness-final`; require explicit profile, RC archive/checksum/manifest, and exact recreation acknowledgement; record profile MCP plan/result, declined no-orphan proof, ownership, and `serg` protection.
- [x] 4.4 Keep `scripts/provision-v3-rc-host.sh` as the test-only host emulator: it recreates only the profile-mapped dedicated user after an exact acknowledgement, then installs fixed Node `24.15.0` and OpenCode `1.18.13`; it never touches `serg` and is never run from unit tests.
- [x] 4.5 Update `docs/aceptacion-rc-v3.1.md`, `docs/release-distribution.md`, and `docs/instalacion-aditiva-v3.md` with the orchestrator-only matrix commands, preflight/evidence boundaries, fixed-host behavior, non-product rule, and new-commit/new-RC rule after failure.
