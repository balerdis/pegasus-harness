"""Loading the content core.

Every category is a markdown file with YAML frontmatter: the frontmatter is the
descriptor, the rest is the body. One format, one parser.

Nothing here names a CLI. A field that only makes sense for one product does not
belong in a descriptor, so this loader rejects it rather than passing it through
and letting an adapter guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from pegasus.core import placeholders

DEFAULT_ROOT = Path(__file__).resolve().parent.parent / "content"
MARKER = "---"
SKILL_FILE = "SKILL.md"
SYSTEM_PROMPT_DIR = "system-prompt"

_MCP_CONVENTION_DIR = PurePosixPath("_shared") / "mcp"
"""Where every server's usage convention lands, relative to the skills root.

`_shared/` already holds hand-authored convention files that the skills renderer
writes by copying an asset verbatim (`cbm-convention.md`, `engram-convention.md`,
`openspec-convention.md`). A server's convention is a different kind of write:
the loader derives it from the server's own descriptor body. Landing both writers
in that same flat namespace means a server whose id happens to match one of those
stems collides with a file it has nothing to do with -- and `cbm` and `engram` are
both real planned servers, not a hypothetical. A subdirectory of its own makes
that collision impossible to express, rather than something a catalog build has
to notice after the fact.
"""


def mcp_convention_path(server_id: str) -> PurePosixPath:
    """Where one server's convention lands, relative to the skills root."""
    return _MCP_CONVENTION_DIR / f"{server_id}-convention.md"


_MCP_REFERENCE_PATTERN = re.compile(
    r"\{\{skills_root\}\}/"
    + re.escape(_MCP_CONVENTION_DIR.as_posix())
    + r"/([^/\s]+?)-convention\.md"
)
"""Built from the same directory `mcp_convention_path` writes into, so the two
can never drift apart: a change to where a convention lands changes what this
matches too, instead of leaving a second, hand-copied guess of the shape.
"""


def _referenced_mcp_ids(body: str) -> set[str]:
    """Every server id an agent body names as a convention path.

    This is a containment check, not a comprehension check: it proves the exact
    path string is present somewhere in the body, never that the surrounding
    prose says anything useful about it. A fenced code block or a sentence
    telling the agent NOT to do this would satisfy it just the same. That is
    accepted here because the failure this guards against is an author who
    never mentioned the server at all -- catching more than that would mean
    judging prose, which this project deliberately leaves untested.
    """
    return set(_MCP_REFERENCE_PATTERN.findall(body))

SESSION_STARTS_IN = "pegasus-orchestrator"
"""The agent a session opens in.

Which agent that is, is a fact about the set of agents rather than about any one
of them: a CLI names it in a single-valued setting. A per-agent frontmatter flag
could not hold it, because no file can see whether another already claimed it --
two claims and no claim at all are both writable, and neither is refusable
without a validator that reads the whole directory back. Naming it once, here,
makes both unrepresentable.
"""


class ContentError(ValueError):
    """The content on disk would mislead an adapter, so it is refused."""


class AgentMode(str, Enum):
    PRIMARY = "primary"
    SUBAGENT = "subagent"


class RunsAs(str, Enum):
    """Which role executes a command. The adapter maps these to real agent names."""

    ORCHESTRATOR = "orchestrator"
    PLANNER = "planner"
    BUILDER = "builder"
    DEFAULT = "default"


class Execution(str, Enum):
    """Whether a command opens its own session or runs in the current conversation."""

    ISOLATED = "isolated"
    INLINE = "inline"


class Distribution(str, Enum):
    """How an MCP server reaches the user's machine.

    One member per mechanism the installer can actually execute, so a descriptor
    cannot declare a mechanism nothing can carry out. (Two more members arrive
    in a later unit.)
    """

    REMOTE = "remote"


@dataclass(frozen=True)
class Asset:
    """One file belonging to a content item, already read into memory.

    The loader does the reading so adapters stay free of I/O and can be tested
    without a filesystem.
    """

    relative_path: PurePosixPath
    content: bytes


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    assets: tuple[Asset, ...]
    source: PurePosixPath


