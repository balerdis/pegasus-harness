"""The real npm installer: `npm ci --ignore-scripts`, for a pinned package Pegasus does not vendor.

Nothing in this suite exercises this module, for the same reason nothing
exercises `infra.downloader_http`: every test that needs an
:class:`~pegasus.ports.npm_installer.NpmInstaller` reaches for the fake in
``tests/fakes.py`` instead, and no test ever constructs this class. Proving
*this* class correct against a real `npm` is outside what a hermetic suite
can promise, and is not attempted here; only the port's contract, exercised
through the fake, is.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from pegasus.ports.npm_installer import NpmInstallerError

TIMEOUT_SECONDS = 300


class SubprocessNpmInstaller:
    """Runs `npm ci --ignore-scripts` against a committed lockfile, offline."""

    def install(self, directory: Path) -> None:
        try:
            subprocess.run(  # noqa: S603
                ["npm", "ci", "--ignore-scripts"],
                cwd=directory,
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise NpmInstallerError(f"npm ci failed in {directory}: {error}") from error
