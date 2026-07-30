# Pegasus Harness — Portable Bootstrap

This repository is a reproducible, Pegasus-owned frozen source baseline plus a
controlled Linux bootstrap. It is never an active configuration for the source
checkout owner. The installer is explicitly targeted at one Linux user and does
not import legacy runtime assets or credentials.

## Layout

- `source/` — sanitized assets, including the layout-bound activation template.
- `manifests/` — inventory, checksums, exclusions, and integrity evidence.
- `docs/` — baseline behavior and migration constraints.
- `tools/` — snapshot validation and the Pegasus registry generator.
- `bin/pegasus` — explicit `install`, `validate`, `uninstall`, and `run` entrypoint.
- `examples/` — safe overlay examples; actual local overlays are ignored.

Run `python3 tools/validate_snapshot.py` from this repository to verify frozen
asset hashes and policy exclusions. The command reads only this repository.
Frozen Markdown assets use one terminal newline with no trailing blank EOF
lines; `baseline-manifest.json` records every intentional normalization.

Run `python3 -m unittest tests/test_pegasus_skill_registry.py` to exercise the
registry generator. Run `python3 -m unittest discover -s tests` for the
bootstrap contract tests.

## Controlled installation

From this checkout, a privileged operator installs only the named target user:

```sh
python3 bin/pegasus --target-user <linux-user> install
python3 bin/pegasus --target-user <linux-user> validate
python3 bin/pegasus --target-user <linux-user> migrate-ownership  # v1 installs only
```

The outer command enters the target account with `sudo -u <linux-user> -H`; the
OpenCode and CBM installers therefore write only user-local paths. OpenCode is
installed by its official current installer. CBM is installed using the upstream
installer with `--skip-config`, then Pegasus writes its own minimal MCP entry.

The materialized OpenCode config contains CBM and Pegasus assets only. It omits
the disabled native-review agents and optional/external MCPs. The registry plugin
is auto-discovered from the OpenCode plugin directory and receives its two-key,
non-secret local contract. It has no legacy runtime/startup dependency.

After installation, start OpenCode through the target user's wrapper so the
non-secret runtime environment is loaded:

```sh
pegasus run -- opencode
```

`~/.config/opencode/pegasus.env` documents the provider and optional MCP values.
Do not put credentials in that file: set `XIAOMI_API_KEY` (and any provider or
external MCP authentication) in the target user's secret manager or launch
environment. Engram, Jira, Figma, and Playwright remain external pending until
the target user independently provides a supported binary, endpoint, or login.
Validation does not make a model call.

`pegasus run -- opencode` resolves the official user-local OpenCode location
(`~/.opencode/bin/opencode`) directly, then falls back to `~/.local/bin` and
the current process `PATH`. It does not require a shell profile change. If no
executable is present, it reports the exact supported locations instead of
raising a Python traceback. To update only this launcher after a harness update:

```sh
python3 bin/pegasus --target-user <linux-user> refresh-launcher
```

## Rollback

Before every materialization, the installer copies any replaced target files to
`~/.local/share/pegasus-harness-backups/<UTC timestamp>/`. To remove only
Pegasus-owned files and restore the captured target files, run:

```sh
python3 bin/pegasus --target-user <linux-user> uninstall
```

It never removes unknown files in the target user's OpenCode directory and does
not uninstall OpenCode or CBM, because those binaries may be shared with later
target-user work.

The ownership manifest is file/symlink exact: user files added later beneath
`agents`, `prompts`, `plugins`, or `~/.local/bin` survive uninstall. If a
managed file has been edited, uninstall preserves it and reports a partial
result instead of overwriting or deleting it. A pre-existing `pegasus` launcher
is backed up before replacement and restored by rollback.
