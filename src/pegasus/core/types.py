"""The vocabulary shared by the engine and every adapter.

Nothing here knows which CLIs exist. These types describe *what* an adapter
produces and *what shape* the engine can materialize, never *which product*
is on the other side.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path, PurePath
from typing import Any

from pegasus.core import pointer

CAPABILITY_MANIFEST_SCHEMA = "pegasus/capability-manifest/v1"


class SupportTier(str, Enum):
    """How complete an adapter's support for its CLI is."""

    FULL = "full"
    PARTIAL = "partial"
    EXPERIMENTAL = "experimental"


class Codec(str, Enum):
    """How a configuration file is parsed and serialized.

    Only JSON is implemented in 4.0.0. The others are declared because adding
    a member later would be an incompatible change to the artifact contract.
    """

    JSON = "json"
    TOML = "toml"
    YAML = "yaml"


class Capability(str, Enum):
    """A feature a CLI may or may not have. The value is the manifest field name."""

    SKILLS = "skills"
    SYSTEM_PROMPT = "system_prompt"
    SLASH_COMMANDS = "slash_commands"
    SUB_AGENTS = "sub_agents"
    PROMPTS = "prompts"
    MCP = "mcp"
    PER_AGENT_MODEL = "per_agent_model"


@dataclass(frozen=True)
class Environment:
    """The user's machine as the engine sees it. Pure data, no I/O."""

    # PurePath, not Path: the catalog builds in a canonical frame that names no
    # real directory, and a type that cannot read a disk is what keeps it honest.
    home: PurePath
    variables: dict[str, str] = field(default_factory=dict)
    platform: str = "linux"

    def __post_init__(self) -> None:
        _require_absolute(self.home, "home")


@dataclass(frozen=True)
class Detection:
    """What a probe found for one CLI. Filesystem and PATH only, never execution."""

    installed: bool = False
    binary_path: Path | None = None
    config_dir: Path | None = None
    config_found: bool = False

    @property
    def present(self) -> bool:
        """A CLI counts as present with either its binary or its configuration."""
        return self.installed or self.config_found


@dataclass(frozen=True)
class CapabilityManifest:
    """What an adapter claims its CLI supports.

    The registry refuses to register an adapter whose claims disagree with what
    it actually implements, so a mistake here stops the program instead of
    surfacing halfway through an installation.
    """

    cli_id: str
    skills: bool = False
    system_prompt: bool = False
    slash_commands: bool = False
    sub_agents: bool = False
    prompts: bool = False
    mcp: bool = False
    per_agent_model: bool = False
    schema: str = CAPABILITY_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if not self.cli_id:
            raise ValueError("a capability manifest needs a cli_id")

    def declares(self, capability: Capability) -> bool:
        return bool(getattr(self, capability.value))

    @property
    def enabled(self) -> frozenset[Capability]:
        return frozenset(item for item in Capability if self.declares(item))


@dataclass(frozen=True)
class Layout:
    """Where one CLI keeps each kind of artifact.

    A ``None`` anchor means the CLI has no such concept. Building a layout is
    pure path arithmetic: it must never touch the filesystem, because the
    registry probes it against a home directory that does not exist.
    """

    config_dir: Path
    settings_file: Path | None = None
    skills_dir: Path | None = None
    agents_dir: Path | None = None
    commands_dir: Path | None = None
    prompts_dir: Path | None = None
    plugins_dir: Path | None = None  # uso interno del adapter, no es una capacidad
    system_prompt_file: Path | None = None

    def __post_init__(self) -> None:
        _require_absolute(self.config_dir, "config_dir")

    def anchor(self, capability: Capability) -> Path | None:
        """The path dedicated to ``capability``, or None when it has no dedicated path.

        Capabilities that write into the shared settings file report None: the
        settings file is not evidence that any single capability is supported.
        """
        return _DEDICATED_ANCHORS.get(capability) and getattr(self, _DEDICATED_ANCHORS[capability])


_DEDICATED_ANCHORS: dict[Capability, str] = {
    Capability.SKILLS: "skills_dir",
    Capability.SYSTEM_PROMPT: "system_prompt_file",
    Capability.SLASH_COMMANDS: "commands_dir",
    Capability.SUB_AGENTS: "agents_dir",
    Capability.PROMPTS: "prompts_dir",
}


@dataclass(frozen=True)
class FileArtifact:
    """A file to place. The engine treats ``content`` as opaque bytes."""

    id: str
    path: Path
    content: bytes
    mode: int
    """The permission bits this artifact should be created with.

    A platform decision, not a domain default: whoever renders the artifact
    already knows whether it is a program handed to the shell or plain text,
    and states the answer here rather than letting the engine assume one.
    """

    def __post_init__(self) -> None:
        _require_absolute(self.path, "path")
        if not isinstance(self.content, bytes):
            raise TypeError("artifact content must be bytes; the adapter encodes it")
        if not 0 <= self.mode <= 0o777:
            raise ValueError(f"mode is outside the permission range: {self.mode:o}")


@dataclass(frozen=True)
class ConfigKeyArtifact:
    """A value to place at one address inside a configuration file.

    Addressing by pointer rather than by top-level key is what lets the engine
    write a single field without rewriting the object that holds it.
    """

    id: str
    path: Path
    pointer: str
    value: Any
    codec: Codec = Codec.JSON

    def __post_init__(self) -> None:
        _require_absolute(self.path, "path")
        if not self.tokens:
            raise ValueError("a configuration artifact must address a key, not the document root")

    @property
    def tokens(self) -> tuple[str, ...]:
        return pointer.parse(self.pointer)


Artifact = FileArtifact | ConfigKeyArtifact
"""The only two shapes the engine knows how to materialize."""


@dataclass(frozen=True)
class ModelAssignment:
    """A provider-qualified model, plus an optional reasoning effort."""

    provider_id: str
    model_id: str
    effort: str | None = None

    @classmethod
    def parse(cls, spec: str, effort: str | None = None) -> ModelAssignment:
        provider_id, separator, model_id = spec.partition("/")
        if not separator or not provider_id or not model_id:
            raise ValueError(f"model spec must be 'provider/model': {spec!r}")
        return cls(provider_id=provider_id, model_id=model_id, effort=effort)

    @property
    def full_id(self) -> str:
        return f"{self.provider_id}/{self.model_id}"


def _require_absolute(path: Path, name: str) -> None:
    if not path.is_absolute():
        raise ValueError(f"{name} must be an absolute path: {path}")
