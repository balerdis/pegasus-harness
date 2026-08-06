# Additive Harness Engine Specification

## Purpose

Define additive releases preserving user artifacts.

## Requirements

### Requirement: Read-only detection and inspectable planning

The system MUST inspect client state without writing. Before apply, the plan MUST expose selected paths/keys, identities, actions, decisions, collisions, and unapproved exclusions.

#### Scenario: Collision plan
- GIVEN a client has user content and a selected collision
- WHEN detection and planning run
- THEN content is unchanged and the collision is reported

### Requirement: V3.1 selected catalog

The catalog MUST include `context-load`, `skill-creator`, `skill-registry`, `engram.ts`, notifier `@mohak34/opencode-notifier@0.2.4`, CBM, Engram, Playwright, Context7, and selected Core/SDD/context/Git/collaboration skills except `sergio-*`. It MUST exclude `tui.json`, `judgment-day`, unlisted items, and leave Zellij inert when absent.

#### Scenario: Catalog enforcement
- GIVEN selected additions and exclusions are in a payload
- WHEN catalog validation runs
- THEN additions pass and exclusions fail

### Requirement: Fixed MCP provenance and ownership

Absent CBM, Engram, and Playwright MUST expose fixed version/provenance/integrity metadata; Engram MUST remain a fixed verified asset. Existing MCPs MUST be non-owning links. Context7 MUST be a user-confirmed provider-managed remote at `https://mcp.context7.com/mcp`; Pegasus MUST NOT control its version or integrity.

#### Scenario: MCP policy
- GIVEN selected MCPs are absent or already installed
- WHEN planning completes and Context7 is confirmed
- THEN fixed metadata, non-owning links, and the unpinned endpoint are recorded

### Requirement: Curated CBM Linux x64 artifact

CBM MUST be a bundled static non-UI Linux x64 artifact from `DeusData/codebase-memory-mcp` v0.9.0, commit `b637e3330c96cfe452da623db068c241aaa3ec01`, tree `67ea1cdff279b0cfe0292640c624388ed9db6dce`. Provenance MUST record repository/tag/commit/tree, builder-image/build-command digests, output path, and SHA-256. Npm, postinstall, runtime builds/downloads, and PATH lookup are prohibited.

#### Scenario: CBM validation
- GIVEN a Linux x64 release contains the CBM bundle
- WHEN release validation runs
- THEN provenance, executable status, checksum, and version probe pass

### Requirement: Playwright package and browser gate

After per-dependency confirmation, Playwright MUST use fixed `package.json`/`package-lock` and `npm ci --ignore-scripts`; no bundled `node_modules` or runtime `npx` is permitted. A browser MUST be checked before apply; missing browsers inform the user, allow cancellation, and support external-install retry without Pegasus installation.

#### Scenario: Playwright dependency and browser proof
- GIVEN Playwright is confirmed and its browser is absent
- WHEN fixed dependency setup and preflight run
- THEN `npm ci --ignore-scripts` is used, no orphan config/artifact exists after cancellation, and external installation enables retry

### Requirement: Granular apply and conservative rollback

Apply MUST materialize selected artifacts only at file/key granularity, preserve user content/unrelated keys, and journal identity, release, source/hash, target/key, and baseline. Update/removal/rollback MUST require unchanged Pegasus ownership.

#### Scenario: Edited artifact
- GIVEN a journaled artifact changed after installation
- WHEN update, removal, or rollback is requested
- THEN it skips and preserves the content

### Requirement: Real isolated acceptance topology

Acceptance MUST use an archive-based immutable `v3.1.0-rc.N` install. `scripts/provision-v3-rc-host.sh` MUST remain the test-only fixed-host emulator: after an exact recreation acknowledgement, it recreates only the profile-mapped dedicated user and provides Node `24.15.0` and OpenCode `1.18.13` outside Pegasus. `scripts/accept-v3-isolated.sh` MUST be the single test-only orchestrator: it requires explicit `--profile`, `--rc-archive`, checksum, manifest, and exact recreation acknowledgement; validates the RC checksum/manifest before calling the provisioner; runs Pegasus with the profile's explicit confirm/decline plan; and records selected result, declined absence/no-orphans, target ownership, and `serg` protection. Unit tests MUST NOT execute subprocess/user operations. Matrix: `cbm` → `pegasus-harness` accepts CBM and declines Engram/Playwright/Context7; `engram` → `pegasus-harness-engram` accepts only Engram; `playwright` → `pegasus-harness-playwright` accepts only Playwright; `context7` → `pegasus-harness-context7` accepts only Context7; `final` → `pegasus-harness-final` accepts all selected MCPs. Unknown profiles, unsafe names/homes, non-RC archives/tags, and absent acknowledgements MUST be refused. The laboratory MUST NOT be installed, cataloged as owned, or treated as Pegasus runtime product code. Failure requires a new commit/RC tag, never tag mutation.

#### Scenario: Per-MCP isolated proof
- GIVEN an RC archive and its named dedicated user/home
- WHEN the external host is provisioned and that user runs the archive install
- THEN only that user is recreated, its decisions/proofs/ownership are recorded, and `serg` is unchanged

#### Scenario: Final aggregate gate
- GIVEN all five matrix users pass and their evidence is complete
- WHEN final release acceptance runs
- THEN the test-only matrix verifier accepts explicit RC archive/checksum/manifest identity and an outside-`/home` evidence directory, requires exactly one valid JSON `PASS` record for `cbm`, `engram`, `playwright`, `context7`, and `final`, rejects duplicate/missing/failed/mismatched identity records, and writes one aggregate proof before immutable `v3.1.0` is created
