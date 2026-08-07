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

Baseline engine, payload, five-profile acceptance laboratory, its test-only aggregate promotion gate, and trusted external-browser preflight are implemented. **16/16 tasks are complete.** No runtime/local system changes were run as part of this status reconciliation.

### Completion Evidence: Playwright 0.0.79 Reconciliation (2026-08-06)

- `manifests/playwright-mcp-package.json` and `manifests/playwright-mcp-package-lock.json` declare only `@playwright/mcp@0.0.79` with the approved npmjs.org URL/SRI graph for `playwright` and `playwright-core@1.63.0-alpha-2026-08-05`.
- `bin/pegasus` validates that exact graph before and after its private staging install, isolates npm registry/user configuration, runs `npm ci --ignore-scripts`, probes the direct `@playwright/mcp/cli.js` entrypoint, and atomically promotes only the verified runtime.
- Focused offline coverage is included in `AdditiveHarnessTests.test_playwright_npm_staging_promotes_only_verified_runtime`, `test_playwright_npm_failures_leave_no_runtime_or_staging`, `test_playwright_lock_failures_leave_no_staging_destination_config_or_journal`, and `test_playwright_rejects_lifecycle_scripts_and_lock_mismatch`.
- Fresh static verification: `python3 tools/validate_snapshot.py` → `PASS: 92 selected artifacts and fixed dependency metadata are valid`; `python3 -m unittest discover -s tests` → `Ran 65 tests ... OK`; `bash -n scripts/accept-v3-isolated.sh` → exit 0. No acceptance or provisioning script was run.

### Suggested Work Units

| Unit | Goal | Commit | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | CBM/MCP integrity and Playwright lock install | Commit 1 | `python -m unittest tests.test_pegasus_bootstrap` | N/A: fixtures/temp paths | manifests, lockfile, verifier tests |
| 2 | Plan, strict compatibility, remote confirmation | Commit 2 | `python -m unittest tests.test_pegasus_bootstrap` | N/A: isolated temp homes | `bin/pegasus`, `install.sh` gates |
| 3 | Apply and ownership lifecycle | Commit 3 | `python -m unittest tests.test_pegasus_bootstrap` | N/A: isolated temp homes | applier, journal, rollback |
| 4 | Five-user RC acceptance and host provisioning | Commit 4 | `python tools/validate_snapshot.py && python -m unittest` | Manual RC only: five named users/homes | operator scripts, docs, evidence |

## Phase 1: Safety and Contract Foundation

- [x] 1.1 **RED** Lock/install fixtures cover the approved Playwright `0.0.79` graph, exact npmjs.org resolved URLs/SRIs, isolated npm registry/user configuration, `npm ci --ignore-scripts`, lifecycle/lock-drift rejection, and no `npx`/fallback behavior. Evidence: focused offline Playwright staging, failure-cleanup, lock-failure, and lifecycle/lock-mismatch tests listed above.
- [x] 1.2 **RED** threat fixtures accept only catalog-listed executable `install.sh`/`bin/pegasus`; reject executable docs/config classes, outside selectors, and non-annotated tags.
- [x] 1.3 **GREEN** `manifests/playwright-mcp-package-lock.json`, package metadata, release contract, and snapshot validator enforce Playwright `0.0.79`, the complete npmjs.org URL/SRI graph, and direct Node runtime argv. Evidence: fresh `python3 tools/validate_snapshot.py` passed with 92 selected artifacts and fixed dependency metadata.

## Phase 2: Plan-First Detection and Preflight

- [x] 2.1 **RED** test write-free detection, inspectable plans, conflict skips, and confirmation gating.
- [x] 2.2 **GREEN** `detect`/`plan`/confirm and wrapper delegation exist in `bin/pegasus`/`install.sh`.
- [x] 2.3 **RED** existing decline/browser/link tests; add strict config-shape, resolved-path, `--version`, required-probe, and Context7 confirmation/decline tests.
- [x] 2.4 **GREEN** Browser preflight/cancel/retry remains before apply; `bin/pegasus` installs the approved `0.0.79` graph only through registry- and user-config-isolated `npm ci --ignore-scripts`, validates resolved npmjs.org metadata before and after staging, probes the direct CLI, and atomically promotes the verified runtime. Evidence: fresh full offline suite passed (65 tests).

## Phase 3: Granular Apply and Lifecycle Safety

- [x] 3.1 **RED** test granular merges, apply-failure rollback, edited/uncertain ownership preservation, and unchanged-entry removal only.
- [x] 3.2 **GREEN** transactional apply, target journal, validation, uninstall, and baseline-gated rollback exist in `bin/pegasus`.

## Phase 4: Payload, Documentation, and Acceptance

- [x] 4.1 **RED** update catalog tests for `context-load`, `skill-creator`, `skill-registry`, `engram.ts`, notifier `0.2.4`, exclusions, and explicitly absent `tui.json`.
- [x] 4.2 **GREEN** baseline payload exists; add the command/plugin/catalog delta, locked notifier install, `source/opencode/plugins/engram.ts`, and remove `source/opencode/tui.json` from distribution.
- [x] 4.3 Test-only `scripts/accept-v3-isolated.sh` records the confirmed Playwright `0.0.79` graph, exact npmjs.org URLs/registry, `npm ci --ignore-scripts` result, SRI integrity, and direct-entrypoint proof in an atomic isolated evidence record.
- [x] 4.4 Keep `scripts/provision-v3-rc-host.sh` as the test-only host emulator: it recreates only the profile-mapped dedicated user after an exact acknowledgement, then installs fixed Node `24.15.0` and OpenCode `1.18.13`; it never touches `serg` and is never run from unit tests.
- [x] 4.5 Update `docs/aceptacion-rc-v3.1.md`, `docs/release-distribution.md`, and `docs/instalacion-aditiva-v3.md` with the orchestrator-only matrix commands, preflight/evidence boundaries, fixed-host behavior, non-product rule, and new-commit/new-RC rule after failure.
- [x] 4.6 Matrix verifier requires the approved Playwright graph evidence for the Playwright and final profiles, rejects stale/declined-profile graph residue, and writes aggregate promotion evidence only after all validations pass.
- [x] 4.7 Fix RC staging handoff: retain root-private verified extraction, copy only after verification into a root-owned payload below a root-controlled `/var/lib` ancestor, grant the target group read/execute only, reject unsafe archive permission bits/handoff paths, and cover offline access/ownership/refusal checks.
- [x] 4.8 Add acceptance/provision `--browser <absolute-path>` propagation to Playwright preflight. Accept only a root-owned, non-symlink regular executable and root-controlled non-writable ancestors outside the target home; preserve target-home detection as fallback and cover offline acceptance/refusals.
