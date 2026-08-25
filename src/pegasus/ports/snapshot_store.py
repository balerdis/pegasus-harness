"""Where a snapshot generation is kept.

:mod:`pegasus.core.snapshot` is pure: it knows what a manifest means, never
where it lives and never how its bytes reached disk. This port is the seam
that supplies both — the file contents captured on the way in, and the place
a generation is written to and read back from.

A snapshot exists for exactly one address: a file the journal already
reclaims, where the user edited it by hand. Installing and uninstalling both
overwrite what they own without asking, so nothing else keeps that edit
anywhere unless this store does.

The failure posture is deliberately asymmetric, in both directions at once.
**Writing a new generation must never depend on the health of the ones before
it.** An install that failed because some earlier, unrelated generation had
gone corrupt would be strictly worse than not snapshotting at all: the very
edit this store exists to protect would be lost, with nothing written in its
place to make up for it. So computing the next generation number treats a
sibling folder that is missing its manifest, or carries one that will not
parse, exactly like a folder that does not exist — never as a reason this
call may fail. **Reading a generation back is strict**, the same way the
journal is: asked for by number, a generation is either whole or an error,
never quietly treated as empty, because restoring garbage would put the
user's files into a state nobody chose.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, Sequence, runtime_checkable

from pegasus.core.snapshot import Manifest


class SnapshotStoreError(Exception):
    """A generation could not be written, or could not be read back and trusted."""


@dataclass(frozen=True)
class Capture:
    """One file as the installer found it, on its way into a new generation.

    ``content`` is the exact bytes read from ``path`` before something
    overwrote them; it is ``None`` exactly when ``existed`` is ``False``,
    mirroring :class:`pegasus.core.snapshot.Entry`, whose ``blob`` reference
    the store derives from this once the bytes are written.
    """

    path: Path
    existed: bool
    mode: str | None
    content: bytes | None


@runtime_checkable
class SnapshotStore(Protocol):
    def ensure_writable(self) -> None:
        """Raise :class:`SnapshotStoreError` now if :meth:`save` would be refused.

        Asked before an installation begins, for the same reason the journal
        store is: a refusal discovered after files were already overwritten
        would arrive with the user's edit already gone and nothing captured
        to recover it from.
        """

    def save(self, captures: Sequence[Capture], *, taken_at: str) -> int:
        """Write a new generation from the given captures and return its number.

        ``taken_at`` is the caller's clock, not this store's: every other
        timestamp Pegasus records — the journal's, the CLI report's — is
        injected from the composition root rather than read from the wall
        clock inside infra, and a snapshot's manifest is no exception.

        The blobs are written first and the manifest last, as the mark that
        the generation is complete — a crash partway through leaves a folder
        with no manifest, indistinguishable from one that was never started.

        The returned number is the highest existing generation plus one, or
        ``1`` when the store is empty. A sibling folder missing its manifest,
        or holding one that cannot be parsed, counts as absent for this
        purpose and never causes this call to fail.
        """

    def read(self, generation: int) -> Manifest:
        """Return the manifest for one generation.

        Raises :class:`SnapshotStoreError` when the generation does not exist
        or its manifest cannot be parsed. Unlike :meth:`save`, this never
        degrades: a caller asking to restore a specific generation needs to
        know whether it can be trusted, not be handed a guess.
        """
