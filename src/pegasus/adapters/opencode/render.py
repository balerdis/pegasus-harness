"""How OpenCode spells what the content core means.

Every table in this module is a translation from an agnostic concept to an
OpenCode name. This is the only place those names are allowed to appear.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pegasus.core import placeholders
from pegasus.core.content import (
    Agent,
    AgentMode,
    Command,
    Distribution,
    Execution,
    Mcp,
    RunsAs,
    Skill,
    SystemPrompt,
    mcp_convention_path,
)
from pegasus.core.dependencies import npm_script_path, program_path
from pegasus.core.types import Artifact, ConfigKeyArtifact, FileArtifact, Layout, ModelAssignment

AGENT_FOR_ROLE: dict[RunsAs, str | None] = {
    RunsAs.ORCHESTRATOR: "pegasus-orchestrator",
    RunsAs.PLANNER: "plan",       # nativo de OpenCode
    RunsAs.BUILDER: "build",      # nativo de OpenCode
    RunsAs.DEFAULT: None,         # se omite la clave y decide el CLI
}

MODE_NAME: dict[AgentMode, str] = {
    AgentMode.PRIMARY: "primary",
    AgentMode.SUBAGENT: "subagent",
}

TOOL_NAME: dict[str, str] = {
    "read": "read",
    "write": "write",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "glob": "glob",
    # Two the runtime offers that are not file work, and that the deny baseline
    # therefore takes away by omission rather than by decision. `skill` is what
    # puts the installed inventory in front of an agent at all -- without it the
    # skills Pegasus placed are invisible, however plainly the system prompt
    # calls consulting them mandatory. `ask` is the runtime's own way of putting
    # a question to the person and waiting, which is what a gate that says "ask,
    # and STOP" needs to exist to mean anything.
    "skill": "skill",
    "ask": "question",
}

# The three the runtime makes ask for `external_directory` before they ask for
# their own name -- `read`, `grep` and `glob` each call `assertExternalDirectory`
# against their target first. Spelled in Pegasus's own tool vocabulary, which is
# what an agent declares; `write` and `edit` are absent because the runtime does
# not gate them this way.
READS_OUTSIDE_THE_WORKTREE = frozenset({"read", "grep", "glob"})

PERMISSION_NAME: dict[str, str] = {
    "read": "read",
    # The runtime's own config loader folds `write`, `edit` and `patch` onto a
    # single `edit` permission when it derives one from `tools` -- its
    # `permission` schema has no `write` key at all. Naming both onto the same
    # target here is what keeps that collapse from being an accident this
    # module's own translation could get wrong: `write` has to land exactly
    # where `edit` does, or a granted write silently governs nothing.
    "write": "edit",
    "edit": "edit",
    "bash": "bash",
    "grep": "grep",
    "glob": "glob",
    "skill": "skill",
    "ask": "question",
}


class RenderError(ValueError):
    """The content asks for something this CLI has no name for."""


def skill(layout: Layout, item: Skill) -> list[Artifact]:
    """Skills travel verbatim: OpenCode reads the same SKILL.md format."""
    return [
        FileArtifact(
            id=f"skill:{item.name}:{asset.relative_path}",
            path=layout.skills_dir / item.name / asset.relative_path,
            content=asset.content,
            executable=False,
        )
        for asset in item.assets
    ]


def prompt(layout: Layout, item: Agent) -> list[Artifact]:
    """The agent's body, in the separate file OpenCode expects."""
    return [
        FileArtifact(
            id=f"prompt:{item.name}",
            path=_prompt_path(layout, item),
            content=_agent_body(layout, item).encode("utf-8"),
            executable=False,
        )
    ]


