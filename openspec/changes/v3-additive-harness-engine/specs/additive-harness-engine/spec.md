# Additive Harness Engine Specification

## Purpose

Define additive releases preserving user artifacts.

## Requirements

### Requirement: Read-only detection and planning

The system MUST inspect client state without writing. Before apply, plans MUST expose selected paths/keys, identities, actions, decisions, collisions, and exclusions.

#### Scenario: Collision plan
- GIVEN a client has user content and a selected collision
- WHEN detection and planning run
- THEN content is unchanged and the collision is reported

### Requirement: V3.1 selected catalog

The catalog MUST include selected commands, `engram.ts`, notifier `@mohak34/opencode-notifier@0.2.4`, CBM, Engram, Playwright, Context7, and selected Core/SDD/context/Git/collaboration skills except `sergio-*`. It MUST exclude `tui.json`, `judgment-day`, unlisted items, and leave Zellij inert when absent.

#### Scenario: Catalog enforcement
- GIVEN selected additions and exclusions are in a payload
- WHEN catalog validation runs
- THEN additions pass and exclusions fail

### Requirement: Fixed MCP provenance and ownership

Absent CBM, Engram, and Playwright MUST expose fixed metadata; Engram MUST remain a fixed verified asset. Existing MCPs MUST be non-owning links. Context7 MUST be a user-confirmed provider-managed remote at `https://mcp.context7.com/mcp`, with no Pegasus version or integrity control.

#### Scenario: MCP policy
- GIVEN selected MCPs are absent or already installed
- WHEN planning completes and Context7 is confirmed
- THEN fixed metadata, non-owning links, and the unpinned endpoint are recorded

### Requirement: Curated CBM Linux x64 artifact

CBM MUST be a bundled static non-UI Linux x64 artifact from `DeusData/codebase-memory-mcp` v0.9.0, commit `b637e3330c96cfe452da623db068c241aaa3ec01`, tree `67ea1cdff279b0cfe0292640c624388ed9db6dce`, with repository/tag/commit/tree, builder-image/build-command digests, output path, and SHA-256 provenance. Npm, postinstall, runtime builds/downloads, and PATH lookup are prohibited.

#### Scenario: CBM validation
- GIVEN a Linux x64 release contains the CBM bundle
- WHEN release validation runs
- THEN provenance, executable status, checksum, and version probe pass

### Requirement: Approved Playwright graph and browser gate

After per-dependency confirmation, Playwright MUST use `@playwright/mcp` `0.0.79`, `playwright` and `playwright-core` `1.63.0-alpha-2026-08-05`, fixed SRIs, and explicit `https://registry.npmjs.org/` URLs; it MUST NOT inherit user registry/mirror/proxy settings. SRIs MUST be mcp=`sha512-VpqD4a3vFyGQMY9sh3UJiO6wjcurggkljKfAyCHL0QWGY5m6Ehr3MNsAAHPDHO//n13g0PCjpHatAOiulrqdZQ==`, playwright=`sha512-zbGZUK+JYkoDV3cUgfvh2czTBJL34Gmz5gHVI25xiIpvYSR17Q1M7TS8hnwECUe+IkKaeXbKrSyJTyogm2DVWw==`, core=`sha512-YussvUybTfBtyYbGXWh43f+5kNP03wg98M6mu4DphYET7PSbNVajsdLGjWE1xrsjqOw32i2wFlRP7U5mcOpMZg==`. It MUST run `npm ci --ignore-scripts` with no bundled `node_modules`, `npx`, `latest`, or browser download. External Node 24 and Chrome 151 are prerequisites; browser preflight MUST allow cancellation and external-install retry.

#### Scenario: Fixed Playwright setup
- GIVEN Playwright is confirmed and fixed manifests are present
- WHEN dependency setup runs
- THEN exact versions/SRIs use npmjs.org and `npm ci --ignore-scripts` succeeds without `npx`

#### Scenario: Browser cancellation and retry
- GIVEN external Chrome 151 is absent
- WHEN preflight informs the user, cancellation occurs, then Chrome is installed externally and retried
- THEN no partial config/artifact exists and preflight can pass

### Requirement: Granular apply and rollback

Apply MUST materialize selected artifacts only at file/key granularity, preserve user content/unrelated keys, and journal identity, release, source/hash, target/key, and baseline. Update/removal/rollback MUST require unchanged Pegasus ownership.

#### Scenario: Edited artifact
- GIVEN a journaled artifact changed after installation
- WHEN update, removal, or rollback is requested
- THEN it skips and preserves the content

### Requirement: Real isolated acceptance topology

Acceptance MUST use an archive-based immutable `v3.1.0-rc.N`. External provisioning MUST provide Node `24.15.0`, OpenCode `1.18.13`, and for Playwright Chrome 151, outside Pegasus. Each profile MUST recreate only its named user, never touch `serg`, record MCP confirmation/result/no-orphan and ownership proof, and unit tests MUST NOT recreate users. Matrix: `pegasus-harness` accepts CBM and declines others; `pegasus-harness-engram`, `-playwright`, and `-context7` accept only their MCP; `pegasus-harness-final` accepts all. Aggregate proof MUST precede immutable `v3.1.0`; failure requires a new RC tag.

#### Scenario: Matrix proof
- GIVEN an RC archive and named dedicated user/home
- WHEN external prerequisites are provisioned and that user runs the archive install
- THEN only that user is recreated, evidence is recorded, and `serg` is unchanged

#### Scenario: Final gate
- GIVEN all five profiles pass with complete evidence
- WHEN final acceptance runs
- THEN aggregate proof is recorded before immutable `v3.1.0`
