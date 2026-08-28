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

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

from pegasus.core import codecs, ownership, pointer
from pegasus.core.journal import Install, Record
from pegasus.core.types import Artifact, Codec, ConfigKeyArtifact, FileArtifact
from pegasus.ports.filesystem import FileSystem, FileSystemError

CREATE = "create"
UPDATE = "update"
UNCHANGED = "unchanged"
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
    entry: Record | None = None
    """What the journal already held for this artifact, when it held anything.

    Carried on the step rather than looked up again while applying: the decision
    and the record that justified it cannot then disagree."""


@dataclass(frozen=True)
class Plan:
    cli: str
    steps: tuple[Step, ...]
    retirements: tuple[Record, ...] = ()
    """Journal entries the render no longer asks for.

    Not a filter over ``steps``, unlike the four properties below: a
    retirement is defined precisely by the render having produced no
    artifact for it, so there is no ``Step`` to filter — only the record the
    journal still holds. A placement is driven by an artifact; a retirement
    is driven by its absence. That asymmetry is real, not an oversight, and
    the core already admits one like it: ``Retired`` is a separate type from
    ``Applied`` for the same reason.

    ``apply`` must not act on this field — see its docstring. ``Plan``
    describes; it does not execute.
    """

    @property
    def creations(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.action == CREATE)

    @property
    def updates(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.action == UPDATE)

    @property
    def unchanged(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.action == UNCHANGED)

    @property
    def placements(self) -> tuple[Step, ...]:
        """Everything this run writes. A creation and an update differ in what
        they leave behind, not in the writing."""
        return (*self.creations, *self.updates)

    @property
    def collisions(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.action == SKIP)


@dataclass(frozen=True)
class Applied:
    """What an install actually did: records for the journal, and what it left alone."""

    records: tuple[Record, ...]
    skipped: tuple[Step, ...]
    unchanged: tuple[Step, ...] = ()
    replaced: tuple[tuple[Path, bytes, int | None], ...] = ()
    """What each updated file held before this run, for a caller that has to undo it.

    ``retire`` cannot answer this: it removes what the journal records, and an
    updated artifact existed before the run, so removing it would take away a
    working file, or a key whose previous value nothing else remembers."""


@dataclass(frozen=True)
class Retired:
    """What an uninstall did, by artifact id.

    ``unaccounted`` is the honest answer for a list item that could not be
    found. A list item has no address of its own, so the user having deleted it
    and the user having edited it beyond recognition are physically
    indistinguishable, and neither is a removal. Every other artifact has an
    address, and is unconditionally removed — the user's edit, if there was
    one, is destroyed with it. The snapshot is what makes that content
    recoverable, not this report.
    """

    removed: tuple[str, ...] = ()
    unaccounted: tuple[str, ...] = ()
    kept_links: tuple[str, ...] = ()


def plan(
    filesystem: FileSystem,
    *,
    cli: str,
    artifacts: Sequence[Artifact],
    installed: Install | None = None,
) -> Plan:
    """Decide the fate of every artifact without touching anything.

    ``installed`` is what the journal says this CLI already received, and it is
    what turns an occupied address from a dead end into a question: an address
    holding bytes Pegasus recorded writing is an update, and the same address
    holding anything else is still the user's. Without it every occupied address
    is a collision, which is the honest answer for a caller that cannot tell the
    two apart.
    """
    _refuse_duplicates(cli, artifacts)
    documents = _load_documents(filesystem, artifacts)
    owned = {entry.id: entry for entry in (installed.entries if installed else ())}
    steps = tuple(_step(filesystem, artifact, documents, owned) for artifact in artifacts)
    return Plan(cli=cli, steps=steps, retirements=retirements(installed, artifacts))


def retirements(installed: Install | None, artifacts: Sequence[Artifact]) -> tuple[Record, ...]:
    """The journal entries this render no longer asks for.

    ``plan`` runs the loop the other way already: for every artifact, is this
    address still ours. That answers a placement's fate, but nothing in it
    ever asks the inverse question, for every entry the journal already
    holds, does the render still want it — an id absent from ``artifacts``
    never produces a step, so nothing would otherwise notice it is gone.

    A set difference over ids, and nothing more: it takes no ``filesystem``
    because it touches no disk, which is what makes it the purest thing in
    this module. ``installed.links`` are excluded by their type rather than
    by a condition here, the same way ``retire`` never looks at them — a link
    was never something Pegasus owned, so it is never something to retire.
    """
    if installed is None:
        return ()
    rendered = {artifact.id for artifact in artifacts}
    return tuple(entry for entry in installed.entries if entry.id not in rendered)


