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
from dataclasses import dataclass, field, replace
from pathlib import Path, PurePosixPath
from typing import Any

from pegasus.core.content import _SERVER_KEY

SCHEMA = "pegasus-harness/journal/v4"
KINDS = frozenset({"file", "config-key", "dependency-tree"})
OWNED = "owned"
NON_OWNING_LINK = "non-owning-link"
#: `file` and `config-key` always hash to `sha256:`; a `dependency-tree` may
#: instead carry `sha512-...`, npm's own integrity string, verbatim.
DIGEST = re.compile(r"^(sha256:[0-9a-f]{64}|sha512-[A-Za-z0-9+/]+=*)$")


class JournalError(ValueError):
    """The journal is malformed, so nothing in it may be treated as owned."""


@dataclass(frozen=True)
class Record:
    """One artifact Pegasus owns.

    ``kind`` is one of ``KINDS``: a single ``file``, a ``config-key`` inside
    a document, or a ``dependency-tree`` — a directory Pegasus materialized
    under its own data directory (an unpacked package, an extracted binary)
    rather than a CLI's configuration. ``target`` is a file path for the
    first two and a directory path for the third; retirement dispatches on
    ``kind`` to know which.
    """

    id: str
    kind: str
    target: Path
    after_digest: str
    """For a ``file`` or ``config-key``, the digest of the bytes Pegasus wrote —
    it proves the write happened and lets a later reinstall recognize its own
    content. For a ``dependency-tree`` it instead identifies *what was
    materialized*: the verified digest of the source artifact (a tarball's
    checksum, a lockfile's integrity string), not a hash of the tree's
    contents on disk. That is deliberate — computing a content hash would need
    a recursive read this journal has no reason to do at record time — but it
    means this digest cannot prove the tree is still intact. A `doctor` that
    wants to detect a corrupted or tampered dependency tree needs a different
    check; this field only answers "is this the version we meant to put
    there", never "is what's on disk still what we put there"."""
    created_at: str
    pointer: str | None = None
    codec: str | None = None
    mode: str | None = None
    ownership: str = OWNED
    program_relpath: str | None = None
    """For a ``dependency-tree`` only: the path, relative to ``target``, of the
    one file a CLI's configuration actually runs -- `dependencies.program_path`
    or `dependencies.npm_script_path`, whichever the distribution used. This
    and ``program_digest`` are the pair that lets a later `doctor` check the
    one thing in the tree whose substitution would matter, without reading
    the tree it sits in. Both are optional, and only ever together: a record
    written before this existed carries neither, and must be told apart from
    a record whose program has gone missing -- the first has nothing to
    check, the second has something to check that failed."""
    program_digest: str | None = None
    """The digest of ``program_relpath``'s bytes at materialization time.

    Deliberately not ``after_digest``: that field identifies the *source*
    Pegasus fetched (an archive's checksum, a lockfile's integrity string),
    which for an archive is never the digest of any single extracted member.
    This is the digest of the placed file itself, the only thing a later
    read of the tree can cheaply reproduce and compare against."""


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
    mcp_bindings: dict[str, str] = field(default_factory=dict)
    """The server key each bound MCP id was granted against, on this install.

    A binding is never a fact about the release, always about one
    installation (see `Mcp.bound_to`'s docstring), and `Install` is precisely
    the per-installation object -- so this is where the fact belongs, not
    threaded through the artifact/step/`Record` pipeline that renders and
    journals per-artifact facts.

    Additive, the same way `program_relpath`/`program_digest` are: a journal
    written before this field existed carries no `mcp_bindings` key at all,
    and that must load exactly as cleanly as one that carries it, with the
    resulting install carrying an empty mapping -- never an invented key,
    never a crash, and never confused with a mapping that legitimately holds
    nothing because this install bound no server."""

    granted_mcp: tuple[str, ...] = ()
    """The server keys this installation was told to expose to every agent.

    A binding (`mcp_bindings`, above) grants one server Pegasus ships a
    descriptor for, against a key the user already runs it under. This is a
    different fact: a server Pegasus never heard of, that the user installed
    and administers entirely on their own, whose only relationship to Pegasus
    is that every rendered agent's deny-all baseline would otherwise stay
    deny-all against it -- a runtime whose own configuration merges an
    agent's rendered permission block last resolves nothing else in the
    user's favour, so a server nothing in this list names is a tool no agent
    can ever reach, no matter what the user's own configuration says. This
    is per-installation, never a fact about the release: two installs of the
    same Pegasus version, on two machines, administer different MCP servers
    under different keys, and neither install has any way to know what the
    other grants.

    Additive, the same discipline `mcp_bindings` follows: a journal written
    before this field existed carries no `granted_mcp` key at all, and that
    must load exactly as cleanly as one that carries it, with the resulting
    install carrying an empty tuple -- never an invented key, never a crash,
    and never confused with a tuple that legitimately holds nothing because
    this install grants no server of its own."""


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


# --- Functional updates ----------------------------------------------------


def with_install(journal: Journal, install: Install) -> Journal:
    """Add or replace the record for one CLI, leaving the others untouched."""
    others = tuple(item for item in journal.installs if item.cli != install.cli)
    ordered = tuple(sorted((*others, install), key=lambda item: item.cli))
    return replace(journal, installs=ordered)


def without_install(journal: Journal, cli: str) -> Journal:
    return replace(journal, installs=tuple(item for item in journal.installs if item.cli != cli))


# --- Serialization ---------------------------------------------------------


def to_dict(journal: Journal) -> dict[str, Any]:
    return {
        "schema": journal.schema,
        "pegasus_version": journal.pegasus_version,
        "installs": [_install_to_dict(item) for item in journal.installs],
    }


