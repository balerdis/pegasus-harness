"""Deciding what an installation will do, doing it, and undoing it.

The engine's whole job with an artifact is four operations — detect a collision,
write, fingerprint, revert — and this module is where they are sequenced. It
names no CLI and never looks inside what it writes: the adapter hands over
finished artifacts and the planner only decides their fate.

Three properties are the point.

**Additive.** Anything already occupying an address is left exactly as it is and
reported at the end. Pegasus does not negotiate with a user's file; ``plan``
separates what it would create from what it must skip, so the answer is visible
before anything is written.

**All or nothing.** ``apply`` undoes what it created if any step fails. Without
that, an interrupted install leaves a journal describing a home that does not
exist, and the next uninstall works from a fiction.

**Retirable.** ``retire`` takes back what the journal records and nothing else.
It has no rollback of its own and does not need one: it is idempotent, so a
failure is recovered by running it again.

Configuration files are handled as documents rather than as keys. Several keys
usually land in the same file, and reading it once, applying every key, and
writing it once is both cheaper and safer than a read-modify-write per key.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from pegasus.core import codecs, ownership, pointer
from pegasus.core.journal import Install, Record
from pegasus.core.types import Artifact, Codec, ConfigKeyArtifact, FileArtifact
from pegasus.ports.filesystem import FileSystem, FileSystemError

CREATE = "create"
SKIP = "skip"
COLLISION = "collision"
APPEND = "/-"
"""A pointer ending here addresses the end of a list, which is not a slot."""


class PlannerError(Exception):
    """The installation cannot proceed, or cannot be undone, safely."""


# --- The plan --------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One artifact and what will happen to it."""

    artifact: Artifact
    action: str
    digest: str
    reason: str | None = None


@dataclass(frozen=True)
class Plan:
    cli: str
    steps: tuple[Step, ...]

    @property
    def creations(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.action == CREATE)

    @property
    def collisions(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.action == SKIP)


@dataclass(frozen=True)
class Applied:
    """What an install actually did: records for the journal, and what it left alone."""

    records: tuple[Record, ...]
    skipped: tuple[Step, ...]


@dataclass(frozen=True)
class Retired:
    """What an uninstall did, by artifact id.

    ``unaccounted`` is the honest answer for a list item that could not be
    found. Every other outcome is a claim about something Pegasus did — removed
    it, put a previous value back, or deliberately left it alone — and none of
    those is true when the item is simply not there to judge.
    """

    removed: tuple[str, ...] = ()
    restored: tuple[str, ...] = ()
    preserved: tuple[str, ...] = ()
    unaccounted: tuple[str, ...] = ()
    kept_links: tuple[str, ...] = ()


def plan(filesystem: FileSystem, *, cli: str, artifacts: Sequence[Artifact]) -> Plan:
    """Decide the fate of every artifact without touching anything."""
    _refuse_duplicates(cli, artifacts)
    documents = _load_documents(filesystem, artifacts)
    steps = tuple(_step(filesystem, artifact, documents) for artifact in artifacts)
    return Plan(cli=cli, steps=steps)


def _step(filesystem: FileSystem, artifact: Artifact, documents: dict[Path, Any]) -> Step:
    digest = ownership.digest(artifact)
    if isinstance(artifact, FileArtifact):
        occupied = filesystem.exists(artifact.path)
    else:
        occupied = _occupied(artifact, documents.get(artifact.path), digest)
    if occupied:
        return Step(artifact=artifact, action=SKIP, digest=digest, reason=COLLISION)
    return Step(artifact=artifact, action=CREATE, digest=digest)


def _occupied(artifact: ConfigKeyArtifact, document: Any, digest: str) -> bool:
    """Whether this configuration artifact's value is already in place.

    An append has no address to test, so the question becomes whether the list
    already holds this exact item. Without that, reinstalling would append the
    same instruction a second time.
    """
    if not _appends(artifact.pointer):
        return ownership.occupies(artifact, document)
    return _index_of(document, artifact.pointer, digest) is not None


# --- Applying --------------------------------------------------------------


def apply(filesystem: FileSystem, plan: Plan, *, at: str) -> Applied:
    """Write everything the plan creates, or leave the home as it was found.

    Files go first and configuration documents second, so a failure has one
    kind of thing to undo at a time. Every configuration file is written once,
    which is what makes a half-applied document impossible.
    """
    created: list[Path] = []
    restorable: dict[Path, tuple[bytes | None, int | None]] = {}
    records: list[Record] = []
    try:
        for step in plan.creations:
            if isinstance(step.artifact, FileArtifact):
                filesystem.write_atomic(step.artifact.path, step.artifact.content, mode=step.artifact.mode)
                created.append(step.artifact.path)
                records.append(_file_record(step, at))
        for path, steps in _by_file(plan.creations).items():
            codec = _codec(steps)
            document = _read_document(filesystem, path, codec)
            restorable[path] = (
                filesystem.read_bytes(path) if document is not None else None,
                filesystem.mode_of(path),
            )
            for step in steps:
                document = pointer.set_at(
                    document if document is not None else {}, step.artifact.pointer, step.artifact.value
                )
            _write_document(filesystem, path, document, codec, restorable[path][1])
            records.extend(_key_record(step, at) for step in steps)
    except (FileSystemError, codecs.CodecError, pointer.PointerError) as error:
        raise PlannerError(_undone(filesystem, created, restorable, error)) from error
    return Applied(records=tuple(records), skipped=plan.collisions)


