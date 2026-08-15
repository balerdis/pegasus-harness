"""Loading the content core.

Every category is a markdown file with YAML frontmatter: the frontmatter is the
descriptor, the rest is the body. One format, one parser.

Nothing here names a CLI. A field that only makes sense for one product does not
belong in a descriptor, so this loader rejects it rather than passing it through
and letting an adapter guess.
"""
from __future__ import annotations

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
    name: str
    description: str
    body: str
    mode: AgentMode
    source: PurePosixPath
    hidden: bool = False
    requires_tools: tuple[str, ...] = ()
    optional_tools: tuple[str, ...] = ()
    may_delegate_to: tuple[str, ...] = ()
    model_configurable: bool = False


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    body: str
    runs_as: RunsAs
    execution: Execution
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
    return Content(
        skills=_load_skills(root / "skills", root),
        agents=_load_agents(root / "agents", root),
        commands=_load_commands(root / "commands", root),
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
        agents.append(
            Agent(
                name=path.stem,
                description=_text(fields, "description", source),
                body=body,
                mode=_choice(fields, "mode", AgentMode, source),
                source=source,
                hidden=bool(fields.get("hidden", False)),
                requires_tools=_names(fields, "requires_tools", source),
                optional_tools=_names(fields, "optional_tools", source),
                may_delegate_to=_names(fields, "may_delegate_to", source),
                model_configurable=bool(fields.get("model_configurable", False)),
            )
        )
    return tuple(agents)


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


def _names(fields: dict[str, Any], key: str, source: PurePosixPath) -> tuple[str, ...]:
    value = fields.get(key, [])
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ContentError(f"{source}: {key!r} must be a list")
    if any(not isinstance(item, str) or not item for item in value):
        raise ContentError(f"{source}: {key!r} must contain non-empty names")
    return tuple(value)
