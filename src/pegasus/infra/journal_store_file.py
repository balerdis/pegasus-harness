"""The ownership journal, kept in the user's own data directory.

This store writes through the filesystem port rather than calling the operating
system itself, so the policy below — who may write, what may be written, what a
damaged file means — is provable without a real home directory.

Three refusals define it:

**Root may not write it.** A journal written by root records a home its owner
cannot manage, and every later uninstall would need root too.

**Only the home's owner may write it.** Pegasus installs into one person's home;
writing into someone else's is never what was asked for.

**Nothing outside the home may be recorded.** The core enforces containment when
reading. Enforcing it again on the way out means a bug upstream cannot mint an
entry that authorizes deleting ``/etc`` later.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.core import codecs, journal as journal_module
from pegasus.core.journal import Journal, JournalError
from pegasus.core.types import Codec
from pegasus.ports.filesystem import FileSystem, FileSystemError
from pegasus.ports.journal_store import JournalStoreError

FILENAME = "journal-v4.json"
DATA_DIR_MODE = 0o700
FILE_MODE = 0o600


def journal_path(filesystem: FileSystem, home: Path) -> Path:
    """Where the journal lives for a given home.

    The directory is the platform's own answer — see
    :meth:`FileSystem.data_dir` — and this is only the arithmetic on top of
    it: the journal's own filename, hung off wherever that call says Pegasus
    keeps its own state.

    The name carries the schema version. v4 is a clean install alongside v3, not
    a rewrite of it, so it must not open — let alone overwrite — v3's file.
    """
    return filesystem.data_dir(home) / FILENAME


class FileJournalStore:
    """The journal as a file under the target user's data directory."""

    def __init__(self, filesystem: FileSystem, *, home: Path, pegasus_version: str):
        self._fs = filesystem
        self._home = home
        self._version = pegasus_version
        self._path = journal_path(filesystem, home)

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> Journal:
        if not self._fs.exists(self._path):
            return journal_module.empty(self._version)
        try:
            raw = self._fs.read_bytes(self._path)
        except FileSystemError as error:
            raise JournalStoreError(f"the journal at {self._path} cannot be read: {error}") from error
        try:
            payload = codecs.loads(Codec.JSON, raw.decode("utf-8"))
        except (UnicodeDecodeError, codecs.CodecError) as error:
            raise JournalStoreError(f"the journal at {self._path} is not readable JSON: {error}") from error
        try:
            return journal_module.from_dict(payload, self._home)
        except JournalError as error:
            raise JournalStoreError(f"the journal at {self._path} is malformed: {error}") from error

    def ensure_writable(self) -> None:
        self._refuse_wrong_writer()

    def save(self, journal: Journal) -> None:
        self._refuse_wrong_writer()
        content = self._serialize(journal)
        try:
            self._fs.make_dir(self._path.parent, mode=DATA_DIR_MODE)
            self._fs.write_atomic(self._path, content, mode=FILE_MODE)
        except FileSystemError as error:
            raise JournalStoreError(f"the journal at {self._path} cannot be written: {error}") from error

    def _refuse_wrong_writer(self) -> None:
        if not self._fs.writable_on_behalf_of_owner(self._home):
            raise JournalStoreError(
                f"the journal at {self._path} must be written by the user who owns {self._home}; refusing to write it"
            )

    def _serialize(self, journal: Journal) -> bytes:
        """Render the journal, re-validating it on the way out.

        Round-tripping through the core's own parser is the cheapest way to be
        sure nothing unloadable — or uncontained — reaches disk.
        """
        payload = journal_module.to_dict(journal)
        try:
            journal_module.from_dict(payload, self._home)
        except JournalError as error:
            raise JournalStoreError(f"refusing to store an invalid journal: {error}") from error
        return codecs.dumps(Codec.JSON, payload).encode("utf-8")