@dataclass(frozen=True)
class Agent:
    """`requires_tools` and `optional_tools` name native tools only.

    A tool that exists because an MCP server is installed is never in either list:
    it is named through `optional_mcp` instead, by the server's id rather than by
    a tool name that only happens to be true today.
    """

    name: str
    description: str
    body: str
    mode: AgentMode
    source: PurePosixPath
    requires_tools: tuple[str, ...] = ()
    optional_tools: tuple[str, ...] = ()
    optional_mcp: tuple[str, ...] = ()
    may_delegate_to: tuple[str, ...] = ()
    model_configurable: bool = False

    @property
    def default(self) -> bool:
        """Whether a session starts in this agent. Read off the name, so only one can."""
        return self.name == SESSION_STARTS_IN

    @property
    def hidden(self) -> bool:
        """Whether the runtime keeps this agent out of the chooser.

        That is exactly what being a subagent means, with no exception, so it is
        read off `mode` rather than declared beside it where the two could drift.
        """
        return self.mode is AgentMode.SUBAGENT


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    body: str
    runs_as: RunsAs
    execution: Execution
    source: PurePosixPath


@dataclass(frozen=True)
class Mcp:
    name: str
    description: str
    body: str
    distribution: Distribution
    endpoint: str
    source: PurePosixPath


@dataclass(frozen=True)
class SystemPrompt:
    body: str
    source: PurePosixPath


@dataclass(frozen=True)
class Content:
    skills: tuple[Skill, ...] = ()
    agents: tuple[Agent, ...] = ()
    commands: tuple[Command, ...] = ()
    mcp: tuple[Mcp, ...] = ()
    system_prompt: SystemPrompt | None = None


def split_frontmatter(text: str, source: str = "<text>") -> tuple[dict[str, Any], str]:
    """Separate the descriptor from the body. Text without a marker has no descriptor."""
    if not text.startswith(MARKER + "\n"):
        return {}, text
    closing = text.find(f"\n{MARKER}\n", len(MARKER))
    if closing == -1:
        raise ContentError(f"{source}: frontmatter is never closed")
    fields = yaml.safe_load(text[len(MARKER) + 1 : closing + 1]) or {}
    if not isinstance(fields, dict):
        raise ContentError(f"{source}: frontmatter must be a mapping of fields")
    return fields, text[closing + len(MARKER) + 2 :].lstrip("\n")


def load(root: Path = DEFAULT_ROOT) -> Content:
    """Read the whole content core, or refuse with the offending file named."""
    root = root.resolve()
    agents = _load_agents(root / "agents", root)
    mcp = _load_mcp(root / "mcp", root)
    _require_known_optional_mcp(agents, mcp)
    _require_mcp_convention_referenced(agents)
    return Content(
        skills=_load_skills(root / "skills", root),
        agents=agents,
        commands=_load_commands(root / "commands", root),
        mcp=mcp,
        system_prompt=_load_system_prompt(root / SYSTEM_PROMPT_DIR, root),
    )


def _load_skills(directory: Path, root: Path) -> tuple[Skill, ...]:
    skills = []
    for item in _subdirectories(directory):
        descriptor = item / SKILL_FILE
        source = _relative(descriptor, root)
        if not descriptor.is_file():
            raise ContentError(f"{_relative(item, root)}: a skill directory needs a {SKILL_FILE}")
        fields, _ = split_frontmatter(descriptor.read_text(encoding="utf-8"), str(source))
        _require_name(fields, item.name, source)
        assets = _assets(item)
        _refuse_verbatim_placeholders(assets, source)
        skills.append(
            Skill(
                name=item.name,
                description=_text(fields, "description", source),
                assets=assets,
                source=source,
            )
        )
    return tuple(skills)


def _load_agents(directory: Path, root: Path) -> tuple[Agent, ...]:
    agents = []
    for path in _markdown_files(directory):
        fields, body, source = _descriptor(path, root)
        _refuse_derived_fields(fields, source)
        agents.append(
            Agent(
                name=path.stem,
                description=_text(fields, "description", source),
                body=body,
                mode=_choice(fields, "mode", AgentMode, source),
                source=source,
                requires_tools=_names(fields, "requires_tools", source),
                optional_tools=_names(fields, "optional_tools", source),
                optional_mcp=_names(fields, "optional_mcp", source),
                may_delegate_to=_names(fields, "may_delegate_to", source),
                model_configurable=_flag(fields, "model_configurable", source),
            )
        )
    _require_the_session_start(tuple(agents), directory, root)
    return tuple(agents)


