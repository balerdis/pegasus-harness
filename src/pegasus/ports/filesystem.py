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
        """Whether anything is at this path. Never raises."""

    def read_bytes(self, path: Path) -> bytes:
        """Read a file whole. Raises :class:`FileSystemError` if it cannot be read."""

    # --- Writing ---

    def write_atomic(self, path: Path, content: bytes, *, mode: int = 0o644) -> None:
        """Write a file so that no reader ever sees it half-written.

        Missing parent directories are created. On success the file holds
        exactly ``content`` with exactly ``mode``; on failure the previous
        content survives untouched and no partial file is left behind. That
        guarantee is what lets an interrupted installation be rolled back
        against the journal instead of guessed at.
        """

    def remove(self, path: Path) -> None:
        """Delete a file.

        Removing something already absent is success: retiring an artifact the
        user deleted first is exactly the outcome Pegasus wanted.
        """

    def make_dir(self, path: Path, *, mode: int = 0o755) -> None:
        """Create a directory and its parents. Idempotent."""

    # --- Who is running ---

    def owned_by_current_user(self, path: Path) -> bool:
        """Whether this process's user owns the path. False when it does not exist.

        Stated as a question rather than as a user id because the answer, not
        the number behind it, is what the engine acts on.
        """

    def running_privileged(self) -> bool:
        """Whether this process holds administrative privileges.

        Pegasus installs into one person's home. Running privileged means every
        file it creates risks belonging to someone other than that person, so
        the engine refuses instead of leaving a home its owner cannot manage.
        """
