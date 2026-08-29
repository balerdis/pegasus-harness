# Proposal: V3 Additive Harness Engine

## Intent

Replace the v2 clean-install foundation with a v3 additive engine. Pegasus must augment an existing OpenCode or Claude Code setup without claiming, replacing, moving, or deleting user artifacts.

## Status

Implementation is complete for v3.1.0. RC archive generation and isolated acceptance are release operations and have not been run as part of this implementation update.

## Scope

### In Scope
- Detect installed clients, configuration, dependencies, and prior Pegasus state without writing.
- Produce an inspectable plan; confirm every absent selected MCP dependency with fixed source, version, integrity, and action before applying it.
- Merge only contract-selected artifacts at file/key granularity; maintain an artifact-level ownership journal and conservative update/removal rules.
- Retain selected payload, registry assets, and release infrastructure; introduce v3 manifest/release evidence, migration, tests, and Spanish operator documentation.

### Out of Scope
- Installing, updating, or removing OpenCode, Claude Code, Zellij, or user dependencies outside an explicitly confirmed selected MCP dependency.
- Replacing whole client directories/configuration, adopting pre-existing user files, or distributing `judgment-day`.
- Runtime feature changes to selected skills/plugins beyond safe additive packaging.

## Capabilities

### New Capabilities
- `additive-harness-engine`: detection, planning, dependency confirmation, granular merge, ownership, validation, rollback, and v2 migration.

### Modified Capabilities
None; no existing OpenSpec capability specs exist.

## Approach

Build a v3 engine around `detect → plan → confirm → apply → validate`. The plan maps each selected artifact to a target key/path and expected hash. Apply skips user collisions, creates no config for declined dependencies, and journals only successfully created Pegasus artifacts (`id`, release version, source/hash, target/key). Update, uninstall, and migration act only when the journal baseline still matches; ambiguous v2 state remains untouched. Release generation validates the contract inclusion catalog, pins/integrity metadata, and archive evidence before a `v3.1.0` annotated release.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `bin/pegasus`, `install.sh` | Modified | Replace clean-install flow with v3 additive commands. |
| `source/`, `manifests/` | Modified | Filter selected payload; add artifact/dependency catalog and v3 state schema. |
| `tools/build_release_manifest.py`, `tests/` | Modified | Prove release pins, merge, decline, ownership, migration, and rollback. |
| `README.md`, `docs/` | Modified | Practical Spanish v3 operations and migration guidance. |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| User config corruption | Med | Plan-first key/file merge; collision preservation tests. |
| Incorrect ownership cleanup | Med | Hash/key baselines; preserve on any mismatch. |
| Dependency supply-chain drift | Low | Immutable provenance/version/integrity; no `latest`. |

## Rollback Plan

Run v3 uninstall/rollback against its journal: remove only unchanged, Pegasus-created entries; preserve every other path/key. Revert to the v2 release only for clean installs; never use it to rewrite an additive v3 target.

## Dependencies

- `docs/contrato-inclusion-artifacts.md` is authoritative; each selected MCP needs release-pinned provenance and integrity metadata.

## Success Criteria

- [x] Existing OpenCode/Claude Code artifacts survive detection, apply, update, and rollback unchanged.
- [x] Plans expose all changes; declined dependencies leave no download, installation, or config reference.
- [x] Release tooling validates exact inclusion, excludes `judgment-day`, and validates v3 ownership/pins.
