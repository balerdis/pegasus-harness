# Proposal: V3.1.1 Release Distribution

## Intent

Publish v3.1.1 as the final, immutable release from an accepted `v3.1.1-rc.1` built from the same commit, including the current user-authored installation documentation. Consumers must be able to fetch final assets through GitHub's `releases/latest/download/...` URLs. Agent-assisted installation must establish safe local readiness without disclosing a user's full OpenCode configuration.

## Scope

### In Scope
- Build and accept immutable `v3.1.1-rc.1` from the selected v3.1.1 commit, then promote only that same commit into v3.1.1.
- Publish the final archive, checksum, and release manifest as v3.1.1 assets; verify the latest-download locators resolve to those assets.
- Update `INSTALL_BY_AGENT.md` with v3.1.1/latest asset locators and a redacted, read-only environment preflight before an agent distributes payload commands.
- Define preflight checks for user/non-root context, Python/OpenCode discovery, snapshot/archive integrity, and selected-MCP prerequisites without printing `opencode debug config` or credential-bearing configuration.

### Out of Scope
- Changes to installer behavior or executing the release. The workflow creates the final annotated tag only after accepting the same-commit RC aggregate.
- Rewriting existing user-authored documentation or exposing provider credentials, tokens, absolute config contents, or full OpenCode config.

## Capabilities

### New Capabilities
- `agent-install-readiness`: privacy-safe agent-assisted release acquisition, readiness checks, and explicit MCP decision handoff.

### Modified Capabilities
- `additive-harness-engine`: final-release distribution requirements cover v3.1.1 assets and stable latest-download resolution without altering apply or acceptance behavior.

## Approach

Treat `v3.1.1-rc.1` acceptance evidence as the promotion input. Package the selected v3.1.1 tree with the already-authored documentation into that RC, accept its own aggregate evidence, then attach the three verified final assets from the same commit to the immutable v3.1.1 GitHub release. Document stable versioned/latest URLs. The agent preflight reports only pass/fail, executable discovery path/version, safe ownership context, and requested MCP readiness; it must never dump OpenCode configuration.

## Affected Areas

| Area | Impact | Description |
|---|---|---|
| `.github/workflows/release.yml` | Modified | Final v3.1.1 asset publication contract. |
| `docs/release-distribution.md` | Modified | v3.1.1-rc.1-to-v3.1.1 promotion and asset verification. |
| `INSTALL_BY_AGENT.md` | Modified | Version/latest locators and redacted preflight. |
| `INSTALL.md`, `README.md`, `MANUAL.md`, `docs/` | Modified | Preserve and include current authored guidance. |

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Latest points at missing/wrong asset | Med | Verify versioned and latest URLs after publication. |
| Preflight leaks sensitive config | Low | Emit allowlisted facts only; never read/print config bodies. |

## Rollback Plan

Do not mutate tags or assets. Withdraw the v3.1.1 release if necessary, publish a corrected immutable patch release, and point latest through that new release.

## Dependencies

- Accepted `v3.1.1-rc.1` aggregate evidence and its exact commit.
- GitHub release permissions and final archive/checksum/manifest generation.

## Success Criteria

- [ ] v3.1.1 is promoted from accepted same-commit `v3.1.1-rc.1` and contains all intended current documentation.
- [ ] Versioned and `releases/latest/download` URLs retrieve validated final assets.
- [ ] Agent guidance performs only redacted readiness checks before command distribution.
