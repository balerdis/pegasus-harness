# Tasks: V3.1.1 Release Distribution

## Review Workload Forecast

| Field | Value |
|---|---|
| Estimated changed lines | 700–900 |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | PR 1 contracts/tests → PR 2 builder/preflight → PR 3 workflow/docs |
| Delivery strategy | ask-on-risk |
| Chain strategy | pending |

Decision needed before apply: Yes
Chained PRs recommended: Yes
Chain strategy: pending
400-line budget risk: High

### Suggested Work Units

| Unit | Goal | Likely PR | Focused test command | Runtime harness | Rollback boundary |
|---|---|---|---|---|---|
| 1 | Lock final/preflight/release contracts | PR 1 | `python3 -m unittest tests.test_pegasus_bootstrap` | N/A: RED/static fixtures only | `tests/test_pegasus_bootstrap.py` |
| 2 | Implement final manifest and safe JSON preflight | PR 2 | `python3 -m unittest tests.test_pegasus_bootstrap` | Temp archive + fake `--version` probes; no user config | `tools/build_release_manifest.py`, `tools/agent_install_preflight.py` |
| 3 | Wire gates and preserve user guidance | PR 3 | `python3 -m py_compile tools/*.py && bash -n install.sh` | N/A: no publish/network/acceptance in this change | workflow, release docs, additive doc links |

## Phase 1: Contract RED Tests

- [x] 1.1 **RED** Extend `tests/test_pegasus_bootstrap.py` for annotated same-commit `v3.1.1-rc.1` and `v3.1.1`, `promotion_rc_tag: v3.1.1-rc.1`, archive/checksum/manifest congruence, preserved authored docs, and rejection of mismatched tag/hash/manifest.
- [x] 1.2 **RED** Add preflight tests for ready non-root JSON, root/missing-prerequisite refusal, malformed/tampered/symlink/unsafe archives, unknown/duplicate MCPs, fixed probe argv, and zero config/credential leakage.
- [x] 1.3 **RED** Add workflow/document tests for exactly three final assets, non-prerelease/latest semantics, versioned/latest locator identity, v3.1.1-rc.1 aggregate gates, and model fallback/user-document preservation.

## Phase 2: Core Implementation

- [x] 2.1 Modify `tools/build_release_manifest.py` to support final `v3.1.1` while retaining RC generation and recording tag object, commit, archive identity, installer digest, provenance, and documentation evidence.
- [x] 2.2 Create `tools/agent_install_preflight.py` with required paired assets, read-only JSON output, fixed executable allowlist/probes, non-root/ownership checks, archive integrity validation, and explicit four-MCP readiness/decision boundaries.
- [x] 2.3 Modify `.github/workflows/release.yml` to publish immutable `v3.1.1-rc.1` for acceptance, then validate its aggregate before creating and publishing non-draft/non-prerelease same-commit `v3.1.1` assets.

## Phase 3: Documentation and Release Gates

- [x] 3.1 Update `docs/release-distribution.md` with v3.1.1-rc.1→v3.1.1 same-commit promotion, immutable correction path, exact assets, and post-publication versioned/latest checksum/manifest verification; do not execute it now.
- [x] 3.2 Update `INSTALL_BY_AGENT.md` with versioned/latest locators, preflight command, four independent MCP decisions, and `/connect`/`/models` deferral; add only minimal links to `INSTALL.md`, `README.md`, and `MANUAL.md`.
- [x] 3.3 Preserve all current unstaged authored guidance, including `MANUAL.md` model fallback/user control and historical-doc safety in `docs/instalacion-*.md`; do not rewrite, stage, commit, tag, push, publish, or accept.

## Phase 4: Verification Gates

- [x] 4.1 Run focused unit tests for final identity, preflight privacy/refusals, asset/latest contracts, release gates, and model fallback.
- [x] 4.2 Run syntax, snapshot, and documentation-link checks; inspect the diff to confirm no unstaged user documentation was discarded.
- [ ] 4.3 Leave operator-only acceptance/release execution pending: accepted v3.1.1-rc.1 aggregate, same-commit immutable final tag, three assets, non-prerelease latest, and byte/checksum identity must be proven before publication.
- [x] 4.4 Require and validate the accepted v3.1.1-rc.1 aggregate against downloaded RC assets before the final release upload; cover invalid aggregate refusal offline.
- [x] 4.5 Fix the final-release provenance contradiction: require immutable `v3.1.1-rc.1` built from the v3.1.1 commit, validate its own aggregate against downloaded RC assets, and preserve same-commit final promotion.
