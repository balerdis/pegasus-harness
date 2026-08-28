"""Materializing a `download`-distributed MCP server: fetch, verify, place.

A server whose descriptor names the `download` distribution does not arrive
inside a CLI's configuration the way a skill or an agent prompt does -- it is
a binary Pegasus itself has to go and get. `render()` still has to name where
that binary will live, because the server's configuration key points at it,
and naming a path is pure arithmetic while fetching bytes is not: the two
stay apart on purpose. `target_dir` and `binary_path` are that shared
arithmetic -- an adapter's renderer and this module's own `materialize` call
the very same functions, so the two can never disagree about where a given
server's tree sits.

Verification happens before placement, never after: a mismatch raises before
`write_atomic` is ever called, so there is no file to remove when it fails --
none was ever written. Writing first and deleting on a failed check would
leave a crash window where "refused" becomes "half-installed", which is the
one thing this ordering exists to rule out.
"""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from pegasus.core import ownership
from pegasus.core.content import Distribution, Mcp
from pegasus.core.journal import Record
from pegasus.ports.downloader import Downloader, DownloaderError
from pegasus.ports.filesystem import FileSystem, FileSystemError


class MaterializeError(Exception):
    """A `download` server could not be safely fetched, verified, or placed."""


def target_dir(dependencies_dir: Path, item: Mcp) -> Path:
    """Where one server's materialized tree lives, at its pinned version.

    Named by id and version rather than by content: two versions of the same
    server are two different directories, and reinstalling the same version
    is what lets a later run recognise its own work without re-fetching it.
    """
    return dependencies_dir / item.name / item.version


def binary_path(dependencies_dir: Path, item: Mcp) -> Path:
    """Where the fetched asset itself lands, inside its version's directory."""
    return target_dir(dependencies_dir, item) / PurePosixPath(item.endpoint).name


def materialize(
    filesystem: FileSystem, downloader: Downloader, dependencies_dir: Path, item: Mcp, *, at: str
) -> Record:
    """Fetch ``item.endpoint``, verify it against ``item.checksum``, then place it.

    Raises :class:`MaterializeError` naming what was expected and what
    arrived, without ever calling `write_atomic` -- so a mismatch is refused
    with nothing left behind for a caller to clean up.
    """
    if item.distribution is not Distribution.DOWNLOAD:
        raise MaterializeError(f"{item.name}: not a 'download' server")
    try:
        fetched = downloader.fetch(item.endpoint)
    except DownloaderError as error:
        raise MaterializeError(f"{item.name}: could not fetch {item.endpoint}: {error}") from error
    digest = ownership.digest_of_bytes(fetched)
    if digest != item.checksum:
        raise MaterializeError(
            f"{item.name}: expected {item.checksum} but {item.endpoint} hashed to {digest}"
        )
    target = binary_path(dependencies_dir, item)
    try:
        filesystem.write_atomic(target, fetched, mode=filesystem.mode_for(executable=True))
    except FileSystemError as error:
        raise MaterializeError(
            f"{item.name}: fetched and verified, but could not be placed: {error}"
        ) from error
    return Record(
        id=f"dependency:{item.name}",
        kind="dependency-tree",
        target=target_dir(dependencies_dir, item),
        after_digest=digest,
        created_at=at,
    )