def _undone(
    filesystem: FileSystem,
    created: list[Path],
    restorable: dict[Path, tuple[bytes | None, int | None]],
    error: Exception,
) -> str:
    """Roll back, and say plainly whether the rollback itself got all the way.

    A rollback that fails must not raise over the failure that caused it: the
    original error is the diagnosis, and losing it to a second one leaves the
    user with no idea what happened. It must not be hidden either — a home left
    half-installed is the one outcome worth interrupting someone for.
    """
    failures = _undo(filesystem, created, restorable)
    if not failures:
        return f"the installation was rolled back: {error}"
    return (
        f"the installation failed and could not be fully undone, so this home is in a partial state. "
        f"Cause: {error}. Rollback also failed: {'; '.join(failures)}"
    )


def _undo(
    filesystem: FileSystem, created: list[Path], restorable: dict[Path, tuple[bytes | None, int | None]]
) -> list[str]:
    """Put back what this run found, newest first, reporting what would not go back."""
    failures: list[str] = []
    for path, (content, mode) in reversed(list(restorable.items())):
        try:
            if content is None:
                filesystem.remove(path)
            else:
                filesystem.write_atomic(path, content, mode=mode if mode is not None else 0o644)
        except FileSystemError as failure:
            failures.append(str(failure))
    for path in reversed(created):
        try:
            filesystem.remove(path)
        except FileSystemError as failure:
            failures.append(str(failure))
    return failures


def _file_record(step: Step, at: str) -> Record:
    return Record(
        id=step.artifact.id,
        kind="file",
        target=step.artifact.path,
        after_digest=step.digest,
        created_at=at,
        mode=f"{step.artifact.mode:04o}",
    )


def _key_record(step: Step, at: str) -> Record:
    return Record(
        id=step.artifact.id,
        kind="config-key",
        target=step.artifact.path,
        after_digest=step.digest,
        created_at=at,
        pointer=step.artifact.pointer,
        codec=step.artifact.codec.value,
    )


# --- Retiring --------------------------------------------------------------


def retire(filesystem: FileSystem, install: Install) -> Retired:
    """Take back what the journal records, and only that.

    Anything whose fingerprint no longer matches is the user's work now: it is
    preserved and reported. Links are never touched — Pegasus does not own a
    dependency that already existed.

    There is no rollback here, and none is needed: every operation is a no-op
    the second time, so an interrupted uninstall is finished by running it
    again.
    """
    removed: list[str] = []
    restored: list[str] = []
    preserved: list[str] = []
    unaccounted: list[str] = []
    outcomes = {
        "removed": removed,
        "restored": restored,
        "preserved": preserved,
        "unaccounted": unaccounted,
    }

    files = [entry for entry in install.entries if entry.kind == "file"]
    keys = [entry for entry in install.entries if entry.kind == "config-key"]

    for entry in files:
        if entry.before is not None:
            raise PlannerError(
                f"{entry.id} is a file recorded with a previous value; only configuration keys are adopted"
            )
        current = _file_digest(filesystem, entry.target)
        if not ownership.still_ours(entry, current):
            preserved.append(entry.id)
            continue
        filesystem.remove(entry.target)
        removed.append(entry.id)

    for path, entries in _group(keys, lambda entry: entry.target).items():
        codec = Codec(entries[0].codec or Codec.JSON.value)
        document = _read_document(filesystem, path, codec)
        if document is None:
            # The file the user deleted takes every key in it with it.
            for entry in entries:
                outcomes["unaccounted" if _appends(entry.pointer or "") else "removed"].append(entry.id)
            continue
        mode = filesystem.mode_of(path)
        original = document
        for entry in entries:
            document, outcome = _retire_key(document, entry)
            outcomes[outcome].append(entry.id)
        if document != original:
            # Rewriting an unchanged file would reformat it for nothing. The
            # user's spacing is theirs, and we only spend it when we must.
            _write_document(filesystem, path, document, codec, mode)

    return Retired(
        removed=tuple(removed),
        restored=tuple(restored),
        preserved=tuple(preserved),
        unaccounted=tuple(unaccounted),
        kept_links=tuple(link.id for link in install.links),
    )


