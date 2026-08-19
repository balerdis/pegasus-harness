"""How OpenCode spells what the content core means.

Every table in this module is a translation from an agnostic concept to an
OpenCode name. This is the only place those names are allowed to appear.
"""
from __future__ import annotations

import json
from typing import Any

from pegasus.core import placeholders
from pegasus.core.content import Agent, AgentMode, Command, Execution, RunsAs, Skill, SystemPrompt
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
    "codebase-memory": "codebase-memory-mcp*",
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
    tools = _tools(item)
    if tools:
        value["tools"] = tools
    if item.may_delegate_to:
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
        ),
        ConfigKeyArtifact(
            id="system-prompt-instruction",
            path=layout.settings_file,
            pointer="/instructions/-",
            value=f"./{path.relative_to(layout.config_dir).as_posix()}",
        ),
    ]


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
    names = (*item.requires_tools, *item.optional_tools)
    unknown = [name for name in names if name not in TOOL_NAME]
    if unknown:
        raise RenderError(f"{item.name}: no OpenCode name for tools {', '.join(sorted(unknown))}")
    return {TOOL_NAME[name]: True for name in names}


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
