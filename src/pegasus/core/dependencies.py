"""Materializing a `download`- or `npm`-distributed MCP server.

`download` fetches, verifies, and places one binary; `npm` writes the
descriptor's own lockfile -- shipped with it, never synthesized here -- and
asks npm's own chain to fetch and verify everything that lockfile pins. Both
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

import io
import json
import tarfile
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
    """Where the fetched asset itself lands, inside its version's directory.

    Only meaningful for a `download` server that fetches a bare binary: an
    archive's own asset -- the `.tar.gz` itself -- is never placed on disk at
    all, only the members inside it, so a caller after the program to run
    wants :func:`program_path` instead.
    """
    return target_dir(dependencies_dir, item) / PurePosixPath(item.endpoint).name


def program_path(dependencies_dir: Path, item: Mcp) -> Path:
    """Where the program a `download` server runs lands, whichever form it took.

    A bare binary places itself there directly, so this is `binary_path`; an
    archive places its declared `archive_executable` member there instead --
    the one file, of everything the archive held, that a CLI's configuration
    should point at.
    """
    if item.archive_executable is not None:
        return target_dir(dependencies_dir, item) / PurePosixPath(item.archive_executable)
    return binary_path(dependencies_dir, item)


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
    with nothing left behind for a caller to clean up. Extraction, when
    ``item`` declares an archive, happens only after that verification, for
    the same reason: a digest proves the bytes are the ones that were
    pinned, never that placing them is safe, so verification comes first and
    extraction's own refusals come after it, not instead of it.
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
    target_root = target_dir(dependencies_dir, item)
    if item.archive_members:
        _extract_archive(filesystem, fetched, target_root, item)
    else:
        try:
            filesystem.write_atomic(
                binary_path(dependencies_dir, item), fetched, mode=filesystem.mode_for(executable=True)
            )
        except FileSystemError as error:
            raise MaterializeError(
                f"{item.name}: fetched and verified, but could not be placed: {error}"
            ) from error
    program_relpath, program_digest = _program_digest(filesystem, target_root, program_path(dependencies_dir, item))
    return Record(
        id=f"dependency:{item.name}",
        kind="dependency-tree",
        target=target_root,
        after_digest=digest,
        created_at=at,
        program_relpath=program_relpath,
        program_digest=program_digest,
    )


def _extract_archive(filesystem: FileSystem, archive_bytes: bytes, target_root: Path, item: Mcp) -> None:
    """Place every member ``item.archive_members`` names, inside ``target_root``.

    Every member is read and checked before the first byte is written: the
    same posture `materialize` already holds between fetching and placing --
    a refusal must never share a run with a partial write. `tarfile.data_filter`
    is what checks each member, chosen over `tar_filter` and
    `fully_trusted_filter` because it is the one PEP 706 wrote for exactly
    this case -- extracting an archive whose contents are not trusted. It
    refuses a member whose own path would resolve outside the destination
    (an absolute path or a `..` escape), and refuses a symbolic or hard link
    whose *target* resolves outside it, even when the member's own name is
    innocent -- exactly the class of escape this exists to close. Calling it
    here, against a destination that never has to exist on disk, is what
    makes that check provable without a real filesystem: only `write_atomic`,
    called afterwards for a member the filter already accepted, ever
    actually places a byte.
    """
    try:
        with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as archive:
            payloads = list(_verified_members(archive, target_root, item))
    except tarfile.TarError as error:
        raise MaterializeError(f"{item.name}: could not open its archive: {error}") from error
    try:
        for name, content in payloads:
            executable = name == item.archive_executable
            filesystem.write_atomic(
                target_root / PurePosixPath(name), content, mode=filesystem.mode_for(executable=executable)
            )
    except FileSystemError as error:
        _clean_up(filesystem, target_root)
        raise MaterializeError(
            f"{item.name}: extracted and verified, but could not be placed: {error}"
        ) from error


def _verified_members(archive: tarfile.TarFile, target_root: Path, item: Mcp):
    for name in item.archive_members:
        try:
            info = archive.getmember(name)
        except KeyError as error:
            raise MaterializeError(f"{item.name}: its archive has no member named {name!r}") from error
        try:
            tarfile.data_filter(info, str(target_root))
        except tarfile.FilterError as error:
            raise MaterializeError(f"{item.name}: refused to extract {name!r}: {error}") from error
        if not info.isfile():
            raise MaterializeError(f"{item.name}: declared member {name!r} is not a regular file")
        extracted = archive.extractfile(info)
        yield name, extracted.read() if extracted is not None else b""


def materialize_npm(
    filesystem: FileSystem,
    installer: NpmInstaller,
    dependencies_dir: Path,
    item: Mcp,
    *,
    node_present: bool,
    at: str,
) -> Record:
    """Write the descriptor's own lockfile, then run `npm ci --ignore-scripts` against it.

    Node is a precondition, never something this materializes: ``node_present``
    is asked before a single byte reaches disk, so a missing Node is refused
    exactly as cleanly as a checksum mismatch is refused in `materialize` --
    nothing written, nothing to clean up. `npm ci` itself refuses a tarball
    that does not match the lockfile's own `integrity`, which is npm's chain
    rather than a hash Pegasus recomputes.

    `package-lock.json` is written verbatim from ``item.npm_lockfile`` -- the
    real lockfile the descriptor shipped, pinning every package the one it
    names actually depends on -- never synthesized here. `package.json` is
    still built from the descriptor's own fields, but its own `name` comes
    from ``item.npm_package_name`` -- the lockfile's own root name, not the
    descriptor's file stem -- because the loader already checked, at load
    time, that the lockfile's root entry pins the exact same name, package,
    and version this produces; deriving the name from the file stem instead
    would agree with the lockfile only by coincidence.
    """
    if item.distribution is not Distribution.NPM:
        raise MaterializeError(f"{item.name}: not an 'npm' server")
    if not node_present:
        raise MaterializeError(
            f"{item.name}: node is not on PATH; installing Node is the user's own responsibility, "
            f"Pegasus does not materialize a runtime"
        )
    if item.npm_lockfile is None or item.npm_package_name is None:
        raise MaterializeError(f"{item.name}: has no lockfile to install from")
    target = target_dir(dependencies_dir, item)
    try:
        filesystem.write_atomic(target / "package.json", _package_json(item))
        filesystem.write_atomic(target / "package-lock.json", item.npm_lockfile)
    except FileSystemError as error:
        raise MaterializeError(f"{item.name}: could not write its lockfile: {error}") from error
    try:
        installer.install(target)
    except NpmInstallerError as error:
        _clean_up(filesystem, target)
        raise MaterializeError(f"{item.name}: npm ci failed: {error}") from error
    program_relpath, program_digest = _program_digest(filesystem, target, npm_script_path(dependencies_dir, item))
    return Record(
        id=f"dependency:{item.name}",
        kind="dependency-tree",
        target=target,
        after_digest=item.integrity,
        created_at=at,
        program_relpath=program_relpath,
        program_digest=program_digest,
    )


def _program_digest(filesystem: FileSystem, target_root: Path, program: Path) -> tuple[str | None, str | None]:
    """The one fact `doctor` can later check cheaply: not the whole tree, the
    program a CLI's configuration will actually run.

    Read back rather than assumed, for both callers: `materialize` already
    holds the fetched bytes in memory, but reading the placed file instead
    is what one code path can share with `materialize_npm`, whose own write
    is `npm ci`'s, not this module's -- a descriptor whose declared entry
    `npm ci` did not produce (a stale or wrong `entry` field) must not stop
    an install `npm ci` itself already accepted. Recording nothing here is
    exactly what a journal written before this pair existed also carries,
    and `doctor` already knows what that means: nothing to check, not
    something checked and found wanting.
    """
    try:
        content = filesystem.read_bytes(program)
    except FileSystemError:
        return None, None
    return str(program.relative_to(target_root)), ownership.digest_of_bytes(content)


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
    """A minimal manifest naming exactly the one package this tree installs.

    ``name`` is ``item.npm_package_name`` -- the shipped lockfile's own root
    name -- rather than something derived from ``item.name``, the descriptor's
    file stem: the two need not match (`playwright.md` ships a lockfile whose
    root package is named `pegasus-playwright-mcp`), and `npm ci` checks this
    field against the lockfile's own, so only the lockfile's own value is
    guaranteed to agree with it.
    """
    document = {
        "name": item.npm_package_name,
        "private": True,
        "dependencies": {item.package: item.version},
    }
    return (json.dumps(document, indent=2) + "\n").encode("utf-8")
