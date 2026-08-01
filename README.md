# Pegasus Harness — Portable Bootstrap

This repository is a reproducible, Pegasus-owned frozen source baseline plus a
controlled Linux bootstrap. It is never an active configuration for the source
checkout owner. The installer is explicitly targeted at one Linux user and does
not import legacy runtime assets or credentials.

## Layout

- `source/core/skills/` — canonical client-agnostic bundled skills and references.
- `source/adapters/` — minimal client instruction adapters.
- `source/` — sanitized assets, including the layout-bound activation template.
- `manifests/` — inventory, checksums, exclusions, and integrity evidence.
- `docs/` — baseline behavior and migration constraints.
- `tools/` — snapshot validation, the Pegasus registry generator, and historical evidence reporters.
- `bin/pegasus` — explicit `install`, `validate`, `uninstall`, and `run` entrypoint.
- `examples/` — safe overlay examples; actual local overlays are ignored.

Run `python3 tools/validate_snapshot.py` from this repository to verify frozen
asset hashes and policy exclusions. The command reads only this repository.
Frozen Markdown assets use one terminal newline with no trailing blank EOF
lines; `baseline-manifest.json` records every intentional normalization.

Run `python3 -m unittest tests/test_pegasus_skill_registry.py` to exercise the
registry generator. Run `python3 -m unittest discover -s tests` for the
bootstrap contract tests.

## Releases and development builds

Use a published GitHub Release for a stable installation. The latest stable
release and its checksums are available at:

<https://github.com/balerdis/pegasus-harness/releases/latest>

Each release is an immutable semantic tag (for example, `v1.1.0`). Download
the archive and verify its published checksum before installation. Do not use a
branch tip when you need a reproducible production installation.

`main` contains the current development version. It is intended for
contributors and early validation, may include unreleased changes, and is not a
replacement for a tagged release. Clone `main` only when you deliberately want
to test the next version:

```sh
git clone --branch main https://github.com/balerdis/pegasus-harness.git
```

Release lines are prepared on `stable/vX.Y.0` branches and published from their
immutable `vX.Y.Z` tags. Users consume the tag/release; the stable branch is a
maintainer workflow boundary, not an installation source.

## Controlled installation

From this checkout, a privileged operator installs only the named target user:

```sh
python3 bin/pegasus --target-user <linux-user> --client opencode install
python3 bin/pegasus --target-user <linux-user> --client claude-code install
python3 bin/pegasus --target-user <linux-user> --client all install
python3 bin/pegasus --target-user <linux-user> --client all validate
python3 bin/pegasus --target-user <linux-user> migrate-ownership  # v1 installs only
```

### Existing-user controlled migration

`install` is intentionally for a clean, Pegasus-managed target and refuses an
unmanaged OpenCode config. For an existing user, use the separate migration
path only after the harness tests pass:

```sh
python3 -m unittest discover -s tests
python3 bin/pegasus --target-user <linux-user> migrate
python3 bin/pegasus --target-user <linux-user> validate
```

`migrate` takes a UTC-named private (`0700`) backup in
`~/.local/share/pegasus-harness-backups/` before any mutation. It structurally
merges Pegasus policy into `opencode.json`: Pegasus becomes the default
orchestrator; CBM is enabled; CodeGraph and native-review agents are removed;
providers, unrelated MCP entries, unknown agents, and unrelated plugin entries
are retained without reading or reporting their secret values. It copies only
exact Pegasus-owned files (agents, commands, prompts, skills, plugins, runtime
helpers, and launcher), retaining unknown files in shared directories.

The migration state records every owned path, digest, collision backup, and
deferred rollback-window cleanup. `uninstall` is the rollback command for both
clean installs and migrations: it touches only unchanged manifest paths, then
restores their exact pre-migration collision backups. It never recursively
deletes a shared directory.

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

`~/.config/opencode/pegasus.env` documents only non-secret Pegasus runtime
values. Do not put credentials in that file: keep provider or external MCP
authentication in the target user's existing secret manager or launch
environment. Clean installs leave Engram, Jira, Figma, and Playwright external
pending; existing-user migration retains their existing config shapes.
Validation does not make a model call.

`pegasus run -- opencode` first checks the documented user-local locations
(`~/.opencode/bin/opencode`, then `~/.local/bin`), then the target environment
and the target account's login-shell `PATH`. It reports both the discovered path
and its resolved executable path; it never uses an active OpenCode process as an
installation substitute. If no executable is present, it reports the exact
locations checked instead of raising a Python traceback. To update only this
launcher after a harness update:

```sh
python3 bin/pegasus --target-user <linux-user> refresh-launcher
```

For an existing-user migration, `validate` is the current integrity check: it
checks every exact manifest-owned asset, the approved explicit JD agents,
and the provider/MCP integration names retained by migration. It reports names
only, never integration values or credentials. `tools/check_active_runtime_unchanged.py`
is a frozen **pre-migration historical capture**. Its differences are evidence
of the migration and are not a current pass/fail target; it never re-baselines
that capture.

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
