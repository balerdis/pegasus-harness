# Portable Configuration Contract

## Contract choice

`source/opencode/opencode.json` is a **sanitized activation template**. It is
valid JSON and uses only OpenCode-supported variable forms, but it is not an
active configuration and Phase 1 does not install it.

OpenCode supports `{file:relative/path}` references resolved relative to the
configuration file and `{env:VARIABLE_NAME}` substitutions from the OpenCode
process environment. The template deliberately does not nest those forms.

## Bootstrap materialization layout

`bin/pegasus install` preserves portable relative prompt references while
placing all referenced prompt and agent files beneath the target user's
`~/.config/opencode` directory:

```text
<config-root>/opencode.json
<config-root>/prompts/sdd/*.md
<config-root>/plugins/*.ts
<config-root>/agents/pegasus-orchestrator.md
<config-root>/agents/pegasus-AGENTS.md
```

The relative SDD prompt references resolve beneath `<config-root>`; the
installer rewrites only the two agent references to `./agents/...`, also relative
to the config file. It must not invent a root-variable syntax or assume nested
variable substitution.

The future runtime must provide these environment variables to OpenCode:

- `ENGRAM_BIN`
- `CODEBASE_MEMORY_MCP_BIN`
- `PLAYWRIGHT_MCP_CWD`
- `PEGASUS_PLUGIN_ROOT`
- `XIAOMI_API_KEY` (from secret management; never stored here)

No credential is permitted in the template or generated local contract. The
bootstrap validator checks JSON parsing, every relative prompt target, generated
registry behavior, absence of legacy/native-review runtime assets, and CBM
availability. External services without an independently configured target-user
binary, endpoint, or authentication are reported as pending warnings.
