"""Turning content plus an adapter into the list of artifacts an install will place.

The catalog is a derived artifact: it is generated from the content core, never
written by hand. Its digests are what later lets an installation prove that what
it placed is what the release declared.

Nothing here names a CLI. The build walks the capabilities an adapter declares
and asks that adapter to render each one.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from pegasus.core import ownership
from pegasus.core.content import Content
from pegasus.core.types import Capability, ConfigKeyArtifact, Environment, FileArtifact

SCHEMA = "pegasus/artifact-catalog/v4"
APPEND_TOKEN = "/-"

SOURCES: dict[Capability, tuple[str, str]] = {
    Capability.SKILLS: ("skills", "render_skill"),
    Capability.SUB_AGENTS: ("agents", "render_agent"),
    Capability.PROMPTS: ("agents", "render_prompt"),
    Capability.SLASH_COMMANDS: ("commands", "render_command"),
    Capability.SYSTEM_PROMPT: ("system_prompt", "render_system_prompt"),
}
"""Which part of the content core feeds each capability, and what renders it."""

INTERACTIVE = frozenset({Capability.PER_AGENT_MODEL})
"""Capabilities configured after installing, so they contribute no artifacts."""


class CatalogError(ValueError):
    """The catalog cannot be built, or would place two artifacts at one address."""


@dataclass(frozen=True)
class Entry:
    id: str
    kind: str
    target: PurePosixPath
    digest: str
    pointer: str | None = None
    codec: str | None = None
    mode: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            key: (str(value) if isinstance(value, PurePosixPath) else value)
            for key, value in asdict(self).items()
            if value is not None
        }


@dataclass(frozen=True)
class Catalog:
    """Everything one CLI would receive, addressed relative to its config root."""

    cli: str
    entries: tuple[Entry, ...]
    schema: str = SCHEMA

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "cli": self.cli,
            "entries": [entry.as_dict() for entry in self.entries],
        }

    @property
    def digest(self) -> str:
        """One digest for the whole catalog, so a release can be compared as a unit."""
        return ownership.digest_of_value(self.as_dict())

    def __len__(self) -> int:
        return len(self.entries)


def render(content: Content, adapter: Any, environment: Environment) -> list[Any]:
    """Everything the adapter declares it supports, plus what it ships itself.

    This is the output of the adapt-and-decorate steps: finished artifacts,
    addressed at real paths for this environment. The catalog turns them into a
    portable manifest; an installation hands them to the planner instead.
    """
    layout = adapter.layout(environment)
    manifest = adapter.capabilities()
    artifacts: list[Any] = []

    for capability in sorted(manifest.enabled - INTERACTIVE, key=lambda item: item.value):
        try:
            attribute, renderer = SOURCES[capability]
        except KeyError:
            raise CatalogError(
                f"{adapter.id!r} declares {capability.value!r} but the catalog has no content for it"
            ) from None
        for item in _items(content, attribute):
            artifacts.extend(getattr(adapter, renderer)(layout, item))

    artifacts.extend(adapter.own_artifacts(layout))
    return artifacts


#: The frame every catalog is built in. Not a real directory, and never written to.
CANONICAL_HOME = PurePosixPath("/pegasus/catalog-build")


def build(content: Content, adapter: Any) -> Catalog:
    """The portable manifest of what one CLI would receive.

    Built in a canonical frame on purpose, because this is release identity: two
    machines must agree on it for the digest to mean anything. It used to be
    home-independent by luck, since nothing an adapter rendered happened to
    contain a path. A body that asks the installer for one -- the whole point of
    `core.placeholders` -- would end that quietly, giving every user a different
    digest for the same release. Taking the environment away makes the property
    structural instead of accidental.

    What a machine actually receives comes from `render` with its own
    environment, and that is what the journal records.
    """
    # PurePosixPath end to end: `Path` takes the flavour of whatever machine runs
    # the build, and a canonical frame that spells itself differently on Windows
    # is not canonical.
    canonical = Environment(home=CANONICAL_HOME)
    artifacts = render(content, adapter, canonical)
    root = adapter.layout(canonical).config_dir
    return Catalog(cli=adapter.id, entries=_entries(artifacts, root, adapter.id))


def _items(content: Content, attribute: str) -> tuple[Any, ...]:
    """A category is a sequence; a singleton is one item, or nothing when absent."""
    value = getattr(content, attribute)
    if value is None:
        return ()
    return tuple(value) if isinstance(value, (tuple, list)) else (value,)


def _entries(artifacts: list[Any], root: Any, cli: str) -> tuple[Entry, ...]:
    entries, seen_ids, seen_addresses = [], set(), set()
    for artifact in artifacts:
        if not artifact.path.is_relative_to(root):
            raise CatalogError(f"{cli!r} would place {artifact.path} outside {root}")
        entry = _entry(artifact, root)

        if entry.id in seen_ids:
            raise CatalogError(f"{cli!r} produced two artifacts with the id {entry.id!r}")
        seen_ids.add(entry.id)

        # Appending to a list is legitimately repeatable; every other address is
        # a single slot and two artifacts claiming it would mean one is lost.
        address = (entry.target, entry.pointer)
        if entry.pointer is None or not entry.pointer.endswith(APPEND_TOKEN):
            if address in seen_addresses:
                raise CatalogError(f"{cli!r} would place two artifacts at {address}")
            seen_addresses.add(address)

        entries.append(entry)
    return tuple(sorted(entries, key=lambda item: item.id))


def _entry(artifact: Any, root: Any) -> Entry:
    target = PurePosixPath(artifact.path.relative_to(root).as_posix())
    if isinstance(artifact, FileArtifact):
        return Entry(
            id=artifact.id,
            kind="file",
            target=target,
            digest=ownership.digest(artifact),
            mode=f"{artifact.mode:04o}",
        )
    if isinstance(artifact, ConfigKeyArtifact):
        return Entry(
            id=artifact.id,
            kind="config-key",
            target=target,
            digest=ownership.digest(artifact),
            pointer=artifact.pointer,
            codec=artifact.codec.value,
        )
    raise CatalogError(f"unsupported artifact shape: {type(artifact).__name__}")
