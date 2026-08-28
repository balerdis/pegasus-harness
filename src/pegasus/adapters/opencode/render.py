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
from pegasus.core.types import Artifact, ConfigKeyArtifact, FileArtifact, Layout

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
        
            mode=0o644,
        )
        for asset in item.assets
    ]


def prompt(layout: Layout, item: Agent) -> list[Artifact]:
    """The agent's body, in the separate file OpenCode expects."""
    return [
        FileArtifact(
            id=f"prompt:{item.name}",
            path=_prompt_path(layout, item),
            content=_body(layout, item.body, item.name).encode("utf-8"),
        
            mode=0o644,
        )
    ]


def agent(layout: Layout, item: Agent, separate_prompt: bool = True) -> list[Artifact]:
    """One entry under the settings file's agent map, plus the default when it is one.

    `mode` and `default` say different things: `primary` says the agent can run at top
    level, `default_agent` says which single one a session opens in.
    """
    value: dict[str, Any] = {"description": item.description, "mode": MODE_NAME[item.mode]}
    if item.hidden:
        value["hidden"] = True
    if item.body.strip():
        value["prompt"] = (
            "{file:./%s}" % _prompt_path(layout, item).relative_to(layout.config_dir).as_posix()
            if separate_prompt
            else _body(layout, item.body, item.name)
        )
    value["tools"] = _tools(item)
    value["permission"] = {"task": {"*": "deny", **{name: "allow" for name in item.may_delegate_to}}}

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
        
            mode=0o644,
        )
    ]


def system_prompt(layout: Layout, item: SystemPrompt) -> list[Artifact]:
    """A file of its own, wired in by appending to OpenCode's instructions list.

    Appending rather than replacing is what keeps this additive: the user's own
    AGENTS.md and any instruction files they already listed stay untouched.
    """
    path = layout.system_prompt_file
    return [
        FileArtifact(
            id="system-prompt",
            path=path,
            content=_body(layout, item.body, "system-prompt").encode("utf-8"),
        
            mode=0o644,
        ),
        ConfigKeyArtifact(
            id="system-prompt-instruction",
            path=layout.settings_file,
            pointer="/instructions/-",
            value=f"./{path.relative_to(layout.config_dir).as_posix()}",
        ),
    ]


MCP_VALUE: dict[Distribution, Any] = {
    # No `headers`: this server needs no authentication, and a secret would
    # never travel in a repository descriptor anyway.
    Distribution.REMOTE: lambda item: {"type": "remote", "url": item.endpoint, "enabled": True},
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


def mcp(layout: Layout, item: Mcp) -> list[Artifact]:
    """The server as a settings key, plus its usage convention as a shared skill file.

    No guard around the lookup: the import-time invariant above already proves
    every mechanism has an entry, so a miss cannot happen and a branch for it
    would be unreachable code with a test that has to forge its own subject.
    """
    value = MCP_VALUE[item.distribution](item)
    return [
        ConfigKeyArtifact(
            id=f"mcp:{item.name}",
            path=layout.settings_file,
            pointer=f"/mcp/{item.name}",
            value=value,
        ),
        FileArtifact(
            id=f"mcp-convention:{item.name}",
            path=_convention_path(layout, item),
            content=_body(layout, item.body, item.name).encode("utf-8"),
        
            mode=0o644,
        ),
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
