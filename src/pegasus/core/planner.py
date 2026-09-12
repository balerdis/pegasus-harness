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
from typing import Any, Callable, Sequence

from pegasus.core import codecs, ownership, pointer
from pegasus.core.journal import KINDS, Install, Record
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
    found: str | None = None
    """What was actually at this address when the step was decided.

    Only set where reading it was already part of deciding, which is every
    address that held something. It answers a question the action alone cannot:
    an `UPDATE` says the address does not hold what this release renders, and
    this says whether what it holds is what Pegasus itself last wrote or
    something a person put there."""


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
    def overwritten(self) -> tuple[Step, ...]:
        """The updates that land on somebody's own edit rather than on ours.

        A digest stopped being a permission in unit 9: an address the journal
        claims is rewritten without asking whether it changed since. That
        decision stands, and this does not soften it — the product still wins.
        What it settles is the other half, which the policy never addressed:
        whether the person finds out. Silence was never the decision, only the
        cheapest way to implement it.

        Nothing is read to answer this. Deciding `UNCHANGED` against `UPDATE`
        already meant reading the address, so the step carries what was found
        there, and `found` disagreeing with the digest the journal recorded is
        the definition of a hand edit -- the same comparison `doctor` calls
        drift, asked at the moment the edit is about to be spent instead of
        before or after.
        """
        return tuple(
            step
            for step in self.updates
            if step.entry is not None and step.found is not None and step.found != step.entry.after_digest
        )

    @property
    def collisions(self) -> tuple[Step, ...]:
        return tuple(step for step in self.steps if step.action == SKIP)


@dataclass(frozen=True)
class Applied:
    """What an install actually did: records for the journal, and what it left alone."""

    records: tuple[Record, ...]
    skipped: tuple[Step, ...]
    unchanged: tuple[Step, ...] = ()
    reconciled: tuple[Record, ...] = ()
    """Records for artifacts this run did not write, because it did not need to.

    Kept apart from ``records`` rather than folded into it, and the separation
    is the correctness. Both belong in the journal -- they say what Pegasus
    claims, and Pegasus does claim these. Neither belongs in the same sentence
    as "placed": a caller reporting `records` is naming what it wrote, and a
    caller rolling back is naming what it may take away. Putting a
    reconciliation in either would report a write that never happened, or,
    far worse, remove a correct artifact this run never touched.
    """
    replaced: tuple[tuple[Path, bytes, int | None], ...] = ()
    """What each updated file held before this run, for a caller that has to undo it.

    ``retire`` cannot answer this: it removes what the journal records, and an
    updated artifact existed before the run, so removing it would take away a
    working file, or a key whose previous value nothing else remembers."""
    created_dirs: tuple[Path, ...] = ()
    """Every directory this run itself brought into existence while placing a file.

    Reported by `FileSystem.make_dir`, called explicitly here rather than left
    to `write_atomic`'s own internal call for exactly this reason: the moment
    of creation is the only moment this fact is knowable, and a caller that
    only learns a placement's parent existed after the fact cannot tell "I
    made this" from "this was already here". A caller merges this into
    `Install.created_dirs` -- see that field's own docstring -- which is what
    later lets `retire` prune only what Pegasus actually created."""


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
    pruned: tuple[str, ...] = ()
    """Directories left empty by retirement and taken back along with it.

    Retiring a `file` or a `dependency-tree` removes what the journal
    recorded, but never the directory that held it -- a skill's directory, a
    dependency's version folder -- so the address stays a live file but its
    scaffolding does not. These are those directories, named relative to
    `config_dir` in POSIX form, deepest ones first where an ancestor and its
    child are both here. Never `config_dir` itself, and never one reached
    only through a symlink -- see `_prune_empty_directories`, which computes
    this."""


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
    claimed = _claimed_by_address(installed)
    steps = tuple(_step(filesystem, artifact, documents, owned, claimed) for artifact in artifacts)
    return Plan(cli=cli, steps=steps, retirements=retirements(installed, artifacts))


