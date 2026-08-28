"""Materializing a `download`- or `npm`-distributed MCP server.

`download` fetches, verifies, and places one binary; `npm` writes a lockfile
pinning one package and asks npm's own chain to fetch and verify it. Both
share the one thing that makes either safe to retry: `target_dir` is named
by id and version, so a version already materialized costs no work at all.

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

import json
from pathlib import Path, PurePosixPath

from pegasus.core import ownership
from pegasus.core.content import Distribution, Mcp
from pegasus.core.journal import Record
from pegasus.ports.downloader import Downloader, DownloaderError
from pegasus.ports.filesystem import FileSystem, FileSystemError
from pegasus.ports.npm_installer import NpmInstaller, NpmInstallerError


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


def npm_script_path(dependencies_dir: Path, item: Mcp) -> Path:
    """Where the installed package's entry script lands, by absolute path.

    Under the same version's directory `npm ci` was run in, exactly where
    `node_modules/<package>/<entry>` would put it -- a scoped package's slash
    is part of that layout, not an escape from it, since `node_modules`
    nests a scope as a real subdirectory.
    """
    return target_dir(dependencies_dir, item) / "node_modules" / PurePosixPath(item.package) / item.entry


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


def materialize_npm(
    filesystem: FileSystem,
    installer: NpmInstaller,
    dependencies_dir: Path,
    item: Mcp,
    *,
    node_present: bool,
    at: str,
) -> Record:
    """Write a lockfile pinning ``item`` alone, then run `npm ci --ignore-scripts` against it.

    Node is a precondition, never something this materializes: ``node_present``
    is asked before a single byte reaches disk, so a missing Node is refused
    exactly as cleanly as a checksum mismatch is refused in `materialize` --
    nothing written, nothing to clean up. `npm ci` itself refuses a tarball
    that does not match the lockfile's own `integrity`, which is npm's chain
    rather than a hash Pegasus recomputes.
    """
    if item.distribution is not Distribution.NPM:
        raise MaterializeError(f"{item.name}: not an 'npm' server")
    if not node_present:
        raise MaterializeError(
            f"{item.name}: node is not on PATH; installing Node is the user's own responsibility, "
            f"Pegasus does not materialize a runtime"
        )
    target = target_dir(dependencies_dir, item)
    try:
        filesystem.write_atomic(target / "package.json", _package_json(item))
        filesystem.write_atomic(target / "package-lock.json", _package_lock_json(item))
    except FileSystemError as error:
        raise MaterializeError(f"{item.name}: could not write its lockfile: {error}") from error
    try:
        installer.install(target)
    except NpmInstallerError as error:
        _clean_up(filesystem, target)
        raise MaterializeError(f"{item.name}: npm ci failed: {error}") from error
    return Record(
        id=f"dependency:{item.name}",
        kind="dependency-tree",
        target=target,
        after_digest=item.integrity,
        created_at=at,
    )


def _clean_up(filesystem: FileSystem, target: Path) -> None:
    """Undo `write_atomic`'s own side effect: the ancestor directories it made.

    A failed install must take the version directory back out, and the id
    directory above it too if this was its only version, or a rolled-back
    install would survive as empty scaffolding.
    """
    try:
        filesystem.remove_dir(target)
        if not filesystem.list_dir(target.parent):
            filesystem.remove_dir(target.parent)
    except FileSystemError:
        pass


def _package_json(item: Mcp) -> bytes:
    """A minimal manifest naming exactly the one package this tree installs."""
    document = {"name": f"pegasus-{item.name}", "private": True, "dependencies": {item.package: item.version}}
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")


def _package_lock_json(item: Mcp) -> bytes:
    """The lockfile `npm ci` reads its version pin and integrity from.

    `resolved` and `integrity` are copied verbatim from the descriptor, which
    copies them verbatim from the registry's own metadata in turn.
    """
    document = {
        "name": f"pegasus-{item.name}",
        "lockfileVersion": 3,
        "requires": True,
        "packages": {
            "": {"name": f"pegasus-{item.name}", "dependencies": {item.package: item.version}},
            f"node_modules/{item.package}": {
                "version": item.version,
                "resolved": item.endpoint,
                "integrity": item.integrity,
            },
        },
    }
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")