def _install_to_dict(install: Install) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "cli": install.cli,
        "installed_at": install.installed_at,
        "config_dir": str(install.config_dir),
        "release": dict(install.release),
        "entries": [_record_to_dict(entry) for entry in install.entries],
        "links": [{"id": link.id, "target": link.target, "ownership": link.ownership} for link in install.links],
    }
    if install.mcp_bindings:
        payload["mcp_bindings"] = dict(install.mcp_bindings)
    if install.granted_mcp:
        payload["granted_mcp"] = list(install.granted_mcp)
    return payload


def _record_to_dict(entry: Record) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": entry.id,
        "kind": entry.kind,
        "target": str(entry.target),
        "after_digest": entry.after_digest,
        "ownership": entry.ownership,
        "created_at": entry.created_at,
    }
    for name in ("pointer", "codec", "mode", "program_relpath", "program_digest"):
        value = getattr(entry, name)
        if value is not None:
            payload[name] = value
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
        mcp_bindings=_mcp_bindings_from_dict(payload.get("mcp_bindings"), cli),
        granted_mcp=_granted_mcp_from_dict(payload.get("granted_mcp"), cli),
    )


def _mcp_bindings_from_dict(value: Any, cli: str) -> dict[str, str]:
    """Absent means a journal from before this field existed -- an empty
    mapping, not an error and not a fabricated binding. Present, it must be a
    mapping of id to server key, both non-empty strings: anything else could
    never have come from `select_mcp`, so it can only be a hand edit."""
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise JournalError(f"{cli}: mcp_bindings must be an object")
    for mcp_id, key in value.items():
        if not isinstance(mcp_id, str) or not mcp_id or not isinstance(key, str) or not key:
            raise JournalError(f"{cli}: mcp_bindings must map non-empty ids to non-empty server keys")
    return dict(value)


def _granted_mcp_from_dict(value: Any, cli: str) -> tuple[str, ...]:
    """Absent means a journal from before this field existed -- an empty
    tuple, not an error and not a fabricated grant. Present, it must be a
    list of keys shaped like `content._SERVER_KEY` -- the same regex
    `content.grant_mcp` validates a key against before ever setting
    `Agent.granted_mcp`, imported rather than restated so the two can never
    drift apart about what a safe key looks like.

    This is the same class of bug `parse_mcp_choice` and `grant_mcp` already
    guard against: a granted key is spliced verbatim into a permission rule,
    and a key holding `*`/`?` renders a wildcard rule that beats the
    per-agent deny baseline for everything the agent was never granted. A
    key that could never have come from `grant_mcp` -- because `grant_mcp`
    would have refused it -- can only be a hand edit or a corrupted write,
    and letting it back in here would replay the exact escalation `grant_mcp`
    exists to stop, straight through `update` or `mcp revoke`, neither of
    which ever asks the CLI-level checks again. A `ContentError` there cannot
    reach a journal load at all, which is exactly why the guard is repeated
    at this boundary rather than trusted to have already run once upstream.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise JournalError(f"{cli}: granted_mcp must be a list")
    for key in value:
        if not isinstance(key, str) or not _SERVER_KEY.fullmatch(key):
            raise JournalError(
                f"{cli}: granted_mcp must be a list of server keys holding only letters, digits, "
                f"'.', '_' and '-' -- {key!r} is not usable as one and could never have come from "
                f"`grant_mcp`, so the journal can only be a hand edit or corrupted"
            )
    return tuple(value)


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
    program_relpath, program_digest = _program_from_dict(payload, identifier, cli)

    return Record(
        id=identifier,
        kind=kind,
        target=_contained(payload.get("target"), home, f"{cli}: {identifier}"),
        after_digest=digest,
        created_at=_text(payload, "created_at", f"{cli}: {identifier}"),
        pointer=pointer,
        codec=payload.get("codec"),
        mode=payload.get("mode"),
        ownership=OWNED,
        program_relpath=program_relpath,
        program_digest=program_digest,
    )


def _leaves_the_tree(relpath: str) -> bool:
    """Whether joining this onto a directory could land outside it.

    Judged by shape and never by resolving anything: this module touches no
    disk, and a path whose safety depends on what happens to exist when it is
    judged is not safe.
    """
    candidate = PurePosixPath(relpath)
    return candidate.is_absolute() or ".." in candidate.parts


def _program_from_dict(payload: dict[str, Any], identifier: str, cli: str) -> tuple[str | None, str | None]:
    """A journal written before this pair existed carries neither key at all --
    that must load exactly as cleanly as one that carries both, since a
    reader who cannot check the program is a different fact from a reader
    who found it missing or wrong. Absent, both come back ``None``; present,
    both must be well-formed, since a half-written pair could never have come
    from `dependencies.materialize`.

    Well-formed includes staying inside the tree, and that check has to live
    here because nothing downstream performs it: the reader joins this onto
    the record's ``target``, and a join is not a boundary. An absolute path
    discards the tree root whole, and a `..` chain walks out of it — either
    one aims the program check at a file of somebody's choosing, which then
    passes forever against a digest they also chose, while the real tree is
    never read at all. The write side cannot produce such a path, since it
    derives the value with `relative_to` against the tree root; a journal
    edited by hand can, and this is the only place that sees it before it is
    used.
    """
    relpath = payload.get("program_relpath")
    digest = payload.get("program_digest")
    if relpath is None and digest is None:
        return None, None
    if not isinstance(relpath, str) or not relpath or _leaves_the_tree(relpath):
        raise JournalError(f"{cli}: {identifier} has a malformed program_relpath")
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise JournalError(f"{cli}: {identifier} has a malformed program_digest")
    return relpath, digest


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