def _step(
    filesystem: FileSystem, artifact: Artifact, documents: dict[Path, Any], owned: dict[str, Record]
) -> Step:
    digest = ownership.digest(artifact)
    if isinstance(artifact, FileArtifact):
        return _file_step(filesystem, artifact, digest, owned.get(artifact.id))
    return _key_step(artifact, documents.get(artifact.path), digest, owned.get(artifact.id))


def _file_step(
    filesystem: FileSystem, artifact: FileArtifact, digest: str, entry: Record | None
) -> Step:
    """A file's fate, once the journal can be consulted about it.

    Two questions decide it. Does anything hold this address, and does the
    journal claim it. An address the journal claims is overwritten without
    asking whether the user changed it since — that question belonged to a
    digest-as-permission policy that no longer applies. Reading the bytes is
    not a third question about permission: it only keeps a reinstall from
    rewriting a file that is already correct.

    Which leaves one address this cannot write, and not by choice. Overwriting
    rests on having copied the address first, so a file that cannot be read is
    a file that cannot be copied, and writing it would destroy the only version
    there is with nothing left to give back.
    """
    if not filesystem.exists(artifact.path):
        return Step(artifact=artifact, action=CREATE, digest=digest, entry=entry)
    if entry is None or entry.kind != "file" or entry.target != artifact.path:
        return Step(artifact=artifact, action=SKIP, digest=digest, reason=COLLISION)
    try:
        current = ownership.digest_of_bytes(filesystem.read_bytes(artifact.path))
    except FileSystemError:
        # Unreadable is not the same as absent, and leaving it alone is not the
        # deference this policy dropped. Overwriting rests on having copied the
        # address first, and what cannot be read cannot be copied — writing it
        # anyway would destroy the only version there is with nothing to give
        # back. Same kind of exception as a list item with no address of its
        # own: a physical impossibility, not a judgement about whose bytes
        # those are.
        return Step(artifact=artifact, action=SKIP, digest=digest, reason=COLLISION)
    if current == digest and filesystem.mode_of(artifact.path) == artifact.mode:
        # Both halves, because a fingerprint is of content and a permission is
        # not content. A program whose bit was wrong ships identical bytes.
        return Step(artifact=artifact, action=UNCHANGED, digest=digest, entry=entry)
    return Step(artifact=artifact, action=UPDATE, digest=digest, entry=entry)


def _key_step(artifact: ConfigKeyArtifact, document: Any, digest: str, entry: Record | None) -> Step:
    """A configuration key's fate, asked of the document rather than of the disk.

    The two shapes ask it differently. An addressable key the journal claims is
    overwritten without asking whether its current value is still the one
    recorded — the same policy as a file. An append has no address, so its
    item is found by fingerprint, and a value the list no longer holds is a
    creation — the same answer as before this module could consult a journal.
    """
    if not _claimable(artifact, entry):
        return _plain_step(artifact, document, digest, None)
    if _appends(artifact.pointer):
        if _index_of(document, artifact.pointer, digest) is not None:
            return Step(artifact=artifact, action=UNCHANGED, digest=digest, entry=entry)
        if _index_of(document, artifact.pointer, entry.after_digest) is None:
            return Step(artifact=artifact, action=CREATE, digest=digest, entry=entry)
        return Step(artifact=artifact, action=UPDATE, digest=digest, entry=entry)
    if not ownership.occupies(artifact, document):
        return Step(artifact=artifact, action=CREATE, digest=digest, entry=entry)
    if ownership.digest_of_value(pointer.get_at(document, artifact.pointer)) == digest:
        return Step(artifact=artifact, action=UNCHANGED, digest=digest, entry=entry)
    return Step(artifact=artifact, action=UPDATE, digest=digest, entry=entry)


def _claimable(artifact: ConfigKeyArtifact, entry: Record | None) -> bool:
    """Whether this record is about this exact key, and not merely about its id."""
    return (
        entry is not None
        and entry.kind == "config-key"
        and entry.target == artifact.path
        and entry.pointer == artifact.pointer
    )