def _require_the_session_start(agents: tuple[Agent, ...], directory: Path, root: Path) -> None:
    """The agent a session opens in has to be here, and has to be able to open one.

    `SESSION_STARTS_IN` decides who that is, so nothing on disk can claim it twice
    or leave it unclaimed. What disk still decides is whether that agent exists and
    what mode it is in, and a session opens in a primary agent.

    A tree with no agents chooses between nothing and is left alone.
    """
    if not agents:
        return
    starts = next((agent for agent in agents if agent.name == SESSION_STARTS_IN), None)
    if starts is None:
        raise ContentError(
            f"{_relative(directory, root)}: no agent is named {SESSION_STARTS_IN!r}, "
            f"which is where a session starts"
        )
    if starts.mode is not AgentMode.PRIMARY:
        raise ContentError(
            f"{starts.source}: {SESSION_STARTS_IN!r} is where a session starts, so its "
            f"'mode' must be {AgentMode.PRIMARY.value!r}, not {starts.mode.value!r}"
        )


def _require_known_optional_mcp(agents: tuple[Agent, ...], servers: tuple[Mcp, ...]) -> None:
    """An `optional_mcp` id nothing provides is a typo that would ship as a
    silently ungranted tool: the agent would run believing a server's tools
    might arrive, and no installation could ever grant them. Checking here,
    once, is what makes that typo a load-time refusal instead of a permission
    nobody notices is missing.
    """
    known = {server.name for server in servers}
    for agent in agents:
        unknown = [name for name in agent.optional_mcp if name not in known]
        if unknown:
            raise ContentError(
                f"{agent.source}: 'optional_mcp' names {', '.join(sorted(unknown))}, "
                f"which no mcp server declares"
            )


def _require_mcp_convention_referenced(agents: tuple[Agent, ...]) -> None:
    """A declared server and its convention reference have to travel together.

    The permission is granted from the declaration alone: `optional_mcp: [id]`
    hands the agent a server's tools with nothing else read from the descriptor.
    Left one-directional, that makes two states representable that should not
    be: a declared server whose convention the body never mentions, and a body
    that points at a convention for a server it never declared -- an agent told
    to follow a convention for tools it will never have. Both directions have to
    agree, so the set of ids declared and the set of ids referenced are required
    to be exactly equal.
    """
    for agent in agents:
        declared = set(agent.optional_mcp)
        referenced = _referenced_mcp_ids(agent.body)
        if declared == referenced:
            continue
        problems = []
        for server_id in sorted(declared - referenced):
            expected = "{{skills_root}}/" + mcp_convention_path(server_id).as_posix()
            problems.append(
                f"declares 'optional_mcp: [{server_id}]' but its body never references "
                f"{expected!r}"
            )
        for server_id in sorted(referenced - declared):
            expected = "{{skills_root}}/" + mcp_convention_path(server_id).as_posix()
            problems.append(
                f"references {expected!r} but never declares 'optional_mcp: [{server_id}]'"
            )
        raise ContentError(f"{agent.source}: " + "; ".join(problems))


def _load_commands(directory: Path, root: Path) -> tuple[Command, ...]:
    commands = []
    for path in _markdown_files(directory):
        fields, body, source = _descriptor(path, root)
        commands.append(
            Command(
                name=path.stem,
                description=_text(fields, "description", source),
                body=body,
                runs_as=_choice(fields, "runs_as", RunsAs, source),
                execution=_choice(fields, "execution", Execution, source),
                source=source,
            )
        )
    return tuple(commands)


def _load_mcp(directory: Path, root: Path) -> tuple[Mcp, ...]:
    servers = []
    for path in _markdown_files(directory):
        fields, body, source = _descriptor(path, root)
        servers.append(
            Mcp(
                name=path.stem,
                description=_text(fields, "description", source),
                body=body,
                distribution=_choice(fields, "distribution", Distribution, source),
                endpoint=_text(fields, "endpoint", source),
                source=source,
            )
        )
    return tuple(servers)


def _load_system_prompt(directory: Path, root: Path) -> SystemPrompt | None:
    files = _markdown_files(directory)
    if not files:
        return None
    if len(files) > 1:
        raise ContentError(
            f"{_relative(directory, root)}: exactly one system prompt is allowed, found {len(files)}"
        )
    source = _relative(files[0], root)
    _, body = split_frontmatter(files[0].read_text(encoding="utf-8"), str(source))
    _require_known_placeholders(body, source)
    return SystemPrompt(body=body, source=source)


def _descriptor(path: Path, root: Path) -> tuple[dict[str, Any], str, PurePosixPath]:
    source = _relative(path, root)
    fields, body = split_frontmatter(path.read_text(encoding="utf-8"), str(source))
    if not fields:
        raise ContentError(f"{source}: a descriptor is required")
    _require_name(fields, path.stem, source)
    _require_known_placeholders(body, source)
    return fields, body, source


