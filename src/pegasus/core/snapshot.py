"""A snapshot generation manifest: what one capture holds, never where it lives.

Installing and uninstalling stop asking whether a file still matches what
Pegasus wrote last; they overwrite what they own regardless. That makes a
user's hand edit to an owned file disappear without a trace unless something
else remembers it first. This module is what remembers: a manifest names, for
every file one generation touched, whether it existed and what its bytes and
mode were. Capturing and restoring the bytes belongs to a store; this module
stays testable without a filesystem.

An entry that claims a blob for a path that never existed would assert bytes
that were never read from anywhere, so that combination cannot be constructed
at all — the invalid state is unreachable rather than merely rejected later.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SnapshotError(ValueError):
    """The manifest is malformed, so the generation it describes cannot be trusted."""


@dataclass(frozen=True)
class Entry:
    """One file as it stood before a generation overwrote it.

    ``existed`` is the fork in what restoring this entry means: ``True`` means
    put ``blob``'s bytes back at ``mode``, ``False`` means the address must go
    back to being empty. Because there is nothing to restore in the second
    case, there is also nothing to have captured — ``mode`` and ``blob`` must
    both be absent, or the manifest would claim bytes that were never written.

    ``is_directory`` is ``True`` for exactly one shape: a dependency tree that
    did not exist before the run this generation captured. It never appears
    alongside ``existed=True`` — a directory that was already there cannot be
    read back whole the way a file's bytes can, so this manifest only ever
    remembers its *absence*, never its contents. What that buys `restore` is
    narrow but real: the address must be emptied with `remove_dir`, a whole
    tree, rather than `remove`, a single file — and nothing wider than that
    is claimed.
    """

    path: Path
    existed: bool
    mode: str | None
    blob: str | None
    is_directory: bool = False

    def __post_init__(self) -> None:
        if not self.existed and (self.mode is not None or self.blob is not None):
            raise SnapshotError("an entry that did not exist cannot carry a mode or a blob reference")
        if self.existed and (not self.mode or not self.blob):
            raise SnapshotError("an entry that existed needs both a mode and a blob reference")
        if self.is_directory and self.existed:
            raise SnapshotError("a directory entry can only record that it did not exist -- its contents are never captured")


@dataclass(frozen=True)
class Manifest:
    """One generation: when it was captured, and what it captured.

    The date lives here, as data, rather than in whatever the store names the
    generation's folder — a folder name is address, not content, and the store
    is free to number generations however it needs to without the manifest
    caring.
    """

    taken_at: str
    entries: tuple[Entry, ...] = ()


# --- Serialization ---------------------------------------------------------


def to_dict(manifest: Manifest) -> dict[str, Any]:
    return {
        "taken_at": manifest.taken_at,
        "entries": [_entry_to_dict(entry) for entry in manifest.entries],
    }


def _entry_to_dict(entry: Entry) -> dict[str, Any]:
    payload: dict[str, Any] = {"path": str(entry.path), "existed": entry.existed}
    if entry.mode is not None:
        payload["mode"] = entry.mode
    if entry.blob is not None:
        payload["blob"] = entry.blob
    # Omitted rather than written as `false`: a manifest a released version
    # already wrote never had this key, and a manifest this version writes
    # for an ordinary file should read back identically to one that version
    # would have produced -- there is no reason for the two to differ on a
    # kind of entry neither of them is describing.
    if entry.is_directory:
        payload["is_directory"] = True
    return payload


def from_dict(payload: Any) -> Manifest:
    """Parse and validate. A manifest that fails here captured nothing usable."""
    if not isinstance(payload, dict):
        raise SnapshotError("the manifest must be an object")
    taken_at = payload.get("taken_at")
    if not isinstance(taken_at, str) or not taken_at:
        raise SnapshotError("the manifest needs taken_at")
    raw_entries = payload.get("entries", [])
    if not isinstance(raw_entries, list):
        raise SnapshotError("entries must be a list")
    return Manifest(taken_at=taken_at, entries=tuple(_entry_from_dict(item) for item in raw_entries))


def _entry_from_dict(payload: Any) -> Entry:
    if not isinstance(payload, dict):
        raise SnapshotError("each entry must be an object")
    path = _text(payload, "path")
    existed = payload.get("existed")
    if not isinstance(existed, bool):
        raise SnapshotError("an entry needs existed")
    mode = payload.get("mode")
    if mode is not None and not isinstance(mode, str):
        raise SnapshotError("mode must be a string")
    blob = payload.get("blob")
    if blob is not None and not isinstance(blob, str):
        raise SnapshotError("blob must be a string")
    is_directory = payload.get("is_directory", False)
    if not isinstance(is_directory, bool):
        raise SnapshotError("is_directory must be a boolean")
    return Entry(path=Path(path), existed=existed, mode=mode, blob=blob, is_directory=is_directory)


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SnapshotError(f"an entry needs {key!r}")
    return value
