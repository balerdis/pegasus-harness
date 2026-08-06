# Additive Harness Engine Specification

## Purpose

Define additive releases preserving user artifacts.

## Requirements

### Requirement: Read-only detection and inspectable planning

The system MUST inspect client state without writing. Before apply, the plan MUST expose every selected artifact’s path/key, identity, action, decision, collision, and exclude unapproved items.

#### Scenario: Detection and collision plan
- GIVEN a client has user content and a selected collision
- WHEN detection and planning run
- THEN content is unchanged and the collision is reported

### Requirement: V3.1 selected catalog

The catalog MUST include `context-load`, `skill-creator`, `skill-registry`, `engram.ts`, notifier `@mohak34/opencode-notifier@0.2.4`, CBM, Engram, Playwright, Context7, and selected Core/SDD/context/Git/collaboration skills except `sergio-*`. It MUST exclude `tui.json` because its plugins are absent, `judgment-day`, unlisted items, and leave Zellij inert when absent.

#### Scenario: Catalog enforcement
- GIVEN selected additions and declared exclusions are in a payload
- WHEN catalog validation runs
- THEN additions pass and exclusions fail

### Requirement: Fixed MCP provenance and ownership

Absent CBM, Engram, and Playwright MUST expose fixed version/provenance/integrity metadata; Engram MUST remain a fixed verified asset. Compatible existing MCPs MUST be non-owning links. Context7 MUST be a user-confirmed provider-managed remote MCP at `https://mcp.context7.com/mcp`; Pegasus MUST NOT control its version or integrity.

#### Scenario: MCP policy is inspectable
- GIVEN the selected MCPs are absent or already installed
- WHEN planning completes and Context7 is confirmed
- THEN fixed local metadata, non-owning links, and the unpinned Context7 endpoint are recorded

### Requirement: Curated CBM Linux x64 artifact

CBM MUST be a bundled static non-UI Linux x64 artifact from `DeusData/codebase-memory-mcp` v0.9.0, commit `b637e3330c96cfe452da623db068c241aaa3ec01`, tree `67ea1cdff279b0cfe0292640c624388ed9db6dce`. Provenance MUST record repository/tag/commit/tree, builder-image/build-command digests, output path, and SHA-256. Npm, postinstall, runtime builds, downloads, and PATH lookup are prohibited.

#### Scenario: CBM bundle validation
- GIVEN a Linux x64 release contains the CBM bundle
- WHEN release validation runs
- THEN provenance, executable status, checksum, and version probe pass

#### Scenario: Invalid CBM blocks changes
- GIVEN CBM is missing, unsupported, tampered, or probe-failing
- WHEN planning or validation runs
- THEN it blocks before configuration/journaling and preserves user content

### Requirement: Playwright package and browser gate

After independent per-dependency confirmation, Playwright MUST use fixed `package.json`/`package-lock` and `npm ci --ignore-scripts`. The release MUST NOT bundle `node_modules` or invoke `npx` at runtime. A compatible browser MUST be checked before apply; missing browsers inform the user and permit safe cancellation, not installation.

#### Scenario: Confirmed Playwright setup
- GIVEN Playwright is confirmed and its fixed manifests are present
- WHEN dependency setup runs
- THEN `npm ci --ignore-scripts` is used without bundled `node_modules` or runtime `npx`

#### Scenario: Browser cancellation and retry
- GIVEN Playwright is selected and no compatible browser exists
- WHEN the user cancels, then installs a browser externally and retries
- THEN no partial config/artifact is created and the preflight can pass

### Requirement: Granular apply and conservative rollback

Apply MUST materialize selected artifacts only at file/key granularity, preserve user content and unrelated keys, and journal created entries with identity, release, source/hash, target/key, and baseline. Update/removal/rollback MUST require unchanged Pegasus ownership.

#### Scenario: Edited artifact is preserved
- GIVEN a journaled artifact changed after installation
- WHEN update, removal, or rollback is requested
- THEN it skips and preserves the changed content

### Requirement: RC archive acceptance precedes final release

The release flow MUST create an immutable `v3.1.0-rc.N` acceptance tag from its archive before an immutable `v3.1.0` final tag. The final tag MUST be created only after `/home/pegasus-harness` passes installation from the RC archive; failure requires a new commit and RC tag, never tag mutation.

#### Scenario: RC archive acceptance
- GIVEN a candidate archive is ready
- WHEN an immutable `v3.1.0-rc.N` tag is accepted
- THEN the fresh-user installation runs from that RC archive

#### Scenario: Final tag gate
- GIVEN RC-archive acceptance passes
- WHEN final publication is authorized
- THEN immutable `v3.1.0` is created; a failure requires another RC