def _plain_step(
    artifact: ConfigKeyArtifact, document: Any, digest: str, entry: Record | None
) -> Step:
    """The answer when occupancy is as far as the question goes.

    A creation still carries the record when there is one. What the user had
    before Pegasus took the address over is owed to them whether or not the
    address is occupied right now — deleting the key does not cancel the debt,
    and a fresh record would quietly write it off.
    """
    if _occupied(artifact, document, digest):
        return Step(artifact=artifact, action=SKIP, digest=digest, reason=COLLISION)
    return Step(artifact=artifact, action=CREATE, digest=digest, entry=entry)


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

    An update inherits from the record the plan judged it against, because a
    record is not only a fingerprint: it also carries what the user had before
    Pegasus took the address over, and that debt outlives every version written
    since.
    """
    created: list[Path] = []
    restorable: dict[Path, tuple[bytes | None, int | None]] = {}
    records: list[Record] = []
    try:
        for step in plan.placements:
            if isinstance(step.artifact, FileArtifact):
                if step.action == UPDATE:
                    # Captured before the write, because an update is the one
                    # placement whose rollback is a restore and not a removal.
                    restorable.setdefault(
                        step.artifact.path,
                        (filesystem.read_bytes(step.artifact.path), filesystem.mode_of(step.artifact.path)),
                    )
                filesystem.write_atomic(step.artifact.path, step.artifact.content, mode=step.artifact.mode)
                if step.action == CREATE:
                    created.append(step.artifact.path)
                records.append(_file_record(step, at))
        for path, steps in _by_file(plan.placements).items():
            codec = _codec(steps)
            document = _read_document(filesystem, path, codec)
            restorable.setdefault(
                path,
                (
                    filesystem.read_bytes(path) if document is not None else None,
                    filesystem.mode_of(path),
                ),
            )
            for step in steps:
                document = pointer.set_at(
                    document if document is not None else {},
                    _address_for(step, document),
                    step.artifact.value,
                )
            _write_document(filesystem, path, document, codec, restorable[path][1])
            records.extend(_key_record(step, at) for step in steps)
    except (FileSystemError, codecs.CodecError, pointer.PointerError) as error:
        raise PlannerError(_undone(filesystem, created, restorable, error)) from error
    return Applied(
        records=tuple(records),
        skipped=plan.collisions,
        unchanged=plan.unchanged,
        # Files and configuration documents alike: an update's address is one
        # that already held something, and putting that back is the same act
        # whichever shape lives there. A path this run brought into existence is
        # not here, because restoring it would mean removing it, and Pegasus does
        # not remove a configuration file it merely put keys into.
        replaced=tuple(
            (path, content, mode)
            for path, (content, mode) in restorable.items()
            if content is not None and path in {step.artifact.path for step in plan.updates}
        ),
    )


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
                _write_back(filesystem, path, content, mode)
        except FileSystemError as failure:
            failures.append(str(failure))
    for path in reversed(created):
        try:
            filesystem.remove(path)
        except FileSystemError as failure:
            failures.append(str(failure))
    return failures


def unplace(
    filesystem: FileSystem, applied: Applied, placed: Install
) -> tuple[Retired, list[tuple[Path, str]]]:
    """Undo a run that was applied and then could not be recorded.

    The order is the correctness. Restoring comes first, because retiring is the
    wrong tool for an update: it takes the artifact away, and the artifact was
    already there. Every address this run updated is withheld from retiring
    afterwards, whether or not the restore itself succeeded: retiring
    unconditionally removes what the journal claims, and it would either erase
    the content just put back, or, when the restore failed, remove the only
    version left — leaving the user with neither. Only what this run created is
    left for retiring to take back.
    """
    failures = _put_back(filesystem, applied)
    updated = {path for path, _, _ in applied.replaced}
    kept = tuple(entry for entry in placed.entries if entry.target not in updated)
    return retire(filesystem, replace(placed, entries=kept)), failures


def _put_back(filesystem: FileSystem, applied: Applied) -> list[tuple[Path, str]]:
    failures: list[tuple[Path, str]] = []
    for path, content, mode in applied.replaced:
        try:
            _write_back(filesystem, path, content, mode)
        except FileSystemError as failure:
            failures.append((path, str(failure)))
    return failures


def _write_back(filesystem: FileSystem, path: Path, content: bytes, mode: int | None) -> None:
    """Put ``content`` back exactly where it stood, at the mode it was captured with.

    A ``None`` mode is not this module's default to pick: it means the mode
    was never observed to begin with, and the choice belongs to whichever
    filesystem is asked to write, not to this rollback path. Omitting the
    argument entirely is what leaves that choice where it belongs.
    """
    if mode is None:
        filesystem.write_atomic(path, content)
    else:
        filesystem.write_atomic(path, content, mode=mode)


def _file_record(step: Step, at: str) -> Record:
    """The record for what was just written, keeping what only the old one knew."""
    entry = step.entry
    return Record(
        id=step.artifact.id,
        kind="file",
        target=step.artifact.path,
        after_digest=step.digest,
        created_at=entry.created_at if entry else at,
        mode=f"{step.artifact.mode:04o}",
    )


def _address_for(step: Step, document: Any) -> str:
    """Where to write this key, which for a replaced append is not its pointer.

    An append addresses the end of the list, so writing there a second time
    would leave two of ours. The item is located by the fingerprint recorded for
    it — never by an index remembered from last time, because the user reorders
    lists — and replaced exactly where it already sits.
    """
    address = step.artifact.pointer
    if step.action != UPDATE or not _appends(address) or step.entry is None:
        return address
    index = _index_of(document, address, step.entry.after_digest)
    return address if index is None else f"{_parent(address)}/{index}"


def _key_record(step: Step, at: str) -> Record:
    """Like a file's record. See ``_file_record``."""
    entry = step.entry
    return Record(
        id=step.artifact.id,
        kind="config-key",
        target=step.artifact.path,
        after_digest=step.digest,
        created_at=entry.created_at if entry else at,
        pointer=step.artifact.pointer,
        codec=step.artifact.codec.value,
    )


