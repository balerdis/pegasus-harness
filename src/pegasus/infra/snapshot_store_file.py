"""Snapshot generations, kept in the user's own data directory.

This store writes through the filesystem port rather than calling the
operating system itself, so the numbering and refusal policy below is
provable without a real home directory.

Generations live in a folder numbered with an ever-increasing integer, hung
off the same directory the journal already lives in — ``snapshots_root``
derives that location from :mod:`pegasus.infra.journal_store_file` instead of
restating it, so the two stores can never drift apart on where "home" means.
Inside a generation's folder sits ``manifest.json`` plus one blob file per
captured entry that existed.

The refusal mirrors the journal store's: root may not write it, and only the
home's owner may.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

from pegasus.core import codecs, snapshot as snapshot_module
from pegasus.core.snapshot import Entry, Manifest, SnapshotError
from pegasus.core.types import Codec
from pegasus.infra.journal_store_file import DATA_DIR, DATA_DIR_MODE, FILE_MODE
from pegasus.ports.filesystem import FileSystem, FileSystemError
from pegasus.ports.snapshot_store import Capture, SnapshotStoreError

SNAPSHOTS_DIRNAME = "snapshots"
MANIFEST_FILENAME = "manifest.json"
GENERATION_WIDTH = 6
BLOB_WIDTH = 4


def snapshots_root(home: Path) -> Path:
    """Where snapshot generations live for a given home. Pure path arithmetic."""
    return home / DATA_DIR / SNAPSHOTS_DIRNAME


def _generation_name(generation: int) -> str:
    return f"{generation:0{GENERATION_WIDTH}d}"


def _blob_name(index: int) -> str:
    return f"{index:0{BLOB_WIDTH}d}.blob"


class FileSnapshotStore:
    """A snapshot generation as a folder under the target user's data directory."""

    def __init__(self, filesystem: FileSystem, *, home: Path):
        self._fs = filesystem
        self._home = home
        self._data_dir = home / DATA_DIR
        self._root = snapshots_root(home)

    @property
    def root(self) -> Path:
        return self._root

    def ensure_writable(self) -> None:
        self._refuse_wrong_writer()

    def save(self, captures: Sequence[Capture], *, taken_at: str) -> int:
        self._refuse_wrong_writer()
        for capture in captures:
            if capture.existed and capture.content is None:
                raise SnapshotStoreError(
                    f"{capture.path} is marked as existing but carries no content to capture"
                )
        generation = self._next_generation()
        folder = self._root / _generation_name(generation)
        self._make_directories(folder)
        entries = []
        for index, capture in enumerate(captures, start=1):
            blob = None
            if capture.existed:
                blob = _blob_name(index)
                try:
                    self._fs.write_atomic(folder / blob, capture.content, mode=FILE_MODE)
                except FileSystemError as error:
                    raise SnapshotStoreError(f"cannot write a blob for {capture.path}: {error}") from error
            try:
                entries.append(Entry(path=capture.path, existed=capture.existed, mode=capture.mode, blob=blob))
            except SnapshotError as error:
                raise SnapshotStoreError(f"cannot capture {capture.path}: {error}") from error
        manifest = Manifest(taken_at=taken_at, entries=tuple(entries))
        self._write_manifest(folder, manifest)
        return generation

    def _make_directories(self, folder: Path) -> None:
        """Create every level this store owns at the journal's private mode.

        Each level is created explicitly, and in this order, before anything
        is written underneath it. Relying on ``write_atomic``'s implicit
        parent creation instead would leave every level but the deepest one
        at the platform default: :meth:`make_dir`'s mode only ever applies to
        the directory a call actually creates, so a level that already exists
        by the time this store gets to it — because a blob was written into
        it first — keeps whatever mode it was born with. On a fresh machine
        this store is routinely the first thing to create the directory the
        journal also lives in, so getting that one wrong is not cosmetic.
        """
        try:
            self._fs.make_dir(self._data_dir, mode=DATA_DIR_MODE)
            self._fs.make_dir(self._root, mode=DATA_DIR_MODE)
            self._fs.make_dir(folder, mode=DATA_DIR_MODE)
        except FileSystemError as error:
            raise SnapshotStoreError(f"cannot create {folder}: {error}") from error

    def read(self, generation: int) -> Manifest:
        folder = self._root / _generation_name(generation)
        manifest_path = folder / MANIFEST_FILENAME
        if not self._fs.exists(manifest_path):
            raise SnapshotStoreError(f"no snapshot generation {generation} exists")
        try:
            raw = self._fs.read_bytes(manifest_path)
        except FileSystemError as error:
            raise SnapshotStoreError(f"the manifest at {manifest_path} cannot be read: {error}") from error
        try:
            payload = codecs.loads(Codec.JSON, raw.decode("utf-8"))
        except (UnicodeDecodeError, codecs.CodecError) as error:
            raise SnapshotStoreError(f"the manifest at {manifest_path} is not readable JSON: {error}") from error
        try:
            return snapshot_module.from_dict(payload)
        except SnapshotError as error:
            raise SnapshotStoreError(f"the manifest at {manifest_path} is malformed: {error}") from error

    def _next_generation(self) -> int:
        """The number after the highest any folder has already claimed.

        Numbering counts folders, not manifests, and the two questions are not
        the same one. A folder with no manifest is a save that died before it
        finished, and what it left behind is still a copy of someone's file.
        Handing its number to the next save would write a fresh generation on
        top of a half-written one: the blobs whose index the new capture
        happens to reuse get overwritten, and the ones it does not reach are
        stranded beside a manifest that never mentions them. Spending the
        number instead leaves the dead attempt whole, and costs only a gap in
        the sequence.
        """
        return max(self._claimed_generations(), default=0) + 1

    def _claimed_generations(self) -> list[int]:
        """Every folder that has taken a number, finished or not."""
        return [int(name) for name in self._fs.list_dir(self._root) if name.isdigit()]

    def _write_manifest(self, folder: Path, manifest: Manifest) -> None:
        content = codecs.dumps(Codec.JSON, snapshot_module.to_dict(manifest)).encode("utf-8")
        try:
            self._fs.write_atomic(folder / MANIFEST_FILENAME, content, mode=FILE_MODE)
        except FileSystemError as error:
            raise SnapshotStoreError(f"cannot write the manifest at {folder}: {error}") from error

    def _refuse_wrong_writer(self) -> None:
        if self._fs.running_privileged():
            raise SnapshotStoreError(
                "a snapshot must be written by the user who owns the home, never by root"
            )
        if not self._fs.owned_by_current_user(self._home):
            raise SnapshotStoreError(f"{self._home} belongs to another user; refusing to write its snapshot")
