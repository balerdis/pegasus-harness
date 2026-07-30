# Linux Test User Baseline

Validated on 2026-07-30 for the Phase 3 installer test account
`pegasus-harness`.

- Home: `/home/pegasus-harness`, owned by `pegasus-harness:pegasus-harness`.
- Login shell: `/bin/bash`.
- Harness configuration directories were absent.
- `opencode`, `gentle-ai`, and `codebase-memory-mcp` were absent from the login
  `PATH`.
- The account has only its primary group. Linux Mint's global sudoers policy
  exposes four hardware-maintenance commands without a password; this is an
  OS-level default, not a harness privilege or installer action.

## Phase 3 controlled-install result

On 2026-07-30, the controlled bootstrap was run for this account only. The
official OpenCode installer installed OpenCode `1.18.10`; the official
Codebase Memory MCP installer installed `0.9.0` with `--skip-config`.
Pegasus then materialized its user-local config, prompt assets, registry plugin,
generator, and non-secret environment contract.

`pegasus validate` passed as `pegasus-harness`: JSON and relative prompts were
valid, a registry was generated in a temporary project, no legacy/CodeGraph or
native-review runtime asset was present, and CBM `--help` plus a temporary
project index succeeded. OpenCode `--version` and `pegasus run -- opencode
--help` both completed without a model call. Engram, Jira, Figma, Playwright,
and a model-provider key remain deliberately external pending.

The launcher was corrected and retested from a real target login shell:
`sudo -iu pegasus-harness sh -lc 'pegasus run -- opencode --version'` returned
OpenCode `1.18.10`. The wrapper resolves the official
`~/.opencode/bin/opencode` location without relying on that location being in
the login `PATH`.

The rollback command was executed and verified to remove Pegasus-owned target
assets while preserving the installed OpenCode and CBM binaries, then the
harness was reinstalled and revalidated. No source-owner runtime path was
modified.
