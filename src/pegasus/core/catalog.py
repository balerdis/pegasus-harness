"""Turning content plus an adapter into the list of artifacts an install will place.

The catalog is a derived artifact: it is generated from the content core, never
written by hand. Its digests are what later lets an installation prove that what
it placed is what the release declared.

Nothing here names a CLI. The build walks the capabilities an adapter declares
and asks that adapter to render each one.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

from pegasus.core import codecs
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
        return _sha256(codecs.canonical_bytes(self.as_dict()))

    def __len__(self) -> int:
        return len(self.entries)


def build(content: Content, adapter: Any, environment: Environment) -> Catalog:
    """Render everything the adapter declares it supports, plus what it ships itself."""
    layout = adapter.layout(environment)
    manifest = adapter.capabilities()
    artifacts = []

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
    return Catalog(cli=adapter.id, entries=_entries(artifacts, layout.config_dir, adapter.id))


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
            digest=_sha256(artifact.content),
            mode=f"{artifact.mode:04o}",
        )
    if isinstance(artifact, ConfigKeyArtifact):
        return Entry(
            id=artifact.id,
            kind="config-key",
            target=target,
            digest=_sha256(codecs.canonical_bytes(artifact.value)),
            pointer=artifact.pointer,
            codec=artifact.codec.value,
        )
    raise CatalogError(f"unsupported artifact shape: {type(artifact).__name__}")


def _sha256(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"