def record_address(entry: Record) -> tuple[str, Path, str | None] | None:
    """The slot ``entry`` occupies, when it occupies one at all.

    A ``file`` and an addressable ``config-key`` each hold one exclusive
    slot -- ``(kind, target, pointer)`` -- and two records can share that
    triple only if one has replaced the other. An appended list item is
    different: several distinct, simultaneously-valid records legitimately
    share the same ``(target, pointer)`` -- that pointer only ever names the
    *list*, never one item in it, so nothing about the triple picks one
    entry over its siblings. Returning ``None`` for it, rather than the
    triple, is what keeps every caller below from silently treating list
    siblings as the same slot -- see `_claimed_by_address`, `retirements`
    and, in `cli.py`, `_merged`.

    Public, unlike the rest of this module's journal-reading half: `cli.py`'s
    own merge of a completed run back into the journal needs the identical
    exclusion, on records rather than artifacts, and duplicating the append
    check there would let the two drift.
    """
    if entry.kind == "config-key" and entry.pointer is not None and _appends(entry.pointer):
        return None
    return entry.kind, entry.target, entry.pointer


def _claimed_by_address(installed: Install | None) -> dict[tuple[str, Path, str | None], Record]:
    """Every address this installation's journal already reclaims, keyed by
    the address itself rather than by the ``id`` recorded against it.

    An artifact's ``id`` is how the *current* render happens to name it, not
    what makes an address belong to this installation. A release is free to
    change the scheme that derives an `id` -- to make a rename visible, say --
    without a single byte on disk moving, and when it does, the journal entry
    written under the old scheme is still ours: same ``kind``, same
    ``target``, same ``pointer``. This map is how `_step` recognizes that
    entry even though `owned` (keyed by `id`) no longer finds it, so an `id`
    change alone never reads as a stranger's file to skip or an abandoned one
    to retire -- see `_file_step` and `_claimable` for the read side, and
    `retirements`, below, for the write side of the same rule.
    """
    if installed is None:
        return {}
    result: dict[tuple[str, Path, str | None], Record] = {}
    for entry in installed.entries:
        address = record_address(entry)
        if address is not None:
            result[address] = entry
    return result


def _artifact_address(artifact: Artifact) -> tuple[str, Path, str | None] | None:
    """The address `_claimed_by_address` would have recorded for this artifact,
    had a previous release already placed it. ``None`` for a shape with no
    exclusive slot of its own -- an append (see `record_address`) or a shape
    this module does not journal by address at all (there is none today, but
    `plan` already refuses any shape besides these two in
    `_refuse_duplicates`)."""
    if isinstance(artifact, FileArtifact):
        return "file", artifact.path, None
    if isinstance(artifact, ConfigKeyArtifact) and not _appends(artifact.pointer):
        return "config-key", artifact.path, artifact.pointer
    return None


def retirements(installed: Install | None, artifacts: Sequence[Artifact]) -> tuple[Record, ...]:
    """The journal entries this render no longer asks for.

    ``plan`` runs the loop the other way already: for every artifact, is this
    address still ours. That answers a placement's fate, but nothing in it
    ever asks the inverse question, for every entry the journal already
    holds, does the render still want it — an id absent from ``artifacts``
    never produces a step, so nothing would otherwise notice it is gone.

    Almost a set difference over ids, and nothing more: it takes no
    ``filesystem`` because it touches no disk, which is what makes it the
    purest thing in this module. ``installed.links`` are excluded by their
    type rather than by a condition here, the same way ``retire`` never looks
    at them — a link was never something Pegasus owned, so it is never
    something to retire.

    "Almost", because an id absent from ``artifacts`` is not, on its own,
    proof the render dropped the address: an `id` scheme change can rename
    every entry at once while every target stays exactly where it was (see
    `_claimed_by_address`). An entry is only actually unwanted when *neither*
    its `id` nor its address survives into this render — otherwise `_step`
    has already picked it back up under its new `id`, by address, as an
    `UPDATE` or `UNCHANGED`, and retiring it here would remove the very file
    (or key) that step just decided to keep. Excluding it here is therefore
    not an optimization: without it, `retire` running after `apply` -- which
    it must, for the reason documented at its call site -- would delete what
    `apply` just wrote.
    """
    if installed is None:
        return ()
    rendered_ids = {artifact.id for artifact in artifacts}
    rendered_addresses = {
        address for address in (_artifact_address(artifact) for artifact in artifacts) if address is not None
    }
    return tuple(
        entry
        for entry in installed.entries
        if entry.id not in rendered_ids and record_address(entry) not in rendered_addresses
    )