def agent(
    layout: Layout, item: Agent, assignment: ModelAssignment | None = None, separate_prompt: bool = True
) -> list[Artifact]:
    """One entry under the settings file's agent map, plus the default when it is one.

    `mode` and `default` say different things: `primary` says the agent can run at top
    level, `default_agent` says which single one a session opens in.

    `assignment` is a fact about one machine -- a preference from Pegasus's own
    state, its model already resolved and validated against what this machine can
    actually reach -- never a fact the content core carries. Absent, both keys are
    omitted entirely and OpenCode falls back to whatever it would have chosen
    anyway, exactly as if this agent had never been assigned a model at all.

    An effort is spelled here as ``variant``: OpenCode's own schema names a
    per-agent reasoning effort that way, and this is the one place that
    translation is allowed to happen. It is written only alongside a model,
    matching the schema's own caveat that a variant "applies only when using
    the agent's configured model".
    """
    value: dict[str, Any] = {"description": item.description, "mode": MODE_NAME[item.mode]}
    if item.hidden:
        value["hidden"] = True
    if item.body.strip():
        value["prompt"] = (
            "{file:./%s}" % _prompt_path(layout, item).relative_to(layout.config_dir).as_posix()
            if separate_prompt
            else _agent_body(layout, item)
        )
    value["tools"] = _tools(item)
    value["permission"] = _permission(layout, item)
    if assignment is not None:
        value["model"] = assignment.full_id
        if assignment.effort is not None:
            value["variant"] = assignment.effort

    artifacts: list[Artifact] = [
        ConfigKeyArtifact(
            id=f"agent:{item.name}",
            path=layout.settings_file,
            pointer=f"/agent/{item.name}",
            value=value,
        )
    ]
    if item.default:
        artifacts.append(
            ConfigKeyArtifact(
                id="default-agent",
                path=layout.settings_file,
                pointer="/default_agent",
                value=item.name,
            )
        )
    return artifacts


def command(layout: Layout, item: Command) -> list[Artifact]:
    """A markdown file whose frontmatter is rebuilt in OpenCode's own vocabulary."""
    fields: dict[str, Any] = {"description": item.description}
    executor = AGENT_FOR_ROLE[item.runs_as]
    if executor:
        fields["agent"] = executor
    if item.execution is Execution.ISOLATED:
        fields["subtask"] = True
    return [
        FileArtifact(
            id=f"command:{item.name}",
            path=layout.commands_dir / f"{item.name}.md",
            content=(_frontmatter(fields) + "\n" + _body(layout, item.body, item.name)).encode("utf-8"),
            executable=False,
        )
    ]


def system_prompt(layout: Layout, item: SystemPrompt) -> list[Artifact]:
    """A file of its own, wired in by appending to OpenCode's instructions list.

    Appending rather than replacing is what keeps this additive: the user's own
    AGENTS.md and any instruction files they already listed stay untouched.

    The value is the absolute path, not a relative one. OpenCode resolves a
    relative entry in this list by walking up from the directory being worked
    in -- the project, never the configuration root -- so `./pegasus-AGENTS.md`
    written into the global configuration names a file that exists nowhere the
    runtime looks, and the whole system prompt is dropped without a word. An
    absolute entry is resolved against itself, which is the only spelling that
    means the file this artifact actually places.
    """
    path = layout.system_prompt_file
    return [
        FileArtifact(
            id="system-prompt",
            path=path,
            content=_system_prompt_body(layout, item).encode("utf-8"),
            executable=False,
        ),
        ConfigKeyArtifact(
            id="system-prompt-instruction",
            path=layout.settings_file,
            pointer="/instructions/-",
            value=str(path),
        ),
    ]


def _system_prompt_body(layout: Layout, item: SystemPrompt) -> str:
    """The base prompt, then one section per server the user chose."""
    return _with_mcp_sections(layout, item.body, item.mcp_sections, "system-prompt")


def _agent_body(layout: Layout, item: Agent) -> str:
    """The agent's own prose, then one section per server it was granted.

    Composed exactly the way `_system_prompt_body` composes the base prompt:
    the two are the same idea at two different levels of the tree, and letting
    them diverge would be an accident of which one this module wrote first,
    not a real difference between an agent's own prompt and the shared one.
    """
    return _with_mcp_sections(layout, item.body, item.mcp_sections, item.name)


def _with_mcp_sections(
    layout: Layout, body: str, sections: tuple[Any, ...], owner: str
) -> str:
    """One prose body, then one section per server that survived selection.

    Concatenated here rather than composed in the content core because the
    separator is a fact about the file being written, not about the text: the
    core hands over bodies, and how they sit on a page is this adapter's
    business. Order follows the content core's, which is the filename order
    `_markdown_files` guarantees -- so two installs of the same selection
    produce the same bytes, and the digest that attests them means something.
    """
    parts = [_body(layout, body, owner)]
    parts += [_body(layout, section.body, str(section.source)) for section in sections]
    return "\n\n".join(part.strip("\n") for part in parts) + "\n"


