"""The port through which Pegasus builds and stocks its own private virtual environment.

Nothing above this port may spawn `venv` or `pip` directly, the same reason a
real HTTP fetch stays behind `Downloader` and a real `npm ci` stays behind
`NpmInstaller`: every decision built on top of it must be provable against a
double instead of a real interpreter and a real package index.

**One port, two operations, not two ports.** Making the environment and
stocking it are always asked of the same target directory, in the same order,
by the same caller, and every implementation that can do one can do the
other -- a real one runs `venv` then `pip`, a double records both calls and
raises nothing. Splitting them into two ports would multiply the seams
without buying an independent axis of substitution the way `Downloader` and
`NpmInstaller` do: those two fetch categorically different things (arbitrary
bytes from a URL versus a package graph resolved by npm), so a CLI's
descriptor genuinely chooses one or the other per server. A venv is never
built without also being stocked, so the split here would be a distinction
without a difference.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class VenvProvisionerError(Exception):
    """Pegasus's private virtual environment could not be built or stocked."""


@runtime_checkable
class VenvProvisioner(Protocol):
    """Everything Pegasus needs to own a private interpreter, offline-provable.

    Both methods are idempotent: calling either again against a directory it
    already produced succeeds without complaint, the same posture
    `FileSystem.make_dir` takes -- a launcher that reprovisions on every
    upgrade must not fail just because yesterday's run already got here.
    """

    def create(self, path: Path) -> None:
        """Build a virtual environment rooted at ``path``.

        Raises :class:`VenvProvisionerError` if the interpreter could not
        create it. Does not install anything into it; that is `install`.
        """

    def install(self, path: Path, *, requirements: Path, source: Path) -> None:
        """Stock the venv at ``path`` with its hash-pinned dependencies, then itself.

        ``requirements`` names a hash-pinned lockfile installed with
        ``--require-hashes``, so nothing lands that was not verified against a
        pin. ``source`` names the Pegasus checkout to install on top, with its
        own dependencies excluded -- ``requirements`` already accounted for
        them, and asking twice would let the two disagree about what a pin
        means. Raises :class:`VenvProvisionerError` if either step fails.
        """
