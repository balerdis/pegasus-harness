# Design: V3.1.1 Release Distribution

## Technical Approach

Keep RC26 acceptance as a manual promotion input; do not alter the installer or acceptance laboratory. Extend the existing tag-bound archive/manifest builder for a final `v3.1.1` identity, publish exactly archive/checksum/manifest assets, and add a read-only agent preflight that reports only allowlisted facts. This implements the proposal; no delta spec exists yet.

## Architecture Decisions

| Decision | Choice | Alternatives / tradeoff | Rationale |
|---|---|---|---|
| Final identity | Build from annotated `v3.1.1`; manifest records final tag, tag object, commit, archive root/name/digest, installer digest, and `promotion_rc_tag: v3.1.0-rc.26`. | Reuse RC26 manifest or rename RC assets; that leaves an RC identity in final artifacts. | All three final assets must describe one immutable final tree while retaining the accepted RC provenance. |
| Preflight boundary | Add a Python, read-only, JSON-only CLI with a fixed MCP allowlist. | Agent shell snippets or `opencode debug config`; these can leak config and are harder to test. | A small deterministic interface can validate files and probe executables without reading configuration bodies. |
| GitHub latest | Publish one non-draft, non-prerelease `v3.1.1` release with final-named assets; verify versioned and `releases/latest/download` URLs by checksum and manifest identity. | Treat an RC as latest or rely on redirect alone. | GitHub computes `latest`; release metadata and asset identity must be independently proven. |
| Documentation | `INSTALL_BY_AGENT.md` is the agent entry point; `INSTALL.md`/`README.md` link to it; `docs/release-distribution.md` owns operator promotion rules. | Duplicate full procedures in every document. | One authoritative procedure prevents release/agent guidance drift. Current uncommitted docs are baseline content: edits are additive and must not rewrite or discard them. |

## Data Flow

```text
accepted RC26 evidence ──manual promotion input──> annotated v3.1.1 tag
                                              │
tagged tree ─> build_release_manifest.py ─> archive + .sha256 + manifest
                                              │
GitHub final release (not prerelease) ─> versioned/latest URLs
                                              │
agent preflight ─> allowlisted JSON ─> explicit user MCP decisions
```

## File Changes

| File | Action | Description |
|---|---|---|
| `tools/build_release_manifest.py` | Modify | Support final v3.1.1 tag/version and emit final identity/provenance while preserving RC generation. |
| `tools/agent_install_preflight.py` | Create | Validate supplied final archive/checksum/manifest, snapshot, non-root context, and explicit MCP readiness without config reads. |
| `.github/workflows/release.yml` | Modify | Define final asset build/upload metadata and non-prerelease latest semantics; retain the manual RC gate. |
| `tests/test_pegasus_bootstrap.py` | Modify | Add RED tests for final identity, preflight privacy/failures, and release/document contract. |
| `INSTALL_BY_AGENT.md`, `INSTALL.md`, `README.md`, `MANUAL.md` | Modify | Preserve current authored text; add minimal agent-preflight and canonical-document links only. |
| `docs/release-distribution.md` | Modify | Document RC26 input, final assets, immutable correction path, and versioned/latest verification. |

## Interfaces / Contracts

```sh
python3 tools/agent_install_preflight.py \
  --archive <final.tar.gz> --checksum <final.tar.gz.sha256> \
  --release-manifest <release-manifest.json> \
  --mcp <cbm|engram|playwright|context7> [--browser <absolute-path>]
```

All three asset arguments are required together. Output is one JSON object containing schema/status, final release identity, snapshot result, non-root/ownership status, requested MCP statuses, and discovered executable path/version. It MUST reject unknown/duplicate MCPs, symlinks or malformed/tampered assets, root execution, unsafe browser paths, and failed probes; it MUST emit no config path/content, environment values, credentials, tokens, `opencode debug config`, or arbitrary command output. It invokes only fixed `--version`/`--help` argv for the allowlisted local executables; Context7 is reported as an explicit remote-confirmation requirement, not configuration-inspected.

## Testing Strategy

| Layer | What to Test | Approach |
|---|---|---|
| Unit (RED first) | Final tag/archive/manifest/checksum congruence; RC compatibility; wrong tag/hash/root/asset rejection. | Existing `unittest` fixtures and dynamic tool loading. |
| Unit (RED first) | Non-root requirement, allowlist/duplicate rejection, only fixed probe argv, redacted JSON, unsafe executable/browser rejection. | Mock subprocess/environment and temporary regular/symlink files. |
| Workflow/docs | Final release is non-prerelease/latest-capable; canonical URLs and no config-dump guidance. | Static workflow/document contract assertions; no network or publish. |
| Integration | Downloaded versioned/latest assets resolve to the same validated identity. | Post-publication operator verification only; not run in this change. |

## Threat Matrix

| Boundary | Applicability | Design response / RED test |
|---|---|---|
| Documentation-like paths | N/A — docs are never classified or executed. | N/A |
| Git repository selection | Applicable — builder invokes Git. | Fixed `ROOT` cwd only; RED test asserts no caller-selected `git -C`/cwd route. |
| Commit state | N/A — no staging or commit operation. | N/A |
| Push state | N/A — no push operation. | N/A |
| PR commands | N/A — no PR operation. | N/A |

## Migration / Rollout

No data migration. Publish only after the separate manual RC26 promotion input is approved. A bad final release is withdrawn and replaced by a new immutable patch release; tags and assets are never mutated.

## Open Questions

- [ ] Confirm whether the final workflow accepts RC26 evidence as a manually reviewed input or requires a repository-stored aggregate reference; no acceptance behavior will change.
