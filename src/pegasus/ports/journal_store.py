"""Where the ownership journal is kept.

:mod:`pegasus.core.journal` is pure: it knows what a journal means, never where
it lives. This port is the seam between the two, and it exists for one practical
reason — the installer and the planner both need to be provable without a home
directory to write into, and an in-memory store makes that possible.

The contract is two operations and one refusal. Loading a journal that cannot be
understood must fail loudly: an unreadable journal is not an empty one, and
treating it as empty would orphan every artifact already installed.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pegasus.core.journal import Journal


class JournalStoreError(Exception):
    """The journal could not be read or written, so ownership is unknown."""


@runtime_checkable
class JournalStore(Protocol):
    def load(self) -> Journal:
        """Return the stored journal, or an empty one when nothing is stored yet.

        Raises :class:`JournalStoreError` when a journal exists but cannot be
        trusted. Never returns an empty journal to paper over damage.
        """

    def save(self, journal: Journal) -> None:
        """Persist the journal, replacing whatever was there.

        Raises :class:`JournalStoreError` when writing is refused or fails. A
        refusal must leave the stored journal exactly as it was.
        """
