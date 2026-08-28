"""The port through which Pegasus resolves a pinned npm package.

Nothing above this port may run `npm` directly, the same reason a real HTTP
fetch stays behind `Downloader`: every decision built on top of it must be
provable against canned answers instead of a real registry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


class NpmInstallerError(Exception):
    """A pinned npm package could not be installed."""


@runtime_checkable
class NpmInstaller(Protocol):
    """Everything Pegasus needs to materialize one npm package, offline.

    `directory` already holds a `package.json` and a `package-lock.json`
    naming exactly the package this call installs; this is asked only to run
    `npm ci --ignore-scripts` against them, never to resolve anything itself.
    """

    def install(self, directory: Path) -> None:
        """Run `npm ci --ignore-scripts` in `directory`. Raises :class:`NpmInstallerError` on failure."""
