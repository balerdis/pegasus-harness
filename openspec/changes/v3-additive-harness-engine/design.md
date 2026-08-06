# Design: V3 Additive Harness Engine

## Technical Approach

Replace v2’s clean-only path with Python-standard-library `detect → plan → confirm → CBM/browser gates → apply → validate`. Catalog/contract are authoritative. CBM is curated Linux x64; Context7 is a user-confirmed provider-managed remote endpoint.

## Architecture Decisions

| Decision | Choice | Rejected / rationale |
|---|---|---|
| Catalog/merge | Catalog every selected file/key/digest/merge rule. Create absent JSON entries/files only; journal created-entry baselines. | No directory/config replacement; excludes `judgment-day`, `sergio-*`, unlisted assets. |
| V3.1 selection | Add `context-load`, `skill-creator`, `skill-registry`, `source/opencode/plugins/engram.ts`, and `@mohak34/opencode-notifier@0.2.4`; exclude `tui.json` because no plugin is distributed. | Implicit plugin/TUI inclusion creates broken references. |
| Curated CBM | Release CI checks out `DeusData/codebase-memory-mcp` `v0.9.0`, commit `b637e3330c96cfe452da623db068c241aaa3ec01`, tree `67ea1cdff279b0cfe0292640c624388ed9db6dce`; builds static non-UI Linux x64 and bundles it. Provenance records repository/tag/commit/tree, builder-image digest, build-command digest, output path/SHA-256. | No npm/postinstall, runtime build/download, floating source, or PATH lookup. |
| CBM failure/recovery | Non-Linux-x64, missing/non-regular/non-executable/tampered bundle, invalid provenance, or failed `--version` blocks CBM before config/journal and preserves user content. An official verified prebuilt is an explicit, separately verified recovery only: new plan and CBM-only confirmation. | No silent/automatic fallback network retrieval. |
| MCP integrity/remediation | Store verified Engram metadata. For Playwright, ship the committed lockfile and run `npm ci --ignore-scripts` only in a fresh Pegasus-owned staging directory; verify the lockfile/package tree, atomically promote it, then direct-entrypoint probe. Existing MCPs become links only after exact config shape, resolved executable, `--version`, and required probe pass. | Placeholder hashes, tarball-as-runtime, lifecycle scripts, `npx`, unverified config, reinstall/adoption/removal. |
| Context7 | Confirm `https://mcp.context7.com/mcp` independently and add only its remote config entry/journal record. Show provider-managed/no Pegasus version or integrity. | Invented pin, checksum, download, or compatibility-version claim. |
| Runtime gates | Keep `bin/pegasus` wrapper; add read-only plan, confirmations, transactional apply, validator/rollback. Missing browser blocks before writes; retry rechecks only. | No framework, browser download, or partial apply. |
| RC acceptance laboratory | `scripts/provision-v3-rc-host.sh` is the test-only destructive host emulator: it recreates only the profile-mapped dedicated user and installs fixed Node `24.15.0` and OpenCode `1.18.13`. `scripts/accept-v3-isolated.sh` is the only test-only orchestrator: explicit `--profile`, `--rc-archive`, checksum, manifest, and exact `--confirm-recreate-user` are required before preflight and provision. | No Pegasus host bootstrap, catalog entry, owned user artifact, or runtime product behavior. |

## Data Flow

```
host + target home ─> detector (no writes) ─> plan/catalog/collisions
                                            └> confirm each absent MCP
confirmed plan ─> CBM bundle/provenance + MCP compatibility gates ─> browser preflight ─> applier ─> journal ─> validator
                         │ missing ─> inform ─> cancel (no writes) | external install ─> retry
                         └─ apply failure ─> journal-guided rollback
```

Unjournaled content is user-owned. Plans expose id, target/key, action, reason, exact artifact metadata, CBM provenance/output SHA, Context7 endpoint/no-integrity state, and browser state. Any verify/extract/probe failure removes temp/created dependency paths, skips dependent config/journal, and preserves user content.

`v3.1.0-rc.N` archive + checksum + manifest → acceptance preflight → profile-mapped host recreation/provision → explicit profile MCP plan → result/no-orphan/ownership evidence → immutable `v3.1.0`. Profiles are `cbm` → `pegasus-harness`, `engram` → `pegasus-harness-engram`, `playwright` → `pegasus-harness-playwright`, `context7` → `pegasus-harness-context7`, and `final` → `pegasus-harness-final`. Failure means new commit/RC; never mutate tags.