MCP_VALUE: dict[Distribution, Any] = {
    # No `headers`: this server needs no authentication, and a secret would
    # never travel in a repository descriptor anyway.
    Distribution.REMOTE: lambda item, layout: {"type": "remote", "url": item.endpoint, "enabled": True},
    # The command points at where the fetched program will land, not where
    # it is right now: `render` never fetches, so this is the same path
    # arithmetic `materialize` uses to place it, computed here without ever
    # touching a filesystem. A bare binary places itself there directly; an
    # archive places its declared executable member there instead.
    Distribution.DOWNLOAD: lambda item, layout: {
        "type": "local",
        "command": [str(_download_command(layout, item)), *item.argv],
        "enabled": True,
    },
    # Same path arithmetic as `download`, pointed at the script `npm ci`
    # installs rather than a fetched binary: `render` never runs `npm`.
    Distribution.NPM: lambda item, layout: {
        "type": "local",
        "command": [str(_npm_command(layout, item)), *item.argv],
        "enabled": True,
    },
}
"""How to spell each distribution mechanism as an OpenCode server value.

Keyed by `Distribution` rather than branched with `if`, so a member added to
the core without a matching entry here fails at import instead of falling
through to whatever branch happened to run last.
"""

_UNMAPPED_DISTRIBUTIONS = [item for item in Distribution if item not in MCP_VALUE]
if _UNMAPPED_DISTRIBUTIONS:
    # Same reasoning as the catalog's own import-time invariant: a member the
    # core grows without teaching this adapter must be impossible to import,
    # not a silent fallthrough discovered in a user's installation.
    raise RenderError(
        "no OpenCode value for distribution(s): "
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


def mcp(layout: Layout, item: Mcp) -> list[Artifact]:
    """The server as a settings key, plus its usage convention as a shared skill file.

    No guard around the lookup: the import-time invariant above already proves
    every mechanism has an entry, so a miss cannot happen and a branch for it
    would be unreachable code with a test that has to forge its own subject.

    A bound server contributes the convention alone. Writing `/mcp/<id>` for a
    server the user administers would stand a second definition beside the one
    they maintain, and the address arithmetic above would resolve a binary this
    install is never going to fetch. The convention travels either way, and it
    is named by the id, because that is the path agent bodies reference.
    """
    convention = FileArtifact(
        id=f"mcp-convention:{item.name}",
        path=_convention_path(layout, item),
        content=_body(layout, item.body, item.name).encode("utf-8"),
        executable=False,
    )
    if item.is_bound:
        return [convention]
    value = MCP_VALUE[item.distribution](item, layout)
    return [
        ConfigKeyArtifact(
            id=f"mcp:{item.name}",
            path=layout.settings_file,
            pointer=f"/mcp/{item.name}",
            value=value,
        ),
        convention,
    ]


def _convention_path(layout: Layout, item: Mcp) -> Path:
    """Where a server's convention lands, inside this layout's skills root.

    The layout inside the content tree -- `_shared/mcp/<id>-convention.md` -- is
    the core's call, made once in `mcp_convention_path`. This adapter's job stays
    what it always was: answering where the skills root itself lives on disk.
    """
    if layout.skills_dir is None:
        raise RenderError(f"{item.name}: this layout has no skills directory")
    return layout.skills_dir / mcp_convention_path(item.name)


def _body(layout: Layout, body: str, owner: str) -> str:
    """Answer the placeholders a body left for its installer.

    A body names facts, not paths, so that one text installs under every CLI.
    This is where those facts become this layout's directories.
    """
    try:
        return placeholders.fill(body, _facts(layout))
    except placeholders.Unanswered as missing:
        raise RenderError(
            f"{owner}: this layout has no {missing.name}, so the body cannot be filled"
        ) from None


def _facts(layout: Layout) -> dict[str, str]:
    """What this layout can answer. An absent anchor answers nothing, never a blank."""
    facts: dict[str, str] = {}
    if layout.skills_dir is not None:
        facts["skills_root"] = str(layout.skills_dir)
    return facts


def _prompt_path(layout: Layout, item: Agent):
    if layout.prompts_dir is None:
        raise RenderError(f"{item.name}: this layout has no prompts directory")
    return layout.prompts_dir / f"{item.name}.md"


def _tools(item: Agent) -> dict[str, bool]:
    """A deny baseline, then exactly the declared tools turned back on.

    Without the baseline, naming a tool only ever adds to the runtime's own
    defaults: it can grant, never restrict. Starting from `{"*": False}` is what
    makes "declare nothing" mean "nothing", instead of "whatever the runtime
    would have given anyway".

    `tools` is deprecated in the runtime's own schema in favour of `permission`
    (see `_permission` below), but it still keeps being rendered: a runtime old
    enough to only read `tools` would otherwise lose every restriction this
    agent declares, silently turning it unrestricted. A runtime that reads both
    derives its own permission set from this map first and then applies the
    explicit `permission` block on top key by key, so rendering both is never a
    conflict -- only ever the same restriction expressed twice, once for each
    reader.
    """
    names = (*item.requires_tools, *item.optional_tools)
    unknown = [name for name in names if name not in TOOL_NAME]
    if unknown:
        raise RenderError(f"{item.name}: no OpenCode name for tools {', '.join(sorted(unknown))}")
    granted = {TOOL_NAME[name]: True for name in names}
    # No table needed here: `mcp()` below writes each server at `/mcp/<id>`, so the
    # id IS the server key OpenCode matches tools against, and `f"{id}*"` is that
    # same key with the wildcard OpenCode uses to grant every tool under it.
    granted.update({f"{mcp_id}*": True for mcp_id in item.optional_mcp})
    return {"*": False, **granted}


def _permission(layout: Layout, item: Agent) -> dict[str, Any]:
    """The one map the runtime actually resolves tool calls against.

    Everything `_tools` expresses is repeated here directly, rather than left
    for the runtime's own `tools`-to-`permission` translation to infer, because
    that translation is exactly the trap: a plain rename of a granted `write`
    into a `permission["write"]` key would govern nothing, since the schema
    folds `write` onto `edit` (`PERMISSION_NAME` above), and this agent would
    silently lose the ability to write.

    The deny baseline has to come first for the same reason `_tools` puts it
    first: resolution takes the *last* matching rule, so `"*": "deny"` only
    ever loses to a grant written after it.

    `task` is the one entry this module has always authored straight into
    `permission`, never through `tools` -- delegation has no native-tool
    equivalent to derive it from -- and it keeps landing last, unaffected by
    the tool and MCP grants next to it: it is resolved against a delegate's
    name, not against the tool-call action namespace the rest of this map
    shares with the deny baseline.

    `external_directory` is authored the same way, and for the opposite reason
    to `task`: it is not a tool at all, so nothing in `tools` could ever derive
    it, yet the deny baseline still reaches it. Granting a tool is not granting
    every path it can be pointed at -- the runtime asks separately, under this
    name, the moment a target sits outside the project worktree -- and a
    baseline that says `*` says this too. Denied is where that ends: the runtime
    refuses before it would prompt, and a sub-agent has nobody to prompt anyway.
    Every path Pegasus hands an agent -- a phase agent's own SKILL.md, the
    `_shared` conventions each prompt defers its detail to -- lives under the
    skills directory, which is outside every worktree, so the lazy-loading
    contract is unreadable by construction without this. The grant is scoped to
    that directory and not to the config directory above it, even though both
    sit outside the worktree: the settings file is the config directory's own
    resident, and it carries whatever a server the user administers was
    configured with. Nothing shipped needs to read it, so nothing shipped is
    allowed to. It is earned rather than given, too -- only the three tools that
    actually ask under this name bring it, so declaring nothing keeps meaning
    nothing.

    The inner `"*": "deny"` is the same shape `task` uses, and it is deliberate
    even though the outer baseline already covers this name: the runtime
    flattens every key of this map into one ordered rule list and keeps the last
    rule matching both name and target, so an unlisted path outside the worktree
    already falls to that baseline. Writing the refusal where the exception
    lives makes the boundary a property of this entry rather than an inference
    across two, which is what lets a test assert it directly.
    """
    names = (*item.requires_tools, *item.optional_tools)
    unknown = [name for name in names if name not in PERMISSION_NAME]
    if unknown:
        raise RenderError(f"{item.name}: no OpenCode name for tools {', '.join(sorted(unknown))}")
    granted: dict[str, Any] = {PERMISSION_NAME[name]: "allow" for name in names}
    # Same reasoning as `_tools`: the MCP server id is the key the runtime
    # matches its tool-call actions against, and the wildcard grants every
    # tool that server exposes.
    granted.update({f"{mcp_id}*": "allow" for mcp_id in item.optional_mcp})
    if any(name in READS_OUTSIDE_THE_WORKTREE for name in names):
        granted["external_directory"] = {"*": "deny", f"{layout.skills_dir.as_posix()}/*": "allow"}
    granted["task"] = {"*": "deny", **{name: "allow" for name in item.may_delegate_to}}
    return {"*": "deny", **granted}


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
