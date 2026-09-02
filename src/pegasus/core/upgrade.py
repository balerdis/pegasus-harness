"""Fetching and verifying a newly published `pegasus` binary, ready to
replace the running one.

Mirrors `pegasus.core.dependencies`'s own verification discipline: fetch,
verify the digest, only then place -- a mismatch never reaches
`FileSystem.write_atomic` at all, so there is nothing on disk for a caller to
clean up when it happens. Unlike `dependencies`, there is no archive to
extract and only ever one file: the binary this whole release ships as.

`replace_binary` adds no second implementation of an atomic rename --
`FileSystem.write_atomic` already writes its temporary file into the
destination's own directory, `chmod`s it, and only then performs the one
`os.replace` that makes the swap atomic (see `pegasus.infra.fs_posix`'s own
docstring for the exact sequence). This module only supplies the two things
that call does not already know on its own: the mode a *program* needs, as
opposed to whatever `write_atomic`'s own default is for plain content, and
the destination's own existing mode to preserve rather than overwrite.

"Verified" here means checksum-matched, nothing more. The checksum is fetched
from the same host and the same release as the binary itself, so it catches
transit corruption, a truncated download, or an asset that was tampered with
on one side and not the other -- it does not prove who published either
file. Anyone who can publish a release can publish a checksum to match it;
there is no signature and no pinned key involved anywhere in this module.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.core import ownership
from pegasus.ports.downloader import Downloader, DownloaderError
from pegasus.ports.filesystem import FileSystem, FileSystemError

#: Every asset a release publishes, at this exact address -- see
#: `docs/release-distribution.md` (read-only from here: this module never
#: reads it, only agrees with it).
RELEASE_ASSET_URL = "https://github.com/balerdis/pegasus-harness/releases/download/{tag}/{asset}"


class UpgradeError(Exception):
    """A newly published `pegasus` binary could not be safely fetched, verified, or placed."""


def _tag(version: str) -> str:
    return f"v{version}"


def binary_url(version: str) -> str:
    return RELEASE_ASSET_URL.format(tag=_tag(version), asset="pegasus")


def checksum_url(version: str) -> str:
    return RELEASE_ASSET_URL.format(tag=_tag(version), asset="pegasus.sha256")


def _expected_digest(checksum_document: bytes) -> str:
    """The digest a `sha256sum`-style line names, in the same `sha256:<hex>`
    shape `ownership.digest_of_bytes` produces -- so the two can be compared
    directly, without either side ever caring how the other one spells it.

    Raises :class:`UpgradeError` when the document is empty, is not valid
    UTF-8, or does not even have a digest as its first token; a checksum
    asset this broken is not trustworthy enough to compare anything against.
    """
    try:
        text = checksum_document.decode("utf-8", errors="strict").strip()
    except UnicodeDecodeError as error:
        raise UpgradeError(f"the published checksum file is not valid UTF-8: {error}") from error
    first_line = text.splitlines()[0] if text else ""
    parts = first_line.split()
    if not parts:
        raise UpgradeError(f"the published checksum file is empty or malformed: {checksum_document!r}")
    return f"{ownership.PREFIX}{parts[0]}"


def fetch_and_verify(downloader: Downloader, version: str) -> bytes:
    """Fetch the `pegasus` binary published for ``version``, verified against
    its own published checksum.

    The checksum is fetched first, and the binary only once it is in hand --
    never the other way around, so a checksum that cannot be fetched at all
    never spends the (much larger) binary download for nothing. Raises
    :class:`UpgradeError` naming what was expected and what arrived on a
    mismatch, or wrapping whatever the downloader raised on either fetch.
    Writes nothing -- placing the verified bytes anywhere is
    :func:`replace_binary`'s job, never this function's.
    """
    try:
        checksum_document = downloader.fetch(checksum_url(version))
    except DownloaderError as error:
        raise UpgradeError(f"could not fetch the checksum for pegasus {version}: {error}") from error
    expected = _expected_digest(checksum_document)
    try:
        fetched = downloader.fetch(binary_url(version))
    except DownloaderError as error:
        raise UpgradeError(f"could not fetch pegasus {version}: {error}") from error
    digest = ownership.digest_of_bytes(fetched)
    if digest != expected:
        raise UpgradeError(
            f"checksum mismatch for pegasus {version}: expected {expected} but the download "
            f"hashed to {digest}; nothing was replaced"
        )
    return fetched


def replace_binary(filesystem: FileSystem, destination: Path, content: bytes) -> None:
    """Place ``content`` at ``destination`` with one atomic rename, last.

    Delegates entirely to `FileSystem.write_atomic`: it already writes a
    temporary file into ``destination``'s own directory, sets its mode, and
    only then performs the `os.replace` that makes the swap atomic -- there
    is no second implementation of that sequence here. What this adds is the
    mode that call is handed: `os.replace` swaps the inode wholesale, so
    nothing about ``destination``'s previous mode survives it on its own.

    An admin who deliberately narrowed the binary's mode -- to restrict
    execution to one group, say -- gets exactly that back rather than having
    it silently widened to the platform's plain executable default on every
    upgrade. The one case a straight carry-through would make worse is a
    preserved mode with no execute bit left in it at all: that would leave an
    unrunnable `pegasus` after upgrading, which defeats the point of
    upgrading more than widening ever would. `FileSystem.mode_ensuring_executable`
    is where that one exception is applied -- see its own docstring for
    exactly what it adds and what it leaves alone; the bit pattern itself is
    a platform fact, so it lives on that side of the port, not here.

    A destination that does not exist yet has nothing to preserve, so it
    gets the platform's plain executable mode, same as before mode
    preservation existed.
    """
    try:
        existing_mode = filesystem.mode_of(destination)
    except FileSystemError as error:
        raise UpgradeError(f"could not read the mode of {destination} before replacing it: {error}") from error
    if existing_mode is None:
        mode = filesystem.mode_for(executable=True)
    else:
        mode = filesystem.mode_ensuring_executable(existing_mode)
    try:
        filesystem.write_atomic(destination, content, mode=mode)
    except FileSystemError as error:
        raise UpgradeError(f"pegasus was verified but could not be placed at {destination}: {error}") from error