def _retire_key(document: Any, entry: Record) -> tuple[Any, str]:
    """Undo one key, and say which outcome it was.

    The invariant that a fingerprint mismatch is preserved and reported cannot
    be enforced for a list item, and pretending otherwise would be the lie. A
    list item has no address of its own: an item whose fingerprint matches
    nothing may have been deleted by the user, or edited into something no
    longer recognisable as ours, and the two are indistinguishable. Neither is a
    removal and neither is a preservation, so they are reported as unaccounted.
    """
    if _appends(entry.pointer or ""):
        index = _index_of(document, entry.pointer, entry.after_digest)
        if index is None:
            return document, "unaccounted"
        return pointer.unset_at(document, f"{_parent(entry.pointer)}/{index}"), "removed"

    if not pointer.exists_at(document, entry.pointer):
        return document, "removed"
    current = ownership.digest_of_value(pointer.get_at(document, entry.pointer))
    if current != entry.after_digest:
        return document, "preserved"
    if entry.before is not None:
        return pointer.set_at(document, entry.pointer, entry.before), "restored"
    return pointer.unset_at(document, entry.pointer), "removed"


def _file_digest(filesystem: FileSystem, path: Path) -> str | None:
    if not filesystem.exists(path):
        return None
    return ownership.digest_of_bytes(filesystem.read_bytes(path))


# --- Documents -------------------------------------------------------------


def _load_documents(filesystem: FileSystem, artifacts: Sequence[Artifact]) -> dict[Path, Any]:
    documents: dict[Path, Any] = {}
    for artifact in artifacts:
        if isinstance(artifact, ConfigKeyArtifact) and artifact.path not in documents:
            documents[artifact.path] = _read_document(filesystem, artifact.path, artifact.codec)
    return documents


def _read_document(filesystem: FileSystem, path: Path, codec: Codec) -> Any:
    """Parse a configuration file, or return ``None`` when there is none yet.

    A file that exists but cannot be parsed stops everything. Overwriting what
    we failed to understand is how a user's settings get lost.
    """
    if not filesystem.exists(path):
        return None
    try:
        return codecs.loads(codec, filesystem.read_bytes(path).decode("utf-8"))
    except (UnicodeDecodeError, codecs.CodecError) as error:
        raise PlannerError(f"{path} exists but cannot be parsed as {codec.value}: {error}") from error


def _write_document(
    filesystem: FileSystem, path: Path, document: Any, codec: Codec, mode: int | None
) -> None:
    """Write a configuration file back, keeping the permissions it had."""
    payload = codecs.dumps(codec, document).encode("utf-8")
    filesystem.write_atomic(path, payload, mode=mode if mode is not None else 0o644)


# --- Pointers that append ---------------------------------------------------


def _appends(address: str) -> bool:
    return address.endswith(APPEND)


def _parent(address: str) -> str:
    return address[: -len(APPEND)]


def _index_of(document: Any, address: str, digest: str) -> int | None:
    """Where in the list the item with this fingerprint sits, if it is there.

    By fingerprint rather than by position: the user may have reordered the
    list, and an index recorded at install time would then point at their work.
    """
    items = pointer.get_at(document, _parent(address)) if document is not None else None
    if not isinstance(items, list):
        return None
    for index, item in enumerate(items):
        if ownership.digest_of_value(item) == digest:
            return index
    return None


# --- Refusals ---------------------------------------------------------------


def _refuse_duplicates(cli: str, artifacts: Sequence[Artifact]) -> None:
    """Two artifacts claiming one address means one of them is silently lost."""
    seen_ids: set[str] = set()
    seen_addresses: set[tuple[Path, str | None]] = set()
    seen_appends: set[tuple[Path, str | None, str]] = set()
    for artifact in artifacts:
        if not isinstance(artifact, (FileArtifact, ConfigKeyArtifact)):
            raise PlannerError(f"unsupported artifact shape: {type(artifact).__name__}")
        if artifact.id in seen_ids:
            raise PlannerError(f"{cli!r} produced two artifacts with the id {artifact.id!r}")
        seen_ids.add(artifact.id)

        address = artifact.path, getattr(artifact, "pointer", None)
        if address[1] is not None and _appends(address[1]):
            # Appending to a list is repeatable, but only with different values.
            # The same item twice is a duplicate the list cannot tell apart, and
            # nothing downstream could ever say which of the two it holds.
            item = (*address, ownership.digest(artifact))
            if item in seen_appends:
                raise PlannerError(f"{cli!r} would append the same value twice at {address[1]}")
            seen_appends.add(item)
            continue
        if address in seen_addresses:
            raise PlannerError(f"{cli!r} would place two artifacts at {address}")
        seen_addresses.add(address)


def _by_file(steps: Sequence[Step]) -> dict[Path, list[Step]]:
    return _group(
        [step for step in steps if isinstance(step.artifact, ConfigKeyArtifact)],
        lambda step: step.artifact.path,
    )


def _group(items, key) -> dict:
    grouped: dict = {}
    for item in items:
        grouped.setdefault(key(item), []).append(item)
    return grouped


def _codec(steps: Sequence[Step]) -> Codec:
    codec = steps[0].artifact.codec
    if any(step.artifact.codec is not codec for step in steps):
        raise PlannerError(f"{steps[0].artifact.path} is claimed with more than one codec")
    return codec