def _refuse_derived_fields(fields: dict[str, Any], source: PurePosixPath) -> None:
    """A field the loader derives is not the file's to declare.

    Reading the line and dropping it would leave a descriptor stating a fact it has
    no say in, and an author who wrote the opposite of what happens would be told
    nothing -- the same silence `_flag` exists to prevent.
    """
    for key in ("default", "hidden"):
        if key in fields:
            raise ContentError(
                f"{source}: {key!r} is derived, not declared, and declaring it decides nothing"
            )


def _require_known_placeholders(body: str, source: PurePosixPath) -> None:
    """A placeholder nobody promised to answer would ship as literal braces."""
    unknown = placeholders.unknown_in(body)
    if unknown:
        named = ", ".join(repr(name) for name in unknown)
        allowed = ", ".join(sorted(placeholders.NAMES))
        raise ContentError(f"{source}: unknown placeholder {named}; expected one of {allowed}")
    if placeholders.malformed_in(body):
        raise ContentError(f"{source}: a '{{{{' that names nothing would ship as literal braces")


def _refuse_verbatim_placeholders(assets: tuple[Asset, ...], source: PurePosixPath) -> None:
    """A skill is copied byte for byte, so a fact it asks for is never answered.

    The engine fills bodies, not assets, and a skill has no body it keeps. Asking
    here anyway is not a typo the adapter would catch later — it is a request
    nobody is listening to, and it lands in the user's home as literal braces.
    """
    for asset in assets:
        try:
            text = asset.content.decode("utf-8")
        except UnicodeDecodeError:
            continue
        where = f"{source.parent}/{asset.relative_path}"
        asked = placeholders.answerable_in(text)
        if asked:
            raise ContentError(
                f"{where}: skills are installed verbatim, "
                f"so {asked[0]!r} would ship as literal braces"
            )
        # Held to the same standard as a body. A malformed opener is refused in
        # an agent prompt, and the same typo reaching the user's home from a
        # skill instead would be the same mistake with a kinder answer.
        if placeholders.malformed_in(text):
            raise ContentError(f"{where}: a '{{{{' that names nothing would ship as literal braces")


def _subdirectories(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(item for item in directory.iterdir() if item.is_dir())


def _markdown_files(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(item for item in directory.glob("*.md") if item.is_file())


def _assets(item: Path) -> tuple[Asset, ...]:
    """Every file under a content directory, with SKILL.md first."""
    files = sorted(path for path in item.rglob("*") if path.is_file())
    ordered = sorted(files, key=lambda path: (path.name != SKILL_FILE, path.relative_to(item).parts))
    return tuple(
        Asset(relative_path=PurePosixPath(path.relative_to(item).as_posix()), content=path.read_bytes())
        for path in ordered
    )


def _relative(path: Path, root: Path) -> PurePosixPath:
    """A portable, root-relative source reference for error messages and catalogs."""
    return PurePosixPath(path.resolve().relative_to(root).as_posix())


def _require_name(fields: dict[str, Any], expected: str, source: PurePosixPath) -> None:
    declared = fields.get("name")
    if declared != expected:
        raise ContentError(
            f"{source}: declares name {declared!r} but its path says {expected!r}"
        )


def _text(fields: dict[str, Any], key: str, source: PurePosixPath) -> str:
    value = fields.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{source}: {key!r} is required and must be a non-empty string")
    return value.strip()


def _choice(fields: dict[str, Any], key: str, options: type[Enum], source: PurePosixPath) -> Any:
    value = fields.get(key)
    try:
        return options(value)
    except ValueError:
        allowed = ", ".join(item.value for item in options)
        raise ContentError(f"{source}: {key!r} is {value!r}; expected one of {allowed}") from None


def _flag(fields: dict[str, Any], key: str, source: PurePosixPath) -> bool:
    """A flag is a YAML boolean or nothing at all.

    `bool()` would read the string 'false', the string '0' and a misspelling as true,
    and turn an author saying "not this one" into the opposite claim with no diagnostic.
    """
    value = fields.get(key, False)
    if not isinstance(value, bool):
        raise ContentError(f"{source}: {key!r} is {value!r}; expected true or false")
    return value


def _names(fields: dict[str, Any], key: str, source: PurePosixPath) -> tuple[str, ...]:
    value = fields.get(key, [])
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ContentError(f"{source}: {key!r} must be a list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ContentError(f"{source}: {key!r} must contain non-empty names")
    return tuple(value)
