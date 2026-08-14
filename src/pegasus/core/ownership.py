"""Fingerprints and collisions: what Pegasus may claim, and what it must not touch.

Two questions live here, and both are pure. Reading disk belongs to the planner;
what an answer *means* belongs to this module.

**Is this still ours?** A fingerprint taken at install time is the only evidence
Pegasus has that an artifact is still its own work and not something the user
rewrote. The fingerprint the catalog publishes and the one the journal stores
must be the same number, so both come from here — the catalog states an
intention, the journal records a fact, and a drift between the two would make
every uninstall find a mismatch and preserve everything forever.

**Is something already there?** Collisions are what keep the install additive.
A file that exists is skipped; a configuration key that already resolves is
skipped. Pegasus reports what it left alone rather than negotiating with it.
"""
from __future__ import annotations

import hashlib
from typing import Any

from pegasus.core import codecs, pointer
from pegasus.core.journal import Record
from pegasus.core.types import Artifact, ConfigKeyArtifact, FileArtifact

PREFIX = "sha256:"


class OwnershipError(ValueError):
    """An artifact shape this module was not asked to reason about."""


# --- Fingerprints ----------------------------------------------------------


def digest_of_bytes(payload: bytes) -> str:
    return f"{PREFIX}{hashlib.sha256(payload).hexdigest()}"


def digest_of_value(value: Any) -> str:
    """Hash a configuration value, independently of how it was spelled.

    Canonical rendering is what makes the digest stable: the same value built in
    a different key order must not look like an edit.
    """
    return digest_of_bytes(codecs.canonical_bytes(value))


def digest(artifact: Artifact) -> str:
    if isinstance(artifact, FileArtifact):
        return digest_of_bytes(artifact.content)
    if isinstance(artifact, ConfigKeyArtifact):
        return digest_of_value(artifact.value)
    raise OwnershipError(f"unsupported artifact shape: {type(artifact).__name__}")


# --- Collisions ------------------------------------------------------------


def occupies(artifact: ConfigKeyArtifact, document: Any) -> bool:
    """Whether this artifact's address already holds something in ``document``.

    A missing document leaves every address free. A value that happens to be
    empty is still the user's, so it counts as occupied: skipping is exactly
    what protects it.
    """
    if not isinstance(artifact, ConfigKeyArtifact):
        raise OwnershipError("only a configuration artifact is answered by a document")
    if document is None:
        return False
    return pointer.exists_at(document, artifact.pointer)


# --- Recognition -----------------------------------------------------------


def still_ours(entry: Record, current: str | None) -> bool:
    """Whether what is on disk now is still what Pegasus recorded.

    ``current`` is ``None`` when nothing is there any more, which counts as
    ours: retiring an artifact the user already deleted is the outcome Pegasus
    was after. Anything else that disagrees with the recorded fingerprint is the
    user's work now, and the invariant is that it is preserved and reported.
    """
    return current is None or current == entry.after_digest
