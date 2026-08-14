"""The ownership journal: what Pegasus may take back, and what it must leave alone.

Pegasus is additive. It creates only what is missing, and when it retires it must
remove exactly what it created and nothing else. This module is the record that
makes that possible.

Two things distinguish it from the catalog. The catalog is portable and addresses
targets relative to a configuration root; the journal records **what this machine
actually holds**, with absolute paths. And the catalog describes an intention while
the journal describes a fact.

Everything here is pure: types, serialization, validation and functional updates.
Reading and writing the file belongs to a store, so this module stays testable
without a filesystem.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

SCHEMA = "pegasus-harness/journal/v4"
KINDS = frozenset({"file", "config-key"})
OWNED = "owned"
NON_OWNING_LINK = "non-owning-link"
DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class JournalError(ValueError):
    """The journal is malformed, so nothing in it may be treated as owned."""


@dataclass(frozen=True)
class Mutation:
    """A deliberate change to an artifact after it was installed."""

    at: str
    by: str
    after_digest: str


@dataclass(frozen=True)
class Record:
    """One artifact Pegasus owns.

    `before` is what was there beforehand: ``None`` means the artifact did not
    exist, so retiring it means removing it. Any other value means Pegasus took
    over something the user already had, and retiring it means putting that value
    back.
    """

    id: str
    kind: str
    target: Path
    after_digest: str
    created_at: str
    before: Any | None = None
    pointer: str | None = None
    codec: str | None = None
    mode: str | None = None
    ownership: str = OWNED
    adopted: bool = False
    mutations: tuple[Mutation, ...] = ()


@dataclass(frozen=True)
class Link:
    """A dependency that already existed. Pegasus points at it and never removes it."""

    id: str
    target: str
    ownership: str = NON_OWNING_LINK


@dataclass(frozen=True)
class Install:
    """Everything one CLI received, with its own lifecycle."""

    cli: str
    installed_at: str
    config_dir: Path
    release: dict[str, Any]
    entries: tuple[Record, ...] = ()
    links: tuple[Link, ...] = ()


@dataclass(frozen=True)
class Journal:
    pegasus_version: str
    installs: tuple[Install, ...] = ()
    schema: str = SCHEMA


def empty(pegasus_version: str) -> Journal:
    return Journal(pegasus_version=pegasus_version)


# --- Queries ---------------------------------------------------------------


def install_for(journal: Journal, cli: str) -> Install | None:
    return next((item for item in journal.installs if item.cli == cli), None)


def retirement(entry: Record) -> str:
    """What retiring this artifact means: put back what was there, or remove it."""
    return "restore" if entry.before is not None else "remove"


# --- Functional updates ----------------------------------------------------


def with_install(journal: Journal, install: Install) -> Journal:
    """Add or replace the record for one CLI, leaving the others untouched."""
    others = tuple(item for item in journal.installs if item.cli != install.cli)
    ordered = tuple(sorted((*others, install), key=lambda item: item.cli))
    return replace(journal, installs=ordered)


def without_install(journal: Journal, cli: str) -> Journal:
    return replace(journal, installs=tuple(item for item in journal.installs if item.cli != cli))


def with_mutation(
    journal: Journal, *, cli: str, entry_id: str, by: str, after_digest: str, at: str
) -> Journal:
    """Record a deliberate change and rebaseline the digest.

    Rebaselining is what keeps ownership intact: without it, the next uninstall
    would see a digest that no longer matches and preserve the artifact forever.
    """
    return _amend(journal, cli, entry_id, lambda entry: _mutated(entry, by, after_digest, at))


def with_adoption(
    journal: Journal, *, cli: str, entry_id: str, before: Any, after_digest: str, at: str
) -> Journal:
    """Take over a value the user edited, keeping theirs so it can be restored.

    Adopting twice keeps the first captured value: what uninstall owes the user is
    their original, not something Pegasus wrote in between.
    """

    def adopt(entry: Record) -> Record:
        captured = entry.before if entry.adopted else before
        return replace(_mutated(entry, "set-model-adopted", after_digest, at), before=captured, adopted=True)

    return _amend(journal, cli, entry_id, adopt)


def _mutated(entry: Record, by: str, after_digest: str, at: str) -> Record:
    mutation = Mutation(at=at, by=by, after_digest=after_digest)
    return replace(entry, after_digest=after_digest, mutations=(*entry.mutations, mutation))


def _amend(journal: Journal, cli: str, entry_id: str, change) -> Journal:
    install = install_for(journal, cli)
    if install is None:
        raise JournalError(f"no install recorded for {cli!r}")
    if not any(entry.id == entry_id for entry in install.entries):
        raise JournalError(f"{cli!r} has no owned artifact called {entry_id!r}")
    entries = tuple(change(entry) if entry.id == entry_id else entry for entry in install.entries)
    return with_install(journal, replace(install, entries=entries))


# --- Serialization ---------------------------------------------------------


def to_dict(journal: Journal) -> dict[str, Any]:
    return {
        "schema": journal.schema,
        "pegasus_version": journal.pegasus_version,
        "installs": [_install_to_dict(item) for item in journal.installs],
    }


def _install_to_dict(install: Install) -> dict[str, Any]:
    return {
        "cli": install.cli,
        "installed_at": install.installed_at,
        "config_dir": str(install.config_dir),
        "release": dict(install.release),
        "entries": [_record_to_dict(entry) for entry in install.entries],
        "links": [{"id": link.id, "target": link.target, "ownership": link.ownership} for link in install.links],
    }


def _record_to_dict(entry: Record) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entry.id,
        "kind": entry.kind,
        "target": str(entry.target),
        "after_digest": entry.after_digest,
        "before": entry.before,
        "ownership": entry.ownership,
        "created_at": entry.created_at,
        "mutations": [{"at": m.at, "by": m.by, "after_digest": m.after_digest} for m in entry.mutations],
    }
    for name in ("pointer", "codec", "mode"):
        value = getattr(entry, name)
        if value is not None:
            payload[name] = value
    if entry.adopted:
        payload["adopted"] = True
    return payload


def from_dict(payload: Any, home: Path) -> Journal:
    """Parse and validate. A journal that fails here owns nothing."""
    if not isinstance(payload, dict):
        raise JournalError("the journal must be an object")
    schema = payload.get("schema")
    if schema != SCHEMA:
        raise JournalError(f"unsupported journal schema: {schema!r}; expected {SCHEMA!r}")
    version = payload.get("pegasus_version")
    if not isinstance(version, str) or not version:
        raise JournalError("the journal needs a pegasus_version")

    raw_installs = payload.get("installs", [])
    if not isinstance(raw_installs, list):
        raise JournalError("installs must be a list")
    installs = tuple(_install_from_dict(item, home) for item in raw_installs)

    seen: set[str] = set()
    for install in installs:
        if install.cli in seen:
            raise JournalError(f"more than one install recorded for {install.cli!r}")
        seen.add(install.cli)

    return Journal(pegasus_version=version, installs=installs, schema=schema)


def _install_from_dict(payload: Any, home: Path) -> Install:
    if not isinstance(payload, dict):
        raise JournalError("each install must be an object")
    cli = payload.get("cli")
    if not isinstance(cli, str) or not cli:
        raise JournalError("an install needs a cli")
    config_dir = _contained(payload.get("config_dir"), home, f"{cli} config_dir")
    return Install(
        cli=cli,
        installed_at=_text(payload, "installed_at", cli),
        config_dir=config_dir,
        release=payload.get("release") if isinstance(payload.get("release"), dict) else {},
        entries=tuple(_record_from_dict(item, home, cli) for item in payload.get("entries", [])),
        links=tuple(_link_from_dict(item, cli) for item in payload.get("links", [])),
    )


def _record_from_dict(payload: Any, home: Path, cli: str) -> Record:
    if not isinstance(payload, dict):
        raise JournalError(f"{cli}: each entry must be an object")
    identifier = payload.get("id")
    if not isinstance(identifier, str) or not identifier:
        raise JournalError(f"{cli}: an entry needs an id")
    kind = payload.get("kind")
    if kind not in KINDS:
        raise JournalError(f"{cli}: {identifier} has an unsupported kind {kind!r}")
    digest = payload.get("after_digest")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise JournalError(f"{cli}: {identifier} has a malformed after_digest")
    if payload.get("ownership", OWNED) != OWNED:
        raise JournalError(f"{cli}: {identifier} must be {OWNED!r} or it is not ours to retire")
    pointer = payload.get("pointer")
    if kind == "config-key" and (not isinstance(pointer, str) or not pointer):
        raise JournalError(f"{cli}: {identifier} is a config-key and needs a pointer")

    return Record(
        id=identifier,
        kind=kind,
        target=_contained(payload.get("target"), home, f"{cli}: {identifier}"),
        after_digest=digest,
        created_at=_text(payload, "created_at", f"{cli}: {identifier}"),
        before=payload.get("before"),
        pointer=pointer,
        codec=payload.get("codec"),
        mode=payload.get("mode"),
        ownership=OWNED,
        adopted=bool(payload.get("adopted", False)),
        mutations=tuple(_mutation_from_dict(item, cli, identifier) for item in payload.get("mutations", [])),
    )


def _mutation_from_dict(payload: Any, cli: str, identifier: str) -> Mutation:
    if not isinstance(payload, dict):
        raise JournalError(f"{cli}: {identifier} has a malformed mutation")
    digest = payload.get("after_digest")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise JournalError(f"{cli}: {identifier} has a mutation with a malformed digest")
    return Mutation(
        at=_text(payload, "at", f"{cli}: {identifier} mutation"),
        by=_text(payload, "by", f"{cli}: {identifier} mutation"),
        after_digest=digest,
    )


def _link_from_dict(payload: Any, cli: str) -> Link:
    if not isinstance(payload, dict):
        raise JournalError(f"{cli}: each link must be an object")
    if payload.get("ownership", NON_OWNING_LINK) != NON_OWNING_LINK:
        raise JournalError(f"{cli}: a link must stay {NON_OWNING_LINK!r}; Pegasus never removes one")
    return Link(
        id=_text(payload, "id", f"{cli} link"),
        target=_text(payload, "target", f"{cli} link"),
        ownership=NON_OWNING_LINK,
    )


def _contained(value: Any, home: Path, what: str) -> Path:
    """Every path in the journal must be absolute and inside the target's home."""
    if not isinstance(value, str) or not value:
        raise JournalError(f"{what} needs a path")
    path = Path(value)
    if not path.is_absolute():
        raise JournalError(f"{what} must be an absolute path: {value}")
    if not path.is_relative_to(home):
        raise JournalError(f"{what} is outside the target home: {value}")
    return path


def _text(payload: dict[str, Any], key: str, what: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise JournalError(f"{what} needs {key!r}")
    return value
