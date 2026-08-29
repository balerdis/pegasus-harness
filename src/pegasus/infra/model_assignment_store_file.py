"""Per-agent model preferences, kept as a file beside the ownership journal.

A preference is never a mutation of an installed artifact -- see
:mod:`pegasus.core.model_assignments` -- so it lives in its own file, under
the same directory the journal already uses, rather than inside the journal
itself. That is what keeps overwriting an artifact from ever being a risk to
ownership: the journal never learns of this file at all.

Same territory, same policy as the journal: written through the filesystem
port, refused for anyone but the home's own owner.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.core import codecs
from pegasus.core import model_assignments as model_assignments_module
from pegasus.core.model_assignments import ModelAssignmentError, ModelAssignments
from pegasus.core.types import Codec
from pegasus.infra.journal_store_file import DATA_DIR_MODE, FILE_MODE
from pegasus.ports.filesystem import FileSystem, FileSystemError
from pegasus.ports.model_assignment_store import ModelAssignmentStoreError

FILENAME = "model-assignments-v1.json"


def model_assignment_path(filesystem: FileSystem, home: Path) -> Path:
    """Where model assignments live for a given home. Arithmetic on top of
    :meth:`FileSystem.data_dir`, same as the journal's own path."""
    return filesystem.data_dir(home) / FILENAME


class FileModelAssignmentStore:
    """Model assignments as a file under the target user's data directory."""

    def __init__(self, filesystem: FileSystem, *, home: Path):
        self._fs = filesystem
        self._home = home
        self._path = model_assignment_path(filesystem, home)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> ModelAssignments:
        if not self._fs.exists(self._path):
            return model_assignments_module.empty()
        try:
            raw = self._fs.read_bytes(self._path)
        except FileSystemError as error:
            raise ModelAssignmentStoreError(
                f"the model assignments at {self._path} cannot be read: {error}"
            ) from error
        try:
            payload = codecs.loads(Codec.JSON, raw.decode("utf-8"))
        except (UnicodeDecodeError, codecs.CodecError) as error:
            raise ModelAssignmentStoreError(
                f"the model assignments at {self._path} are not readable JSON: {error}"
            ) from error
        try:
            return model_assignments_module.from_dict(payload)
        except ModelAssignmentError as error:
            raise ModelAssignmentStoreError(
                f"the model assignments at {self._path} are malformed: {error}"
            ) from error

    def save(self, assignments: ModelAssignments) -> None:
        self._refuse_wrong_writer()
        content = self._serialize(assignments)
        try:
            self._fs.make_dir(self._path.parent, mode=DATA_DIR_MODE)
            self._fs.write_atomic(self._path, content, mode=FILE_MODE)
        except FileSystemError as error:
            raise ModelAssignmentStoreError(
                f"the model assignments at {self._path} cannot be written: {error}"
            ) from error

    def _refuse_wrong_writer(self) -> None:
        if not self._fs.writable_on_behalf_of_owner(self._home):
            raise ModelAssignmentStoreError(
                f"the model assignments at {self._path} must be written by the user who owns "
                f"{self._home}; refusing to write it"
            )

    def _serialize(self, assignments: ModelAssignments) -> bytes:
        """Render the assignments, re-validating them on the way out, same
        discipline as the journal store's own `_serialize`."""
        payload = model_assignments_module.to_dict(assignments)
        try:
            model_assignments_module.from_dict(payload)
        except ModelAssignmentError as error:
            raise ModelAssignmentStoreError(f"refusing to store invalid model assignments: {error}") from error
        return codecs.dumps(Codec.JSON, payload).encode("utf-8")
