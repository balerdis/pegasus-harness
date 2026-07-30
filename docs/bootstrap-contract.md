# Bootstrap Contract

## Scope and safety

`bin/pegasus` is a Linux-only, explicit, idempotent bootstrap command. Its outer
mode requires a named target user and invokes internal work through
`sudo -u <user> -H`. It rejects a missing user/home, root internal execution,
missing `curl`/`python3`, and an unmanaged pre-existing `opencode.json` rather
than overwriting it.

Before materialization, the target-user state file records an ownership manifest
of each exact Pegasus-managed file or symlink, its content digest/link target,
and a backup for every pre-existing collision. Directories are never owned:
`agents`, `prompts`, `plugins`, and `~/.local/bin` remain shared user
directories. A directory collision where a file is required fails before any
mutation.

`uninstall` removes only a manifest entry that is still byte-identical (or an
unchanged managed symlink), then restores its exact pre-install backup if one
exists. It never recursively removes shared directories. A modified managed
file is preserved, its ownership entry remains in the manifest, and uninstall
returns a partial result so the user can restore/remove it deliberately before
retrying. OpenCode and CBM binaries are intentionally never removed.

Existing v1 installations must run `pegasus migrate-ownership` once. Migration
adopts only known Pegasus paths and retains usable legacy backups; it does not
adopt or delete extra files in shared directories. A pre-existing launcher is
backed up before replacement on every new v2 install and restored on uninstall.

## Runtime assets

The bootstrap copies only Pegasus prompts, agents, the registry plugin, and the
registry generator. It does not materialize the Engram or Zellij plugins, old
review agents, or any retired graph tooling. The generated config configures
CBM only after the official CBM installer has produced an executable.

The non-secret target environment contract is:

- `ENGRAM_BIN` — external; set after the target user installs/configures Engram.
- `CODEBASE_MEMORY_MCP_BIN` — generated to the target user's CBM binary.
- `PLAYWRIGHT_MCP_CWD` — external; set only when Playwright MCP is installed.
- `PEGASUS_PLUGIN_ROOT` — generated to the materialized plugin directory.
- `XIAOMI_API_KEY` — never written by the installer; provide through secret
  management or the target launch environment.

Jira and Figma are also external pending integrations. Their remote endpoint or
package presence is not treated as authentication. `validate` emits warnings for
these deliberately unconfigured integrations and does not claim that Engram is
installed when it is not.

## Validation and smoke test

`pegasus validate` runs as the target user. It validates config JSON and prompt
resolution, checks the registry wrapper by generating a registry in a temporary
project, rejects legacy/CodeGraph/native-review runtime references, runs CBM
`--help`, and indexes that temporary project through the CBM CLI. It performs no
LLM request and reads no credentials.

The target-user `pegasus run -- opencode` wrapper resolves OpenCode without
depending on shell initialization: executable `PATH`, then
`~/.opencode/bin/opencode` (the official installer location), then
`~/.local/bin/opencode`. `refresh-launcher` copies only the Pegasus launcher and
recreates its `~/.local/bin/pegasus` symlink; it does not rematerialize config,
prompts, plugins, OpenCode, or CBM.

`refresh-launcher` refuses a modified managed launcher. It updates only the
known launcher file after ownership migration; it does not replace an unknown
or user-modified collision.
