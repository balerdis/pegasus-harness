"""How Claude Code spells what the content core means.

Every table in this module is a translation from an agnostic concept to a
Claude Code name. This is the only place those names are allowed to appear.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pegasus.core import placeholders
from pegasus.core.content import (
    Agent,
    Command,
    DENY_FLOOR_DIRECTORIES,
    Distribution,
    Mcp,
    Skill,
    SystemPrompt,
    delegation_capabilities_path,
    mcp_convention_path,
)
from pegasus.core.dependencies import npm_script_path, program_path
from pegasus.core.identity import Identity
from pegasus.core.types import Artifact, ConfigKeyArtifact, FileArtifact, Layout, ModelAssignment

#: Claude Code's exact, case-sensitive tool names. This is the entire native
#: tool vocabulary in shipped content: the union of `requires_tools` and
#: `optional_tools` across every agent this repository ships (verified by
#: reading all sixteen). A name outside this table is not "close enough" --
#: Claude Code matches tool names literally -- so `_tools_field` raises
#: rather than let an unmapped name pass through unnoticed.
TOOL_NAME: dict[str, str] = {
    "read": "Read",
    "write": "Write",
    "edit": "Edit",
    "bash": "Bash",
    "grep": "Grep",
    "glob": "Glob",
    "ask": "AskUserQuestion",
    "skill": "Skill",
}


#: Measured live against a throwaway user on 2026-09-27, not assumed from the
#: documentation (see this product's 7.3.0 architecture-doc section for the
#: full account): with these two rules under `permissions.allow` in Claude
#: Code's own `settings.json` -- the leading `//` anchors the pattern at the
#: filesystem root rather than at the working directory -- a Read or Edit
#: outside the current working directory proceeds without a prompt. This is
#: Claude Code's own equivalent of the product decision already taken for
#: OpenCode's `external_directory` baseline (`adapters/opencode/render.py`,
#: `EXTERNAL_DIRECTORY_TOOLS`'s own docstring): external directories are
#: allowed by default, in both CLIs alike.
#:
#: `Write(...)` is deliberately never one of these two rules, and must never
#: be added: Claude Code's own permission docs say a `Write(path)` rule is
#: never consulted at all -- only `Edit(...)`, which the same docs say also
#: covers the Write tool -- so a `Write(...)` entry here would be dead
#: configuration a person could mistake for a second guard.
#:
#: `permissions.additionalDirectories` is deliberately not used anywhere in
#: this module either: measured the same day, it only grants reads, never
#: writes, so it cannot stand in for these two rules, and Pegasus never
#: writes it.
PERMISSIONS_ALLOW: tuple[str, ...] = ("Read(//**)", "Edit(//**)")

#: Claude Code's own translation of `content.DENY_FLOOR_DIRECTORIES` -- the
#: one CLI-agnostic list of five always-denied directory names every
#: adapter's own floor derives from -- into this runtime's own permission
#: rule vocabulary, rather than a second, independently-typed list of the
#: same five words (see `DENY_FLOOR_DIRECTORIES`'s own docstring for why
#: that would be a silent way for the two adapters to drift apart).
#:
#: Measured live on 2026-09-27: a `permissions.deny` rule of this shape
#: blocks Read, Edit/Write, AND a Bash `cat` of the same path -- verified for
#: `.ssh`, `.config/gh` (two path segments) and `secrets`. Two rules per
#: directory, `Read(...)` then `Edit(...)`, because Claude Code has no
#: single wildcard-keyed permission the way OpenCode's `external_directory`
#: is -- `Read` and `Edit` are separate permission families here, and `Edit`
#: again covers Write, the same fact `PERMISSIONS_ALLOW` already relies on.
PERMISSIONS_DENY_FLOOR: tuple[str, ...] = tuple(
    rule for name in DENY_FLOOR_DIRECTORIES for rule in (f"Read(//**/{name}/**)", f"Edit(//**/{name}/**)")
)

#: A `git push` asks the person -- the 7.5.0 product decision, recorded in
#: `docs/arquitectura/arquitectura.md`. Claude Code's permissions are per
#: session, never per agent (agent frontmatter can only grant `tools:` or
#: remove them with `disallowedTools:`, never "ask"), so this rule also asks
#: for the coordinator's own pushes: that is this CLI's limit, not a choice.
#:
#: Syntax per https://code.claude.com/docs/en/permissions ("Wildcard
#: patterns", "Compound commands", "What a Bash rule doesn't match"): `*` may
#: sit anywhere, and a trailing ` *` also matches the bare command, so
#: `Bash(git push *)` covers `git push` and `git push origin main`; `:*` is
#: only an equivalent spelling of that trailing wildcard, and the dialog
#: itself writes the space form. Ask rules apply when ANY subcommand of a
#: compound command matches (`cd x && git push`, `$(git push)` included).
#: The docs say `git -C . push` is not matched by the first rule, so the
#: second and third add `git <anything> push` with and without arguments.
#: Still not caught: `/usr/bin/git push`, `sh -c 'git push'`, aliases, and
#: `gh` commands. `git * push *` over-asks for lines like `git log --grep
#: push x`, a false positive and never a miss.
PERMISSIONS_ASK: tuple[str, ...] = ("Bash(git push *)", "Bash(git * push *)", "Bash(git * push)")

#: Explicit ids: `_permission_slug` drops `*`, so these three rules would
#: otherwise all slug to the same `Bash-git-push`.
_ASK_IDS: tuple[str, ...] = ("git-push", "git-any-push-args", "git-any-push")

_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def _permission_slug(rule: str) -> str:
    """A short, readable id fragment for one permission rule string.

    Not guaranteed unique by construction the way a hash would be -- unique
    across the fixed, small set this module actually renders, which
    `test_claudecode_permissions.py` pins with its own uniqueness check.
    Collapsing every run of non-alphanumeric characters to one `-` keeps a
    directory name's own letters (`ssh`, `aws`, `config`, `gh`, ...) legible
    in a journal dump instead of hiding them behind escaped parentheses and
    slashes.
    """
    return _NON_ALNUM.sub("-", rule).strip("-")


def permission_artifacts(layout: Layout) -> list[Artifact]:
    """The fixed `permissions.allow`/`deny`/`ask` entries this adapter
    owns in `settings.json`, one `ConfigKeyArtifact` per rule.

    Each is an *append* -- its pointer ends in `/-` -- the same mechanism
    `core.planner` already gives every other list Pegasus contributes to
    without claiming the whole array (see `system_prompt`'s own
    `/instructions/-` entry above, or OpenCode's `/mcp/<id>` siblings, for
    the same pattern in this codebase already). An append is identified by
    its own fingerprint (`target`, `pointer`, `digest`), never by position or
    by owning the array, so the person's own `permissions.allow`/`deny`
    entries -- present before install, or added by hand afterward -- are
    never touched, and `install`/`update` writing this twice never
    duplicates a rule. `doctor` reports drift the same generic way it
    already does for any other appended entry (`planner.
    record_append_identity`, `cli._digest_of_config_key`); nothing there had
    to learn about permissions specifically.

    These artifacts are this adapter's implementation of the product
    decision recorded in `docs/arquitectura/arquitectura.md`'s 7.3.0
    section: external directories are allowed by default in Claude Code,
    the same decision already taken for OpenCode, with the same fixed
    five-directory floor (`content.DENY_FLOOR_DIRECTORIES`) still denied
    regardless of that default.
    """
    allow = [
        ConfigKeyArtifact(
            id=f"own:permission-allow:{_permission_slug(rule)}",
            path=layout.settings_file,
            pointer="/permissions/allow/-",
            value=rule,
        )
        for rule in PERMISSIONS_ALLOW
    ]
    deny = [
        ConfigKeyArtifact(
            id=f"own:permission-deny:{_permission_slug(rule)}",
            path=layout.settings_file,
            pointer="/permissions/deny/-",
            value=rule,
        )
        for rule in PERMISSIONS_DENY_FLOOR
    ]
    ask = [
        ConfigKeyArtifact(
            id=f"own:permission-ask:{slug}",
            path=layout.settings_file,
            pointer="/permissions/ask/-",
            value=rule,
        )
        for slug, rule in zip(_ASK_IDS, PERMISSIONS_ASK, strict=True)
    ]
    return [*allow, *deny, *ask]


class RenderError(ValueError):
    """The content asks for something this CLI has no name for."""


def skill(layout: Layout, item: Skill) -> list[Artifact]:
    """Skills travel verbatim: Claude Code reads the same SKILL.md format."""
    return [
        FileArtifact(
            id=f"skill:{item.name}:{asset.relative_path}",
            path=layout.skills_dir / item.name / asset.relative_path,
            content=asset.content,
            executable=False,
        )
        for asset in item.assets
    ]


def agent(
    layout: Layout,
    item: Agent,
    assignment: ModelAssignment | None = None,
    mcp: tuple[Mcp, ...] = (),
) -> list[Artifact]:
    """One file per agent, `agents_dir / <name>.md`, frontmatter over the body.

    Every agent renders here the same way regardless of `item.mode`: Claude
    Code has one session identity, not a `primary`/`subagent` split at the
    file level. `content.py` keeps declaring `mode: primary` for the two
    agents that carry it because that is the fact about them; how that fact
    is spelled for one particular CLI is this adapter's job, never the
    content core's. For Claude Code the answer lives in `adapter.own_
    artifacts`, not here: the session-starting agent
    (`content.SESSION_STARTS_IN`) becomes the CLI's single session identity
    through `settings.json`'s `agent` key, and any other `primary` agent (the
    content core ships exactly one: `king-pegasus`) is demoted to an ordinary
    delegation target with no special file shape of its own -- it renders
    through this same function, indistinguishable on disk from a subagent.
    That demotion happens in the adapter, never in the content core, because
    it is a fact about how *this* CLI expresses "the session runs as", not
    about what `king-pegasus` *is*.

    `assignment`, when given, names a model at the one field Claude Code's
    schema has for it. `assignment.model_id` is written, not `assignment.
    full_id`: Claude Code's `model:` field takes a bare alias (`sonnet`,
    `opus`, `haiku`, `fable`, `inherit`) or a bare model id, never a
    provider-qualified one -- `ModelAssignment` carries `provider_id`
    separately because a *machine's* resolved preference needs it (to tell
    two providers' same-named models apart), but that provider qualifier has
    nowhere to land in this CLI's own vocabulary. Dead code today:
    `per_agent_model=False` means the engine always calls this with `None`,
    so `assignment` is kept, per the port's signature, and handled without
    inventing a default for the day this capability might exist.

    `mcp` is this agent's own resolved grant -- see `ports.cli_adapter.
    CliAdapter.render_agent`'s own docstring for why Claude Code, unlike
    OpenCode, needs the descriptors themselves rather than a bare id: a
    sub-agent's `mcpServers:` frontmatter is the only documented in-tree
    place a server can be scoped to less than every session, so the
    definition has to travel here rather than sit once at the top of the
    tree. `_mcp_servers_field` and `_disallowed_tools_field` are what turn
    those descriptors into this CLI's own two frontmatter keys.
    """
    fields: dict[str, Any] = {"name": item.name, "description": item.description}
    fields["tools"] = _tools_field(item, mcp)
    servers = _mcp_servers_field(layout, mcp)
    if servers:
        fields["mcpServers"] = servers
    disallowed = _disallowed_tools_field(mcp)
    if disallowed:
        fields["disallowedTools"] = disallowed
    if assignment is not None:
        fields["model"] = assignment.model_id
    return [
        FileArtifact(
            id=f"agent:{item.name}",
            path=layout.agents_dir / f"{item.name}.md",
            content=(_frontmatter(fields) + "\n" + _agent_body(layout, item)).encode("utf-8"),
            executable=False,
        )
    ]


#: How to spell each distribution mechanism as one Claude Code `mcpServers`
#: entry value -- the inline definition documented at code.claude.com/docs/
#: en/sub-agents.md ("Scope MCP servers to a subagent"), same schema as a
#: `.mcp.json` entry. `stdio` is the type both `download` and `npm` resolve
#: to: both start a local process, and Claude Code's own `command`/`args`
#: split is exactly the `argv` split `Mcp` already carries, unlike OpenCode's
#: single combined `command` array (`opencode.render.MCP_VALUE`). `remote`
#: maps to `http`, the general-purpose remote type this schema documents
#: (`sse` is its legacy predecessor); no server this project ships needs
#: bespoke headers, the same fact `opencode.render.MCP_VALUE`'s own `REMOTE`
#: entry already states for the identical reason.
#:
#: Keyed by `Distribution`, exactly like `opencode.render.MCP_VALUE`, and
#: guarded by the same import-time invariant just below it: a member the
#: core grows without a matching entry here must fail at import, not produce
#: a silently wrong subagent file in a user's installation.
MCP_VALUE: dict[Distribution, Any] = {
    Distribution.REMOTE: lambda item, layout: {"type": "http", "url": item.endpoint},
    Distribution.DOWNLOAD: lambda item, layout: {
        "type": "stdio",
        "command": str(_download_command(layout, item)),
        "args": list(item.argv),
    },
    Distribution.NPM: lambda item, layout: {
        "type": "stdio",
        "command": str(_npm_command(layout, item)),
        "args": list(item.argv),
    },
}

_UNMAPPED_DISTRIBUTIONS = [item for item in Distribution if item not in MCP_VALUE]
if _UNMAPPED_DISTRIBUTIONS:
    raise RenderError(
        "no Claude Code value for distribution(s): "
        + ", ".join(sorted(item.value for item in _UNMAPPED_DISTRIBUTIONS))
    )


def _download_command(layout: Layout, item: Mcp) -> Path:
    if layout.dependencies_dir is None:
        raise RenderError(f"{item.name}: this layout has no dependencies directory")
    return program_path(layout.dependencies_dir, item)


def _npm_command(layout: Layout, item: Mcp) -> Path:
    if layout.dependencies_dir is None:
        raise RenderError(f"{item.name}: this layout has no dependencies directory")
    return npm_script_path(layout.dependencies_dir, item)


def _mcp_servers_field(layout: Layout, mcp: tuple[Mcp, ...]) -> list[Any]:
    """One `mcpServers:` list entry per server this agent was granted.

    A bound server (`item.is_bound`) contributes only a bare string naming
    the key it already runs under -- Claude Code's own "already-configured
    server" spelling -- because Pegasus never fetches or defines it: writing
    a second, inline definition beside the one the installation already
    administers under that key is exactly the collision `opencode.render.mcp`
    already refuses for the identical reason (see its own docstring). An
    unbound server -- one Pegasus itself obtains -- contributes the inline
    form instead, the only shape that can carry a definition at all: there is
    no session-wide location inside `~/.claude/` this adapter could point a
    bare reference at (see `manifest.py`), which is the whole reason this
    parameter exists.
    """
    return [
        server.bound_to if server.is_bound else {server.name: MCP_VALUE[server.distribution](server, layout)}
        for server in mcp
    ]


def _disallowed_tools_field(mcp: tuple[Mcp, ...]) -> str:
    """`disallowedTools`, Claude Code's own way to take back part of a grant.

    Built straight from each granted server's own `withheld_tools`, never by
    parsing `Agent.denied_mcp_tools` back apart: that field is already
    qualified as `<key>_<tool>` with a single underscore, which cannot be
    split unambiguously the moment a key itself contains one (see `Agent.
    denied_mcp_tools`'s own docstring). `mcp` already carries the same fact
    in its own, unambiguous shape -- one descriptor, one `withheld_tools`
    tuple of bare names, one resolved key (`bound_to or name`) -- so this
    reads directly from that instead of re-deriving anything from a string.

    Named `mcp__<key>__<tool>`, Claude Code's own documented qualification
    for an MCP tool, with the double underscore this CLI uses and no other
    adapter in this codebase does -- OpenCode's own `f"{key}_{tool}"` shape
    (`opencode.render._tools`) is a different vocabulary for the identical
    fact, never reused here.

    Rendered as a comma-separated string, the same shape `_tools_field`
    already writes `tools` in: Claude Code's own frontmatter documents both
    as a plain list, spelled as prose, not as a YAML list of scalars.
    """
    names = [
        f"mcp__{server.bound_to or server.name}__{tool}"
        for server in mcp
        for tool in server.withheld_tools
    ]
    return ", ".join(names)


def mcp(layout: Layout, item: Mcp) -> list[Artifact]:
    """The server's usage convention, as a shared skill file -- and nothing else.

    Unlike OpenCode, this never writes the server's own settings key: Claude
    Code's per-agent `mcpServers:` frontmatter (`agent`/`_mcp_servers_field`
    above) is where a definition lives for this CLI, granted per agent
    through `core.catalog.render`'s own `mcp` parameter, not once globally
    the way OpenCode's `/mcp/<id>` settings key is. So the only artifact left
    for this function to produce is the convention itself.

    The convention still has to be written, though, and by this function:
    it is CLI-agnostic prose, and an agent's own ambient half
    (`Agent.mcp_sections`, composed into the agent's body by `_agent_body`)
    points at it by the exact path `mcp_convention_path` names, through the
    same `{{skills_root}}/_shared/mcp/<id>-convention.md` lazy-load reference
    every adapter's bodies use (see `content._MCP_REFERENCE_PATTERN`). Not
    writing it here would leave that pointer dangling for every Claude Code
    installation that grants the server -- the CLI reads a dead reference
    with no way to tell that from an author's own mistake.

    A bound server still gets its convention written, the same as an
    unbound one: `_mcp_servers_field` is what stops rendering a second
    *definition* for a bound server, and that reasoning has nothing to do
    with whether its usage convention should exist.
    """
    return [
        FileArtifact(
            id=f"mcp-convention:{item.name}",
            path=_convention_path(layout, item),
            content=_body(layout, item.body, item.name).encode("utf-8"),
            executable=False,
        )
    ]


def _convention_path(layout: Layout, item: Mcp) -> Path:
    """Where a server's convention lands, inside this layout's skills root.

    Identical to `opencode.render._convention_path`: the layout inside the
    content tree (`_shared/mcp/<id>-convention.md`) is the core's call, made
    once in `mcp_convention_path`; this adapter's job stays answering where
    the skills root itself lives on disk.
    """
    if layout.skills_dir is None:
        raise RenderError(f"{item.name}: this layout has no skills directory")
    return layout.skills_dir / mcp_convention_path(item.name)


def _delegation_tools_cell(target: Any) -> str:
    """A target's native-tool column, spelled exactly as `_tools_field` spells
    the same names for a real agent file: `TOOL_NAME` is looked up here too,
    the one and only tool vocabulary this adapter ever writes, so a delegator
    reading `Bash` in this table and `Bash` in `disallowedTools`/`tools:` is
    reading the identical fact both times, never a second table's own guess
    at the same name.

    Raises the same `RenderError` `_tools_field` would for a name outside
    `TOOL_NAME`: a delegation target is a real shipped agent (`content.
    catalog._delegation_targets` only ever selects those), so an unmapped
    name here is exactly as much an authoring bug as it would be in that
    agent's own rendered file, and deserves the identical loud failure.
    """
    names = sorted({*target.requires_tools, *target.optional_tools})
    unknown = [name for name in names if name not in TOOL_NAME]
    if unknown:
        raise RenderError(
            f"{target.name}: no Claude Code name for tools {', '.join(sorted(unknown))}"
        )
    return ", ".join(TOOL_NAME[name] for name in names) or "none"


def _delegation_mcp_cell(target: Any) -> str:
    """A target's MCP column, one entry per server key in `target.mcp`.

    `target.withheld_mcp_tools` is the same already-associated (key, tools)
    fact `opencode.render._mcp_cell` reads -- `core.catalog` decided which
    withheld tool belongs to which server key, and this function, like its
    OpenCode counterpart, only decides how that association reads on a page.
    Where the two adapters diverge on purpose: a withheld tool is spelled
    here as `mcp__<key>__<tool>`, this CLI's own qualified name for one MCP
    tool -- the exact string this adapter's `disallowedTools` frontmatter key
    (`_disallowed_tools_field`, above) would carry to actually deny it. A
    bare tool name would read as a fact about the *server*; the qualified
    form reads as the fact this table exists to state: which single
    capability Claude Code itself has already refused to grant, in Claude
    Code's own vocabulary for refusing it, not OpenCode's differently-shaped
    `f"{key}_{tool}"` permission string.
    """
    withheld = dict(target.withheld_mcp_tools)
    parts = [
        "{key} (withholds: {tools})".format(
            key=key,
            tools=", ".join(f"mcp__{key}__{tool}" for tool in withheld[key]),
        )
        if key in withheld
        else key
        for key in target.mcp
    ]
    return ", ".join(parts) or "none"


def delegation_capabilities(layout: Layout, targets: tuple[Any, ...]) -> list[Artifact]:
    """The generated reference every delegating Claude Code body's pointer names.

    Mirrors `opencode.render.delegation_capabilities` in structure only --
    same table shape, same reason for existing (see that function's own
    docstring for the split between `core.catalog`'s facts and an adapter's
    presentation of them) -- and diverges from it everywhere the two CLIs
    disagree about vocabulary. `_delegation_tools_cell` spells a target's
    tools the way `TOOL_NAME` spells them for a real agent file (`Bash`,
    `Read`, ...), never OpenCode's lowercase server-prefixed names, because a
    table that spelled tools in the wrong CLI's vocabulary would be a file
    that lies about capabilities in the one place that exists to stop
    capability guesswork -- exactly the failure this whole feature exists to
    prevent. `_delegation_mcp_cell` spells a withheld tool the way this
    adapter's own `disallowedTools` key would.

    Written unconditionally by `own_artifacts`, the same as every other file
    it ships: this adapter has no interactive selection step of its own to
    gate it on.
    """
    if layout.skills_dir is None:
        raise RenderError("delegation-capabilities: this layout has no skills directory")
    header = "| Agent | Native tools | MCP servers |\n| --- | --- | --- |\n"
    rows = "".join(
        "| `{name}` | {tools} | {mcp} |\n".format(
            name=target.name,
            tools=_delegation_tools_cell(target),
            mcp=_delegation_mcp_cell(target),
        )
        for target in targets
    )
    text = (
        "# Delegation Target Capabilities\n\n"
        "Generated -- never hand-edited, and never a snapshot: every install regenerates\n"
        "this from the content core's own agent declarations, after this machine's own\n"
        "MCP selection and grants have already been applied. One row per agent that is\n"
        "the declared target of at least one other agent's `may_delegate_to`: what it\n"
        "reads here is what an install actually grants it, `granted_mcp` included\n"
        "alongside `optional_mcp`, because a target that can do something a delegator\n"
        "did not know about is cheap, and a target a delegator wrongly assumed could do\n"
        "something is the expensive direction this file exists to close.\n\n"
        "Native tools are spelled exactly as this CLI's own `tools:` frontmatter key\n"
        "spells them (`Bash`, `Read`, ...), never a lowercase agnostic name -- the same\n"
        "vocabulary a delegating body reads in its own rendered file.\n\n"
        "A server listed with `(withholds: ...)` still grants every tool it exposes\n"
        "except the ones named -- a wildcard grant with a tool or two taken back out,\n"
        "never the whole server refused. Each withheld tool is spelled\n"
        "`mcp__<server>__<tool>`, the exact qualified name this CLI's own\n"
        "`disallowedTools` key uses to refuse it -- assuming one of those named tools is\n"
        "reachable is exactly the wrongly-assumed-capability mistake this file exists\n"
        "to close, so it is never left off the row.\n\n"
        "Read this before writing a brief that assumes a target can run a command, open\n"
        "a browser, or write a file. If this reference is missing or unreadable, do not\n"
        "assume the capability: verify it directly, or ask for less.\n\n"
        + header
        + rows
    )
    return [
        FileArtifact(
            id="own:delegation-capabilities",
            path=layout.skills_dir / delegation_capabilities_path(),
            content=text.encode("utf-8"),
            executable=False,
        )
    ]


def _tools_field(item: Agent, mcp: tuple[Mcp, ...]) -> str:
    """A comma-separated tool list, plus an `Agent(...)` entry for delegation.

    `Agent(name-a, name-b)` is Claude Code's purpose-built construct for
    restricting which subagent types may be spawned -- it lives inside this
    same `tools` list, not in a field of its own. An agent whose `may_
    delegate_to` is empty gets no `Agent(...)` entry at all: that omission is
    how "may delegate to nobody" is spelled, not a special case to guard.

    Measured live on Claude Code 2.1.283 (`docs/arquitectura/arquitectura.md`'s
    7.3.3 section): a sub-agent reaches the tools of the servers in its own
    `mcpServers:` regardless of what its `tools:` names, but the session
    identity -- the one agent `settings.json`'s `agent` key names, `item.
    default` here -- does not: its `tools:` filters MCP tools out even though
    `mcpServers:` connects the servers. Naming a server *at the server level*
    in `tools:` (`mcp__<key>`, never the bare `mcp__*` wildcard, which was
    measured to be a silent no-op) is what exposes every tool that server
    has. So for the session identity only, and only when it was granted at
    least one server, this appends one `mcp__<key>` entry per resolved key in
    `mcp` -- the exact same keys `_mcp_servers_field` already wrote into this
    agent's own `mcpServers:` -- plus `ToolSearch`, which is how this session
    loads them: with every server up, an interactive session defers all its
    MCP tools (61 of them, "loaded on-demand") and fetches them through that
    tool, so without it none would arrive. A sub-agent is never touched
    here: it already reaches its granted servers' tools without this, and
    adding it there would be a change nobody asked for.
    """
    names = (*item.requires_tools, *item.optional_tools)
    unknown = [name for name in names if name not in TOOL_NAME]
    if unknown:
        raise RenderError(f"{item.name}: no Claude Code name for tools {', '.join(sorted(unknown))}")
    entries = sorted({TOOL_NAME[name] for name in names})
    if item.may_delegate_to:
        entries.append(f"Agent({', '.join(item.may_delegate_to)})")
    if item.default and mcp:
        keys = sorted({server.bound_to or server.name for server in mcp})
        entries += [f"mcp__{key}" for key in keys]
        entries.append("ToolSearch")
    return ", ".join(entries)


def command(layout: Layout, item: Command, orchestrator_name: str) -> list[Artifact]:
    """A markdown file, Claude Code's own command frontmatter over the body.

    `orchestrator_name` is accepted because the port's signature requires
    every adapter to take it, not because this function has anywhere to put
    it. Claude Code's command frontmatter (`description`, `argument-hint`,
    `allowed-tools`, `model`, `disable-model-invocation`, `user-invocable`)
    has no `agent:` field -- unlike OpenCode, which spells `RunsAs.
    ORCHESTRATOR` by naming an agent there. There is nothing honest to write
    for it here: this function renders the same frontmatter for every
    `RunsAs` member, and `orchestrator_name` never appears in the output.
    """
    fields: dict[str, Any] = {"description": item.description}
    return [
        FileArtifact(
            id=f"command:{item.name}",
            path=layout.commands_dir / f"{item.name}.md",
            content=(_frontmatter(fields) + "\n" + _body(layout, item.body, item.name)).encode("utf-8"),
            executable=False,
        )
    ]


def system_prompt(layout: Layout, item: SystemPrompt, identity: Identity) -> list[Artifact]:
    """One file, `rules/<program_name>.md`, and nothing else to wire in.

    `~/.claude/rules/*.md` is a first-class, auto-loaded location -- Claude
    Code documents it in the same "what loads at startup" bullet as CLAUDE.md,
    reaching the main session AND every sub-agent (only the built-in Explore
    and Plan agents skip it). That means this one file, shipped once, reaches
    all sixteen agents with no per-agent duplication and no settings key
    pointing at it -- unlike OpenCode's own `system_prompt`, which has to
    append an entry to an `instructions` list for the runtime to notice the
    file at all. There is deliberately no `ConfigKeyArtifact` here.

    The filename comes from `identity`, not from `layout.system_prompt_file`:
    `layout` is built with no `Identity` in reach (see `adapter.layout`,
    called from many places that never carry one), so its own anchor stays
    the fixed, identity-unaware default -- correct only for the packaged
    distribution, and never consulted for what this function actually writes.

    This adapter never writes into the user's own `~/.claude/CLAUDE.md`; that
    file is theirs.
    """
    path = layout.config_dir / "rules" / f"{identity.program_name}.md"
    return [
        FileArtifact(
            id=f"system-prompt:{path.name}",
            path=path,
            content=_system_prompt_body(layout, item).encode("utf-8"),
            executable=False,
        )
    ]


def _system_prompt_body(layout: Layout, item: SystemPrompt) -> str:
    """The base prompt, then one section per server the user chose."""
    return _with_mcp_sections(layout, item.body, item.mcp_sections, "system-prompt")


def _agent_body(layout: Layout, item: Agent) -> str:
    """The agent's own prose, then one section per server it was granted.

    Composed exactly the way `_system_prompt_body` composes the base prompt:
    the two are the same idea at two different levels of the tree. Each
    section in `item.mcp_sections` typically points, through a lazy-load
    reference, at the convention file `mcp` (above) writes for that same
    server -- which is why this adapter's `mcp=True` cannot exist without
    also implementing `mcp` to write it.
    """
    return _with_mcp_sections(layout, item.body, item.mcp_sections, item.name)


def _with_mcp_sections(layout: Layout, body: str, sections: tuple[Any, ...], owner: str) -> str:
    parts = [_body(layout, body, owner)]
    parts += [_body(layout, section.body, str(section.source)) for section in sections]
    return "\n\n".join(part.strip("\n") for part in parts) + "\n"


def _body(layout: Layout, body: str, owner: str) -> str:
    """Answer the placeholders a body left for its installer.

    A body names facts, not paths, so that one text installs under every CLI.
    This is where those facts become this layout's directories.
    """
    try:
        return placeholders.fill(body, facts(layout))
    except placeholders.Unanswered as missing:
        raise RenderError(
            f"{owner}: this layout has no {missing.name}, so the body cannot be filled"
        ) from None


def facts(layout: Layout) -> dict[str, str]:
    """What this layout can answer. An absent anchor answers nothing, never a blank."""
    result: dict[str, str] = {}
    if layout.skills_dir is not None:
        result["skills_root"] = str(layout.skills_dir)
    return result


def _frontmatter(fields: dict[str, Any]) -> str:
    lines = ["---"]
    lines += [f"{key}: {_scalar(value)}" for key, value in fields.items()]
    lines.append("---")
    return "\n".join(lines) + "\n"


def _scalar(value: Any) -> str:
    """JSON is a subset of YAML, so this quotes exactly when quoting is needed."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return json.dumps(value, ensure_ascii=False)
