"""The real venv provisioner: the standard library's `venv`, then `pip`, offline-verifiable only by its pins.

Nothing in this suite exercises this module, for the same reason nothing
exercises `infra.downloader_http` or `infra.npm_installer_subprocess`: every
test that needs a :class:`~pegasus.ports.venv_provisioner.VenvProvisioner`
reaches for the fake in ``tests/fakes.py`` instead, and no test ever
constructs this class. Proving *this* class correct against a real
interpreter and a real package index is outside what a hermetic suite can
promise, and is not attempted here; only the port's contract, exercised
through the fake, is.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from pegasus.ports.venv_provisioner import VenvProvisionerError

TIMEOUT_SECONDS = 600


class SubprocessVenvProvisioner:
    """Builds a venv with the running interpreter's own `venv` module, then stocks it with `pip`."""

    def create(self, path: Path) -> None:
        try:
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "venv", str(path)],
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise VenvProvisionerError(f"could not create a venv at {path}: {error}") from error

    def install(self, path: Path, *, requirements: Path, source: Path) -> None:
        python = path / "bin" / "python"
        try:
            subprocess.run(  # noqa: S603
                [str(python), "-m", "pip", "install", "--require-hashes", "-r", str(requirements)],
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=True,
            )
            subprocess.run(  # noqa: S603
                [str(python), "-m", "pip", "install", "--no-deps", str(source)],
                capture_output=True,
                timeout=TIMEOUT_SECONDS,
                check=True,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise VenvProvisionerError(f"could not stock the venv at {path}: {error}") from error
