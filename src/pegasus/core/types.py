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
    data_dir: PurePath | None = None
    """Where Pegasus's own directory sits in this frame -- the same fact
    `FileSystem.data_dir` answers for a real home, and `CANONICAL_DATA_DIR`
    stands in for in the canonical one. `None` means this frame has no
    answer, which is only ever true of a test that never renders anything
    reaching for it."""

    def __post_init__(self) -> None:
        _require_absolute(self.home, "home")
        if self.data_dir is not None:
            _require_absolute(self.data_dir, "data_dir")


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
    #: What `reason_for` reads back for a capability this manifest declares
    #: `False` -- the adapter's own person-facing explanation of *why*, not
    #: a developer-facing restatement of the boolean itself. Every surface
    #: that shows a person a disabled feature (`cli._require_per_agent_model`,
    #: `tui.session._models_screen`'s placeholder, `tui.navigator
    #: .models_menu`'s own row, by way of `tui.session
    #: .disabled_model_reasons`) reads this same string, so an adapter that
    #: declares one is the single source every one of them repeats verbatim
    #: -- see `cli._per_agent_model_reason` for the generic fallback used
    #: when an adapter declares none.
    reasons: dict[Capability, str] = field(default_factory=dict)
    schema: str = CAPABILITY_MANIFEST_SCHEMA

    def __post_init__(self) -> None:
        if not self.cli_id:
            raise ValueError("a capability manifest needs a cli_id")
        for capability in self.reasons:
            if self.declares(capability):
                raise ValueError(
                    f"{self.cli_id!r} declares {capability.value!r} as True and also carries a reason "
                    "for its absence -- a reason only ever explains a capability this manifest does "
                    "not declare"
                )

    def declares(self, capability: Capability) -> bool:
        return bool(getattr(self, capability.value))

    def reason_for(self, capability: Capability) -> str | None:
        """The adapter's own person-facing reason it does not support
        `capability`, or `None` when it declared none -- never raised for a
        capability this manifest declares `True`, since `__post_init__`
        already refuses that combination at construction."""
        return self.reasons.get(capability)

    @property
    def enabled(self) -> frozenset[Capability]:
        return frozenset(item for item in Capability if self.declares(item))


@dataclass(frozen=True)
class CredentialTransportCapability:
    """Which of the four credential-transport operations one adapter supports.

    Not one of the content-rendered `Capability` members: nothing here is
    sourced from `content.py` one item at a time the way a skill or an agent
    is (see `catalog.SOURCES`). It is a fixed plugin plus a sidecar the
    content core ships as data, so it is asked of an adapter directly,
    exactly like `writes_mcp_config_key`.

    An adapter that never implements `credential_transport()` at all reads as
    every field `False` here -- see `credential_transport.capability_of`,
    which is where that default is applied. That is deliberate: it is the
    mechanism a future adapter (Claude Code, still unregistered in this
    release) uses to declare it supports none of the four operations, with
    no code written here to special-case it -- the port's absence already
    means "none", the same way an adapter with no `mcp` implementation
    already means "no MCP" for every other capability in this file.
    """

    detect_and_replace: bool = False
    """`chat.message` (or the nearest equivalent): find a credential value in
    the user's own text, register it, and rewrite it to `$PEGASUS_SECRET_<NAME>`
    before the message is persisted or reaches the model."""

    inject_at_execution: bool = False
    """`shell.env` (or the nearest equivalent): expose every registered
    `PEGASUS_SECRET_<NAME>` in the environment of a spawned command, so a
    shell command that references the variable by name still runs correctly."""

    redact_on_output: bool = False
    """`tool.execute.after` (or the nearest equivalent): replace a registered
    value found in a tool's own output with its variable name, before that
    output is persisted or handed back to the model."""

    redact_before_memory: bool = False
    """A hook a memory-writing plugin (Engram's own) can call before it POSTs
    a prompt or a passive-capture body, so a credential value never reaches
    the wire even when the memory plugin runs independently of this one."""

    @property
    def any(self) -> bool:
        """Whether this adapter supports at least one of the four operations.

        The installer's own admission test for shipping the plugin and its
        sidecar at all: an adapter that supports none of them gets neither.
        """
        return any(
            (
                self.detect_and_replace,
                self.inject_at_execution,
                self.redact_on_output,
                self.redact_before_memory,
            )
        )


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
    dependencies_dir: Path | None = None
    """Where a materialized `download` server's tree lands, inside Pegasus's
    own directory rather than this CLI's configuration root. Not a
    capability's dedicated anchor -- every adapter shares one Pegasus-owned
    tree, so there is nothing here for `anchor()` to disambiguate between
    CLIs."""

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
    executable: bool
    """Whether this artifact is a program handed to the shell, or plain text.

    This is the one distinction the engine actually needs to make about a
    file's permissions, and it is a fact about the artifact, not a mode the
    engine chooses: whoever renders the artifact already knows which of the
    two it is. Turning that fact into the permission bits a real filesystem
    understands is a platform decision, made where the artifact is written.
    """

    def __post_init__(self) -> None:
        _require_absolute(self.path, "path")
        if not isinstance(self.content, bytes):
            raise TypeError("artifact content must be bytes; the adapter encodes it")
        if not isinstance(self.executable, bool):
            raise TypeError("executable must be a bool; it is a fact, not a mode to interpret")


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