def _step(
    filesystem: FileSystem,
    artifact: Artifact,
    documents: dict[Path, Any],
    owned: dict[str, Record],
    claimed: dict[tuple[str, Path, str | None], Record],
) -> Step:
    digest = ownership.digest(artifact)
    entry = owned.get(artifact.id)
    if entry is None:
        # The `id` this release renders is not one the journal recognizes, but
        # the address it renders may still be one this installation already
        # holds under a different, older `id` -- see `_claimed_by_address`.
        # Falling back to the id lookup keeps every other case identical to
        # before: an `id` the journal does recognize is never second-guessed
        # by an address lookup that could only ever agree with it.
        address = _artifact_address(artifact)
        if address is not None:
            entry = claimed.get(address)
    if isinstance(artifact, FileArtifact):
        return _file_step(filesystem, artifact, digest, entry)
    return _key_step(artifact, documents.get(artifact.path), digest, entry)


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
    if current == digest and filesystem.mode_of(artifact.path) == filesystem.mode_for(executable=artifact.executable):
        # Both halves, because a fingerprint is of content and a permission is
        # not content. A program whose bit was wrong ships identical bytes.
        return Step(artifact=artifact, action=UNCHANGED, digest=digest, entry=entry, found=current)
    return Step(artifact=artifact, action=UPDATE, digest=digest, entry=entry, found=current)


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
    # The same read that decides the action answers who wrote what is there, so
    # `found` costs nothing here either. An append is left out on purpose: it is
    # located BY the recorded digest, so a value that disagrees with it is not
    # found at all, and "somebody edited ours" is indistinguishable from
    # "somebody deleted ours and added their own" -- see `_retire_key`, which
    # refuses the same claim for the same reason.
    found = ownership.digest_of_value(pointer.get_at(document, artifact.pointer))
    if found == digest:
        return Step(artifact=artifact, action=UNCHANGED, digest=digest, entry=entry, found=found)
    return Step(artifact=artifact, action=UPDATE, digest=digest, entry=entry, found=found)


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