## File Changes

| File | Action | Description |
|---|---|---|
| `bin/pegasus` | Modify | v3 commands, detector, planner, safe applier/journal/validator/rollback. |
| `install.sh` | Modify | Delegate additive plan/apply; retain argument/root/target-user boundary checks. |
| `manifests/artifact-catalog.json` | Create | Exact selected artifact and dependency/provenance catalog. |
| `manifests/release-contract.json`, `manifests/cbm-linux-x64-provenance.json` | Modify/Create | v3 pins plus curated-CBM source, builder, command, and output evidence. |
| `manifests/playwright-mcp-package-lock.json` | Modify/Create | Verified Playwright graph. |
| `scripts/acceptance_v3_contract.py`, `scripts/accept-v3-isolated.sh`, `scripts/provision-v3-rc-host.sh` | Create/Modify | Test-only RC preflight, single acceptance orchestrator, and fixed-host emulator; none are Pegasus payload. |
| `docs/aceptacion-rc-v3.1.md` | Create | Five-profile laboratory and evidence contract. |
| `.github/workflows/release.yml` | Create | RC archive build, pinned Linux x64 CI/provenance, acceptance-gated final release. |
| `source/opencode/`, `source/core/skills/`, `source/adapters/` | Modify | Contract-selected payload only. |
| `tools/build_release_manifest.py`, `tools/validate_snapshot.py` | Modify | Validate archive, catalog, provenance, pins, hashes, exclusions, modes. |
| `tests/test_pegasus_bootstrap.py` | Modify | Engine unit/integration and adversarial tests. |
| `README.md`, `docs/instalacion-aditiva-v3.md`, `docs/release-distribution.md` | Modify/Create/Modify | Spanish operator and migration/acceptance handoff. |

## Interfaces / Contracts

`CbmProvenance = {repository, tag, commit, tree, platform, builder_image_digest, build_command_sha256, output_path, output_sha256}`. `DependencyEntry` contains exact source/version/integrity/archive layout/runtime argv; `McpLink` adds `{resolved_path, probe_result, ownership:false}`. `RemoteMcp = {endpoint, provider_managed:true, integrity:null}`. Journal remains target-owned; malformed/missing state is unowned.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit | Exact metadata, safe archive members, Playwright lock/`npm ci --ignore-scripts`, links, Context7 | RED rejects placeholders, traversal/symlinks, lock drift, lifecycle scripts, failed probes, remote version/integrity claims. |
| Integration | Plan/gates/apply/rollback | Tampered CBM/Engram/Playwright or incompatible existing MCP cleans temp/owned paths and leaves no config/journal; Context7 decline leaves no remote entry. |
| Release | RC → final | CI publishes `v3.1.0-rc.N` archive/provenance; only a passing fresh-user archive acceptance promotes the same verified artifact/commit to `v3.1.0`. |
| Rollout | Five dedicated homes | Profiles: `cbm` → `pegasus-harness`; `engram` → `pegasus-harness-engram`; `playwright` → `pegasus-harness-playwright`; `context7` → `pegasus-harness-context7`; `final` → `pegasus-harness-final`. Each confirms only its mapped MCP plan, declines the remainder, proves no-orphans/ownership and unchanged `serg`; scripts have no defaults and never run in automated tests. |

## Threat Matrix

| Boundary | Applicability | Design response / planned RED test |
|---|---|---|
| Documentation-like paths | Applicable: release executable classification | Safe: only catalog-listed regular `install.sh`/`bin/pegasus` are executable. Failure: reject `requirements.txt`, `CMakeLists.txt`, executable Markdown/MDX, `README.sh`. RED: one fixture per class. |
| Git repository selection | Applicable: release builder reads an annotated tag | Safe: fixed `ROOT` cwd and annotated tag only. Failure: reject relative/absolute outside selectors and non-annotated tags. RED: one fixture per selector. |
| Commit state | N/A: no commit operation | No commit argv or test required. |
| Push state | N/A: no push operation | No remote/ref resolution or test required. |
| PR commands | N/A: no PR operation | No composed PR argv or test required. |

## Migration / Rollout

v2 state is ambiguous: detect/report only; rollback is journal/baseline-gated. Release order is RC archive → five-user acceptance matrix → aggregate proof → `v3.1.0` from the accepted commit/artifact evidence. No design-time provisioning or acceptance action.

## Open Questions

None.
