# Pegasus Skill Registry Migration

## Runtime contract

`tools/pegasus-skill-registry` is a standard-library Python wrapper. It accepts
one target project and one or more ordered skill roots:

```sh
tools/pegasus-skill-registry \
  --project-root /path/to/project \
  --skill-root /path/to/project/skills \
  --skill-root /path/to/user/skills
```

It recursively discovers `SKILL.md`, extracts only scalar or folded `name` and
`description` frontmatter fields, and atomically writes
`<project-root>/.atl/skill-registry.md`. Rows are sorted by skill name; roots
are scanned in CLI order, but that order is only a tie-breaker. For duplicate
names, a valid path under `--project-root` always wins over any user/global
path, regardless of root order. Within the same scope, the earliest supplied
root wins; duplicate paths in one root resolve by lexical path order. Invalid,
missing, unreadable, or unsafe frontmatter is not a candidate, so it cannot
hide a valid duplicate in another root. Every rejected candidate produces a
deterministic stderr warning while other skills continue. The registry has no
cache and emits no timestamps, which makes identical inputs produce identical
output.

The output preserves the consumer-facing table and loading protocol: `Skill`,
`Trigger / description`, `Scope`, and exact `SKILL.md` `Path`. It deliberately
does not persist to Engram; the existing skill workflow may save this generated
index separately when that service is available. It deliberately excludes
`_shared`, `skill-registry`, and `sdd-*` directories to retain the current
Pegasus registry contract. It does not reproduce cache or `.gitignore`
behavior because neither is required by the current consumer contract.

## Future OpenCode plugin contract

`source/opencode/plugins/pegasus-skill-registry.ts` is an auto-discovered
plugin template. It is not listed in the frozen `opencode.json`. Its runtime
contract uses these environment variables:

- `PEGASUS_SKILL_REGISTRY_BIN`: absolute or `PATH`-resolvable wrapper command.
- `PEGASUS_SKILL_ROOTS`: one or more skill-root paths separated by the host
  platform path delimiter (`:` on POSIX, `;` on Windows).

Process environment values take precedence. For a current-user, no-config
activation, the plugin also reads only those two unset keys from
`$XDG_CONFIG_HOME/opencode/pegasus-skill-registry.env` (or
`~/.config/opencode/pegasus-skill-registry.env` when `XDG_CONFIG_HOME` is
unset). The file is a two-key, unquoted `KEY=value` contract, not an OpenCode
configuration field and not a shell profile. This avoids unsupported
`opencode.json` environment syntax while making the auto-discovered plugin
self-contained. The file must contain no credentials.

The plugin derives the target project from OpenCode's directory/worktree input,
prepends conventional project skill roots (`skills`, `.opencode/skills`, and
`.opencode/skill`), then invokes the configured wrapper asynchronously with
explicit arguments. This lets project-local duplicates win over configured
user/global roots. It logs a skipped refresh when configuration is absent and
logs failures without blocking startup.

## Cutover and rollback

Before cutover, run the focused test suite and generate a registry in a
non-active fixture project. Materialize the wrapper and plugin in the active
auto-discovery layout, configure both environment variables through process
environment or the documented local contract file, and verify startup produces
the expected project-local `.atl/skill-registry.md`.

Rollback restores the previous auto-discovered plugin and removes only the
local contract file and materialized generator directory. The generator never
changes OpenCode configuration, skill sources, caches, or active project
registries by itself.