def apply(
    filesystem: FileSystem, plan: Plan, *, at: str, on_step: Callable[[str], None] | None = None
) -> Applied:
    """Write everything the plan creates, or leave the home as it was found.

    Files go first and configuration documents second, so a failure has one
    kind of thing to undo at a time. Every configuration file is written once,
    which is what makes a half-applied document impossible.

    An update inherits from the record the plan judged it against, because a
    record is not only a fingerprint: it also carries what the user had before
    Pegasus took the address over, and that debt outlives every version written
    since.

    ``on_step``, when given, is told once per `Step` in ``plan.placements`` --
    never a document, even though several keys can share one write -- as soon
    as that step's own work is durable, naming it by the artifact's own `id`.
    This module reports the fact that a unit finished; it never counts a total
    or a fraction, because it does not know the plan's siblings -- dependencies
    fetched outside it, or retirements from a separate call -- that a caller
    composing a whole install's progress needs to add in.

    A caller's callback raising is that caller's bug, not this function's, but
    it must not be allowed to leave the home half-installed: the same rollback
    that answers a filesystem failure answers a broken callback too, and the
    original exception is what surfaces, so the bug is never swallowed.
    """
    created: list[Path] = []
    restorable: dict[Path, tuple[bytes | None, int | None]] = {}
    records: list[Record] = []
    created_dirs: list[Path] = []

    def _notify(unit: str) -> None:
        if on_step is None:
            return
        try:
            on_step(unit)
        except Exception as error:
            raise PlannerError(_undone(filesystem, created, restorable, error)) from error

    def _make_dir_for(path: Path) -> None:
        # Called explicitly, ahead of `write_atomic`, rather than left to that
        # call's own internal `make_dir` -- the moment of creation is the only
        # moment `FileSystem.make_dir` can say what it made, and by the time
        # `write_atomic` returns that answer is gone. Idempotent, so
        # `write_atomic`'s own call right after this one creates nothing and
        # reports nothing: this one already did. No mode is asked for here on
        # purpose, the same restraint `mode_for` already keeps this module
        # from ever choosing a permission bit itself: a POSIX mode is a
        # platform detail, and a bare literal naming one has no business in
        # `core/` at all (`test_architecture.NoPermissionOctalLiteralsTest`
        # holds every module here to that). Every implementation of this port
        # already carries its own ordinary, traversable default for a
        # directory nobody asked to be made private -- the same one
        # `write_atomic`'s own internal call has always used -- so this simply
        # defers to it instead of inventing one.
        created_dirs.extend(filesystem.make_dir(path.parent))

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
                _make_dir_for(step.artifact.path)
                filesystem.write_atomic(
                    step.artifact.path,
                    step.artifact.content,
                    mode=filesystem.mode_for(executable=step.artifact.executable),
                )
                if step.action == CREATE:
                    created.append(step.artifact.path)
                records.append(_file_record(filesystem, step, at))
                _notify(step.artifact.id)
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
            _make_dir_for(path)
            _write_document(filesystem, path, document, codec, restorable[path][1])
            records.extend(_key_record(step, at) for step in steps)
            for step in steps:
                _notify(step.artifact.id)
    except (FileSystemError, codecs.CodecError, pointer.PointerError) as error:
        raise PlannerError(_undone(filesystem, created, restorable, error)) from error
    return Applied(
        records=tuple(records),
        skipped=plan.collisions,
        unchanged=plan.unchanged,
        reconciled=_reconciled(filesystem, plan, at),
        created_dirs=tuple(created_dirs),
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


def _reconciled(filesystem: FileSystem, plan: Plan, at: str) -> tuple[Record, ...]:
    """The journal entries an unchanged artifact should already have had.

    "Already current" is decided against the disk; drift is reported against
    the journal. The two agree until a hand edit lands on exactly the bytes a
    later release renders: the disk is right, so nothing is written, so the
    journal keeps a digest from before -- and every later run reaches the same
    conclusion and writes nothing again, so the disagreement never resolves on
    its own. What makes it recoverable here is that an unchanged step already
    carries both halves of the answer, the digest of what is wanted and the
    entry it was judged against, so closing the gap costs no disk access at
    all.

    Only a step whose entry actually disagrees produces one. Recording the rest
    would put a journal write in every run of an install that did nothing.

    A changed ``id`` is exactly this kind of disagreement, and not a separate
    one invented for it. A release that renders the same bytes at the same
    address under a new `id` -- a scheme change with no content change behind
    it -- is picked up by `_step`'s address fallback (`_claimed_by_address`)
    as the same artifact, so the step still reads `UNCHANGED`; but the entry
    it was judged against still carries the *old* `id`, and nothing about the
    digest disagreeing captures that. Left alone, the journal would keep
    claiming this address under an `id` no render will ever produce again,
    forever -- the very address `retirements` is trusted, above, to leave
    alone precisely because some entry still claims it. Recording it here
    closes that loop the same way a digest mismatch does: for free, off a
    step that was already read.
    """
    return tuple(
        _file_record(filesystem, step, at)
        if isinstance(step.artifact, FileArtifact)
        else _key_record(step, at)
        for step in plan.unchanged
        if step.entry is not None
        and (step.entry.after_digest != step.digest or step.entry.id != step.artifact.id)
    )


def _file_record(filesystem: FileSystem, step: Step, at: str) -> Record:
    """The record for what was just written, keeping what only the old one knew."""
    entry = step.entry
    return Record(
        id=step.artifact.id,
        kind="file",
        target=step.artifact.path,
        after_digest=step.digest,
        created_at=entry.created_at if entry else at,
        mode=f"{filesystem.mode_for(executable=step.artifact.executable):04o}",
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


def _retire_files(
    filesystem: FileSystem,
    entries: list[Record],
    outcomes: dict[str, list[str]],
    on_step: Callable[[str], None] | None,
) -> None:
    for entry in entries:
        if filesystem.exists(entry.target):
            filesystem.remove(entry.target)
        outcomes["removed"].append(entry.id)
        if on_step is not None:
            on_step(entry.id)


def _retire_config_keys(
    filesystem: FileSystem,
    entries: list[Record],
    outcomes: dict[str, list[str]],
    on_step: Callable[[str], None] | None,
) -> None:
    for path, group in _group(entries, lambda entry: entry.target).items():
        codec = Codec(group[0].codec or Codec.JSON.value)
        document = _read_document(filesystem, path, codec)
        if document is None:
            # The file the user deleted takes every key in it with it, appended
            # items included: nothing survives that could be a changed version
            # of ours, so there is nothing ambiguous to report.
            outcomes["removed"].extend(entry.id for entry in group)
            if on_step is not None:
                for entry in group:
                    on_step(entry.id)
            continue
        mode = filesystem.mode_of(path)
        original = document
        for entry in group:
            document, outcome = _retire_key(document, entry)
            outcomes[outcome].append(entry.id)
            if on_step is not None:
                on_step(entry.id)
        if document != original:
            # Rewriting an unchanged file would reformat it for nothing. The
            # user's spacing is theirs, and we only spend it when we must.
            _write_document(filesystem, path, document, codec, mode)


def _retire_dependency_trees(
    filesystem: FileSystem,
    entries: list[Record],
    outcomes: dict[str, list[str]],
    on_step: Callable[[str], None] | None,
) -> None:
    """A dependency tree is a directory Pegasus materialized, not a file it
    wrote — taking it back means removing the whole tree, unconditionally,
    with the same "already gone counts as done" posture `remove` gives a
    single file. `filesystem.remove` is file-only by contract; a tree needs
    `remove_dir`."""
    for entry in entries:
        filesystem.remove_dir(entry.target)
        outcomes["removed"].append(entry.id)
        if on_step is not None:
            on_step(entry.id)


RETIRE_HANDLERS: dict[
    str, Callable[[FileSystem, list[Record], dict[str, list[str]], Callable[[str], None] | None], None]
] = {
    "file": _retire_files,
    "config-key": _retire_config_keys,
    "dependency-tree": _retire_dependency_trees,
}
"""How to take back each kind of journal entry, keyed by `journal.KINDS`.

The old shape of this function filtered `install.entries` twice, once per
kind it knew about; an entry whose kind matched neither filter fell into
neither list, and was never removed, and never reported — not even as
`unaccounted`. Keying the handlers by kind and checking the result against
`KINDS` below turns that into an import-time failure instead: a kind added
to the journal without a handler here stops this module from importing at
all, rather than leaking silently on whichever machine is the first to
produce one."""

_UNHANDLED_KINDS = sorted(KINDS - RETIRE_HANDLERS.keys())
if _UNHANDLED_KINDS:
    raise PlannerError("no retirement handler for kind(s): " + ", ".join(_UNHANDLED_KINDS))


def retire(
    filesystem: FileSystem, install: Install, *, on_step: Callable[[str], None] | None = None
) -> Retired:
    """Take back what the journal records, and only that.

    An address the journal records is removed unconditionally, whether or not
    the user changed it since — the same policy as install, in reverse. Links
    are never touched — Pegasus does not own a dependency that already existed.

    There is no rollback here, and none is needed: every operation is a no-op
    the second time, so an interrupted uninstall is finished by running it
    again.

    ``on_step``, when given, is told once per retired record, named by its own
    `id` -- the same identifier `apply` reported when it placed that record in
    the first place. There is no total here either, for the same reason
    ``apply`` has none: a caller composing one install's or uninstall's whole
    progress knows the record count from elsewhere already.
    """
    outcomes: dict[str, list[str]] = {"removed": [], "unaccounted": []}

    by_kind: dict[str, list[Record]] = {kind: [] for kind in KINDS}
    for entry in install.entries:
        by_kind[entry.kind].append(entry)

    for kind in sorted(KINDS):
        RETIRE_HANDLERS[kind](filesystem, by_kind[kind], outcomes, on_step)

    # `config-key` rewrites a document in place rather than removing a file,
    # so it is the one kind that never leaves a directory behind -- only
    # `file` and `dependency-tree` ever contribute a candidate to prune.
    candidates = [entry.target.parent for entry in (*by_kind["file"], *by_kind["dependency-tree"])]
    pruned = _prune_empty_directories(filesystem, install.config_dir, candidates, install.created_dirs)

    return Retired(
        removed=tuple(outcomes["removed"]),
        unaccounted=tuple(outcomes["unaccounted"]),
        kept_links=tuple(link.id for link in install.links),
        pruned=pruned,
    )


def _prune_empty_directories(
    filesystem: FileSystem, root: Path, candidates: list[Path], created: tuple[Path, ...]
) -> tuple[str, ...]:
    """Take back what retiring a file or a dependency tree left standing --
    but only the ground Pegasus itself broke.

    ``candidates`` is the immediate parent of every target retirement just
    removed; each is checked and, if empty, taken back, then its own parent is
    checked the same way, ascending until one is not empty, one was never
    created by Pegasus, or ``root`` is reached. ``root`` itself is never a
    candidate — the CLI's own configuration directory is not Pegasus's to
    remove, however empty it ends up.

    ``created`` is ``Install.created_dirs`` — every directory some `make_dir`
    call, on this install or an earlier one, actually reported creating. It is
    the one thing that tells a directory the person already had apart from one
    Pegasus put there: both can end up empty, and emptiness alone cannot
    distinguish them. A directory absent from this set is never removed, full
    stop, no matter how empty it is or how deep under a just-vacated candidate
    it sits — the ascent below stops the instant it reaches one, exactly the
    same stopping condition an occupied directory already gives it. An install
    recorded before this set was ever tracked carries an empty one, which
    means nothing under it is ever pruned; that is not a gap to route around,
    it is the correct, conservative answer for a fact that was never recorded
    (see `Install.created_dirs`).

    It does not heal itself on a later install or update, either: `make_dir`
    only reports what it actually creates, and by the time a CLI already
    installed before 5.28.0 is reinstalled or updated, the directories this
    set would need to name already exist, so nothing calls `make_dir` for
    them and `created_dirs` stays empty. Pruning applies to every install
    that started recording `created_dirs` from 5.28.0 onward; an install from
    before that keeps its empty directories, unmigrated, because telling a
    directory Pegasus made from one the person made, with no record that ever
    tracked the difference, is a guess -- and guessing here means deleting
    something that might not be Pegasus's to delete. Reaching that older
    installed base would need asking the person directly; that cannot be
    inferred from disk state and is separate work this function does not do.

    A candidate outside ``root`` entirely (a `dependency-tree` may live under
    the product's own data directory rather than under a CLI's configuration)
    is left alone: there is nothing here to ascend from it towards. This is
    also, incidentally, the same guarantee `journal._contained` gives every
    ``target`` and ``config_dir`` it parses — a `..` cannot buy a candidate a
    way past `root in candidate.parents` by resolving somewhere `is_relative_to`
    cannot see, because the journal already refuses to load a path shaped that
    way. The guarantee lives there, not here; this function only relies on it.

    Before a candidate is touched at all, every component of its absolute
    path — from the filesystem root down through the candidate itself, not
    only the portion under ``root`` — is checked with `is_symlink`. Any
    symlink in that chain stops the whole candidate cold — nothing below it
    or above it is pruned — because `remove_empty_dir` is a bare `os.rmdir`,
    which resolves every path component but the last, and a symlinked
    ancestor anywhere in the chain, including one standing above ``root``
    itself (``config_dir`` reached through a symlinked parent, say), would
    otherwise send it outside the tree entirely. `_contained` only refuses a
    `..` in the recorded path; it does not resolve anything, so a
    lexically-contained ``config_dir`` is no guarantee against this and the
    check here cannot be narrowed to ``root``'s own descendants. That check
    happens once, up front, against the chain as it stood before this
    candidate's own ascent — not re-run at every step of it — because every
    directory in that ascent is a prefix of the same already-checked chain.
    That single check does not close every window: a directory found to be
    real here can still be swapped for a symlink by something else on the
    machine in the moment between this check and the `os.rmdir` that later
    visits it, and nothing here re-checks at that instant. Closing that would
    need a check immediately before every single `rmdir`, atomic with it,
    which this port does not offer. Left open on purpose — closing it needs a
    local attacker with the same access Pegasus already has, in which case an
    empty directory is the least of what they could already do — but named
    here rather than implied away, because a reader of the paragraph above
    this one could otherwise take "checked once, up front" for "safe for the
    whole ascent."

    Processed deepest candidate first, so a child directory is gone before its
    parent is ever asked about, and each candidate is only ever visited once.
    """
    created_dirs = set(created)
    pruned: list[Path] = []
    # Sorted by the path *relative to* `root`, never by the candidate's own
    # absolute path: two installs of the same content into different homes
    # produce candidates whose absolute paths differ but whose structure
    # below `root` is identical, and a caller comparing their two reports --
    # the TUI against the equivalent CLI run, on separate throwaway homes --
    # needs the same tie-break both times. Sorting on the absolute path (or
    # relying on `set` iteration order) would let two candidates at the same
    # depth swap places from one home to the other for no reason connected to
    # what was actually pruned.
    under_root = {candidate for candidate in candidates if root in candidate.parents}
    ordered = sorted(
        under_root,
        key=lambda path: (-len(path.relative_to(root).parts), path.relative_to(root).as_posix()),
    )
    for candidate in ordered:
        if not _free_of_symlinks(filesystem, candidate):
            continue
        current = candidate
        while root in current.parents and current in created_dirs:
            if not filesystem.remove_empty_dir(current):
                break
            pruned.append(current)
            current = current.parent

    seen: set[str] = set()
    result: list[str] = []
    for path in pruned:
        relative = path.relative_to(root).as_posix()
        if relative not in seen:
            seen.add(relative)
            result.append(relative)
    return tuple(result)


def empty_directories_never_pruned(
    filesystem: FileSystem, config_dir: Path, created: tuple[Path, ...]
) -> tuple[str, ...]:
    """Every directory under ``config_dir`` that is empty right now and that
    `_prune_empty_directories` would never remove — because its ascent stops
    the instant it reaches a directory absent from ``created`` (`created_dirs`
    is exactly what that ascent checks membership against; see its own
    docstring for the pre-5.28.0 case that leaves it permanently empty for a
    whole install).

    This is a report, not a preview of a removal: nothing here is deleted, or
    ever will be by this call. Ownership is not claimed either way — a
    directory named here is not asserted to be one Pegasus made and lost track
    of, only that pruning, as it exists today, will never reach it. It could
    just as well be a sentinel some other program left meaningful; what it
    provably does not hold is someone else's *content*, which is the one thing
    naming an empty path can say without guessing whose the directory itself
    is.

    Walked depth-first from ``config_dir``, which is itself never a candidate
    — the same exclusion `_prune_empty_directories` applies to its own
    ``root``. A symlink anywhere in the walk stops descending into it, the
    same caution `_free_of_symlinks` applies before a real removal: this
    never removes anything, but reporting a path reached only through a link
    as if it sat under ``config_dir`` would misname where it actually is.

    This is `doctor`'s own walk, and `doctor` degrades rather than dying —
    a path this cannot probe (a permission bit denying it, say) is skipped
    silently rather than raised: calling this must never be the reason a
    diagnostic tool fails outright over one directory it could not read.
    """
    created_dirs = set(created)
    found: list[Path] = []

    def visit(path: Path) -> None:
        try:
            if filesystem.is_symlink(path):
                return
            names = filesystem.list_dir(path)
        except FileSystemError:
            return  # a file, or unreadable -- neither is an empty directory
        if not names:
            if path != config_dir and path not in created_dirs:
                found.append(path)
            return
        for name in names:
            visit(path / name)

    visit(config_dir)
    return tuple(sorted(str(path) for path in found))


def _free_of_symlinks(filesystem: FileSystem, candidate: Path) -> bool:
    """Whether every component of ``candidate``'s absolute path, from the
    filesystem root down through ``candidate`` itself, is a real directory.

    Walked from the filesystem root and not from ``config_dir``, because a
    symlink standing above the configuration root sends a later `os.rmdir`
    outside the tree exactly as well as one standing below it: `_contained`
    refuses a `..` in the recorded path but resolves nothing, so a
    ``config_dir`` that is lexically under the home can still be reached
    through a link. Checking only the half below the root left the other half
    unchecked, and an invariant enforced in one direction is where the bug
    gets in.

    One consequence worth knowing rather than discovering: on a machine whose
    home is itself reached through a symlink, no component of any candidate is
    symlink-free, so nothing is ever pruned there. That is the conservative
    side of the trade and it fails safe -- an empty directory survives -- but
    it does mean pruning is a property of the path a home sits on, not only of
    what Pegasus recorded.
    """
    current = Path(candidate.anchor)
    for part in candidate.relative_to(candidate.anchor).parts:
        current = current / part
        if filesystem.is_symlink(current):
            return False
    return True


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
