"""The port through which Pegasus touches disk.

Two reasons this is a port and not a handful of calls to :mod:`os`.

**Platforms disagree.** Atomic replacement, permission bits and what "the user
who owns this home" means are spelled differently on POSIX and on Windows. The
engine states the intention; an implementation per platform supplies the
spelling.

**Installation must be testable.** Everything above this line can run against an
in-memory implementation, so the engine's decisions are provable without a home
directory to ruin.

The vocabulary stays deliberately small. Every method here exists because the
installer needs it; a filesystem is far larger than this, and the parts Pegasus
does not need are parts no implementation has to get right.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class FileSystemError(Exception):
    """A filesystem operation failed.

    Implementations translate whatever their platform raises into this, so the
    engine can handle failure without importing platform errors.
    """


@runtime_checkable
class FileSystem(Protocol):
    """Everything Pegasus needs from a disk."""

    # --- Reading ---

    def exists(self, path: Path) -> bool:
        """Whether anything is at this path.

        Raises :class:`FileSystemError` when that cannot be told — an
        unreadable parent directory, most often — rather than returning
        ``False``. ``False`` means absent, and a caller that treats "cannot
        tell" as "absent" can go on to delete or overwrite something that was
        there all along; a bool cannot carry both meanings without one of
        them lying.
        """

    def read_bytes(self, path: Path) -> bytes:
        """Read a file whole. Raises :class:`FileSystemError` if it cannot be read."""

    def mode_of(self, path: Path) -> int | None:
        """The permission bits of an existing path, or ``None`` when it is absent.

        Pegasus writes into files the user already owns — a CLI's settings file
        is theirs, not ours. Rewriting one means putting its own permissions
        back, so this exists to make that possible instead of quietly widening
        or narrowing who can read it.
        """

    def list_dir(self, path: Path) -> list[str]:
        """Names of the entries directly inside a directory, sorted.

        A path that does not exist lists as empty, consistent with
        :meth:`remove`: what is absent is not an error. Sorting is not needed
        by anything that only computes a maximum, but a port that returned
        entries in arbitrary order would make every caller's tests brittle.
        Raises :class:`FileSystemError` when the path exists but is a file,
        and the same when it cannot be told whether the path exists at all —
        an unreadable directory does not list as empty; that would say
        nothing is there when the truth is only that it could not be seen.
        """

    # --- Permissions ---

    def mode_for(self, *, executable: bool) -> int:
        """The permission bits a file this platform creates should carry.

        The engine states one fact about an artifact — whether it is a
        program or plain text — and never a permission number; turning that
        fact into the bits a real filesystem understands is exactly the
        platform decision this method exists to answer. Two artifacts asking
        the same question always get the same answer here, on one platform.
        """

    # --- Writing ---

    def write_atomic(self, path: Path, content: bytes, *, mode: int) -> None:
        """Write a file so that no reader ever sees it half-written.

        Missing parent directories are created. On success the file holds
        exactly ``content`` with exactly ``mode``; on failure the previous
        content survives untouched and no partial file is left behind. That
        guarantee is what lets an interrupted installation be rolled back
        against the journal instead of guessed at.

        There is no default: what an artifact's permissions should be is a
        decision the engine has already made by the time this is called, and
        a port that guessed one would let a forgotten argument ship a file
        with permissions nobody chose. An implementation is free to default
        its own signature for calls this port does not make itself.
        """

    def remove(self, path: Path) -> None:
        """Delete a file.

        Removing something already absent is success: retiring an artifact the
        user deleted first is exactly the outcome Pegasus wanted.
        """

    def remove_dir(self, path: Path) -> None:
        """Delete a directory and everything inside it.

        Retention deletes whole generation folders, never single files inside
        them, so this is a distinct operation from :meth:`remove` rather than
        a loop built on top of it. Removing something already absent is
        success, the same posture as :meth:`remove`: a retention pass that
        runs twice must not fail on the second run just because the first one
        already cleared the folder away.
        """

    def make_dir(self, path: Path, *, mode: int) -> None:
        """Create a directory and its parents. Idempotent.

        ``mode`` applies **only to directories this call creates**. A directory
        that already exists keeps the permissions it has, and so do parents
        created along the way. Asking for ``0o700`` is therefore a request about
        a new directory, never a guarantee about the one you end up with.

        That is the additive contract, not a shortcoming: tightening a directory
        Pegasus did not create in this installation would mutate something it
        does not own. Callers that need a guarantee must state it about the
        files they write, where ``write_atomic`` does enforce the mode.

        There is no default: whether a directory should be private or
        traversable is exactly the distinction this call exists to state, and
        a port that assumed one for a caller who forgot would decide it by
        accident.
        """

    # --- Who is running ---

    def writable_on_behalf_of_owner(self, home: Path) -> bool:
        """Whether this process may write into ``home`` as the person who owns it.

        ``False`` collapses three different facts into one, deliberately:
        this process is not the home's owner; this process holds
        administrative privileges, so anything it creates risks belonging to
        someone other than the owner even if the home happens to be theirs;
        or ownership could not be determined at all. Pegasus installs into
        one person's home, and every one of those three cases is a reason to
        refuse rather than to write — so the engine only ever needs the
        single bit, never which of the three produced it.
        """
