"""Where per-agent model preferences are kept.

Mirrors :mod:`pegasus.ports.journal_store`, for the same practical reason: the
engine and the CLI commands both need to be provable without a home directory
to write into.

Unlike the journal, a missing file is never a fault to raise past: no agent
starting without a model is the initial state, not damage.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from pegasus.core.model_assignments import ModelAssignments


class ModelAssignmentStoreError(Exception):
    """The stored assignments could not be read or written."""


@runtime_checkable
class ModelAssignmentStore(Protocol):
    def load(self) -> ModelAssignments:
        """Return the stored assignments, or an empty set when nothing is stored yet.

        Raises :class:`ModelAssignmentStoreError` when a file exists but cannot
        be trusted. Never returns an empty set to paper over damage.
        """

    def save(self, assignments: ModelAssignments) -> None:
        """Persist the assignments, replacing whatever was there.

        Raises :class:`ModelAssignmentStoreError` when writing is refused or
        fails.
        """
