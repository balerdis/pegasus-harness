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

        Raises :class:`FileSystemError` when the path is there and its bits
        cannot be read, for the same reason `exists` raises rather than
        answering ``False``: a caller reads this to restore a file's own
        permissions and falls back to a default when it gets ``None``, and that
        default is right for a file being created and wrong for one whose bits
        were merely unreadable — it would put a ``0600`` file back as ``0644``.
        ``None`` has to mean absent and nothing else.
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

    # --- Locating ---

    def data_dir(self, home: Path) -> Path:
        """Where Pegasus keeps everything it manages of its own.

        The journal, snapshot generations, and anything else Pegasus itself
        needs to remember — as opposed to what it installs into a CLI's own
        configuration, which lives wherever that CLI already keeps its
        configuration. Where "its own" means on a given platform is exactly
        the question this method answers; Linux, macOS and Windows each put
        an application's private data somewhere different, and none of that
        disagreement belongs above this port.

        Two calls with the same ``home`` on the same platform always answer
        the same path.
        """

    def bin_dir(self, home: Path) -> Path:
        """Where a program installed for one person, not the whole machine, belongs on their `PATH`.

        This is the same question `data_dir` answers, asked about a different
        fact: `~/.local/bin` is a Linux convention that macOS and Windows do
        not share, so a launcher shim cannot hard-code it any more than
        Pegasus's own data can hard-code XDG. Two calls with the same
        ``home`` on the same platform always answer the same path.
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

    def is_writable(self, path: Path) -> bool:
        """Whether replacing or creating ``path`` would succeed, without writing anything.

        What actually governs that is the *containing directory's* write
        permission — plus, on POSIX, its sticky bit — never ``path``'s own
        permission bits. `os.replace` and creating a new file both act on the
        directory entry, not on the file's content in place, so this always
        asks the parent, whether ``path`` exists yet or not: an existing
        read-only file in a directory the caller may freely write into is
        writable by this definition, and a caller does not need to try and
        fail to find that out.

        Deliberately narrower than "would this exact call fully succeed": it
        says nothing about who owns ``path`` once it exists, only whether the
        operation itself is permitted at the filesystem level. A caller that
        must also refuse to take over a file it does not own — `pegasus
        upgrade` replacing its own binary, precisely — pairs this with
        :meth:`owned_by_current_user` rather than getting that from here. The
        two are kept separate on purpose: an earlier version of this method
        tested the target's own bits instead of the parent's, which was wrong
        on both sides (a read-only file in a writable directory answered
        `False` when the replace would in fact succeed; a world-writable
        sticky directory answered `True` for a file only its owner may
        replace) — and, as a side effect of testing the wrong thing, it also
        happened to block replacing a file owned by someone else. That
        protection now lives in :meth:`owned_by_current_user`, called
        explicitly wherever ownership actually matters, instead of riding
        along by accident.

        Exists so a caller that must refuse *before* doing anything else at
        all — `pegasus upgrade` replacing its own binary, chiefly, which must
        never reach the network when it already knows the replace could not
        land — can ask up front rather than fetch first and discover the
        refusal only once there is something to clean up.

        Never raises: an answer that cannot be told for certain is `False`,
        the same posture as a probe that failed — "unwritable" is always the
        safe reading when writability itself could not be determined.
        """

    def mode_ensuring_executable(self, mode: int) -> int:
        """``mode``, widened only enough to guarantee something with it can run.

        `pegasus upgrade` preserves whatever mode the binary it replaces
        already carries, rather than overwriting it with `mode_for`'s plain
        executable default -- an admin who deliberately narrowed it keeps
        exactly what they chose (see `pegasus.core.upgrade.replace_binary`'s
        own docstring). The one case a straight carry-through would make
        worse is a mode with no execute bit left in it at all, which would
        leave an unrunnable program in place after every upgrade -- strictly
        worse than the widening this whole scheme exists to avoid. This is
        where that one exception is applied: a mode that already lets its
        owner execute it passes through completely unchanged; one that does
        not gets just enough added to run, and nothing else about it --
        including any narrowed group or other permission -- is touched.

        What "just enough" means is itself a platform fact this method keeps
        on this side of the port, same as `mode_for`: an owner-only execute
        bit on POSIX, whatever the nearest equivalent is anywhere else.
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

    def owned_by_current_user(self, path: Path) -> bool:
        """Whether the user running this process owns ``path``.

        `os.replace` swaps the inode outright, so a caller that writes over
        someone else's file ends up handing its ownership to whoever ran the
        process — silently, since nothing about a successful replace records
        whose file it used to be. This is how a caller refuses that takeover
        *before* it happens: `pegasus upgrade` calls it on the binary it is
        about to replace, paired with :meth:`is_writable` rather than folded
        into it, because a directory being writable and a file being *yours*
        are two different facts, and a caller may need either one without the
        other.

        `False` for a path that does not exist, is owned by someone else, or
        whose owner could not be determined — the same posture
        :meth:`writable_on_behalf_of_owner` takes: an answer that cannot be
        told for certain reads as "not mine", never as a guess in either
        direction.
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