# --- Retiring --------------------------------------------------------------


def retire(filesystem: FileSystem, install: Install) -> Retired:
    """Take back what the journal records, and only that.

    An address the journal records is removed unconditionally, whether or not
    the user changed it since — the same policy as install, in reverse. Links
    are never touched — Pegasus does not own a dependency that already existed.

    There is no rollback here, and none is needed: every operation is a no-op
    the second time, so an interrupted uninstall is finished by running it
    again.
    """
    removed: list[str] = []
    unaccounted: list[str] = []
    outcomes = {"removed": removed, "unaccounted": unaccounted}

    files = [entry for entry in install.entries if entry.kind == "file"]
    keys = [entry for entry in install.entries if entry.kind == "config-key"]

    for entry in files:
        if filesystem.exists(entry.target):
            filesystem.remove(entry.target)
        removed.append(entry.id)

    for path, entries in _group(keys, lambda entry: entry.target).items():
        codec = Codec(entries[0].codec or Codec.JSON.value)
        document = _read_document(filesystem, path, codec)
        if document is None:
            # The file the user deleted takes every key in it with it, appended
            # items included: nothing survives that could be a changed version
            # of ours, so there is nothing ambiguous to report.
            removed.extend(entry.id for entry in entries)
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
        unaccounted=tuple(unaccounted),
        kept_links=tuple(link.id for link in install.links),
    )


def _retire_key(document: Any, entry: Record) -> tuple[Any, str]:
    """Undo one key, and say which outcome it was.

    An addressable key is removed unconditionally when it is there, regardless
    of its current value. An append is different: it has no address of its own,
    so an item whose fingerprint matches nothing may have been deleted by the
    user, or edited into something no longer recognisable as ours —
    indistinguishable, and not a removal either way.

    That ambiguity is narrower than it first looks, though, and claiming it
    where it does not exist would be its own inaccuracy. It needs survivors: a
    list that is absent, or present and empty, holds nothing that could be a
    changed version of ours, so our item is unambiguously gone and that is a
    plain removal. Only a list that still holds items, none of which are ours,
    leaves the question open.
    """
    if _appends(entry.pointer or ""):
        items = pointer.get_at(document, _parent(entry.pointer))
        if not isinstance(items, list) or not items:
            return document, "removed"
        index = _index_of(document, entry.pointer, entry.after_digest)
        if index is None:
            return document, "unaccounted"
        return pointer.unset_at(document, f"{_parent(entry.pointer)}/{index}"), "removed"

    if not pointer.exists_at(document, entry.pointer):
        return document, "removed"
    return pointer.unset_at(document, entry.pointer), "removed"


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
    """Write a configuration file back, keeping the permissions it had.

    A document with no observed mode is one this run is creating for the
    first time, so there is no permission of the user's to keep — the
    argument is left out rather than guessed at here, and whichever
    filesystem is asked to write picks the mode a brand-new file gets.
    """
    payload = codecs.dumps(codec, document).encode("utf-8")
    _write_back(filesystem, path, payload, mode)


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
