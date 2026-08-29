"""Provisioning the private virtual environment Pegasus runs from.

The launcher shim in `bin/pegasus` runs before Pegasus is importable, so it
cannot ask `pegasus.ports.filesystem.FileSystem.data_dir` where its venv
lives; it mirrors that computation in shell instead, and the comment at the
top of that file says so. This module is the other half: what actually builds
and stocks the venv the shim expects to find, and whether the directory the
shim gets copied into is one a person can already reach without touching it.
"""
from __future__ import annotations

from pathlib import Path

from pegasus.ports.venv_provisioner import VenvProvisioner

VENV_DIRNAME = "venv"
SHIM_NAME = "pegasus"


def venv_dir(data_dir: Path) -> Path:
    """Where the private venv sits inside Pegasus's own data directory."""
    return data_dir / VENV_DIRNAME


def provision(provisioner: VenvProvisioner, *, venv: Path, requirements: Path, source: Path) -> None:
    """Build the venv, then stock it.

    Both steps are idempotent (see :class:`VenvProvisioner`), so a rerun --
    picking up a newer ``source`` checkout or a changed pin in
    ``requirements`` -- costs nothing when nothing changed and lands the
    update when something did. Neither step is attempted, nor its failure
    swallowed: a :class:`~pegasus.ports.venv_provisioner.VenvProvisionerError`
    from either propagates as is, since there is nothing partial here for a
    caller to clean up -- there is no journal entry for a venv, and the venv
    directory itself is safe to leave half-built for the next rerun to finish.
    """
    provisioner.create(venv)
    provisioner.install(venv, requirements=requirements, source=source)


def path_warning(bin_dir: Path, path_variable: str) -> str | None:
    """``None`` when ``bin_dir`` is already on ``PATH``; a sentence for ``activation`` otherwise.

    ``path_variable`` is asked for explicitly rather than read from the
    process's own environment: the warning is about the *person's* shell, and
    a test must not be able to see the machine running it -- the same
    discipline ``XDG_DATA_HOME`` and the Node lookup in `core/dependencies.py`
    already follow. Comparing parsed entries rather than substrings is what
    keeps ``/home/x/.local/bin`` from matching a `PATH` that only contains
    ``/home/x/.local/binary``.
    """
    entries = {Path(entry) for entry in path_variable.split(":") if entry}
    if bin_dir in entries:
        return None
    # A new session first, and only then editing anything: several systems
    # add this directory at login but only when it already exists, which it
    # did not a moment ago. Someone who edits their shell's configuration
    # instead ends up with the entry twice, and finds that out later.
    return (
        f"open a new shell session so {bin_dir} is picked up, and if the 'pegasus' command is "
        f"still not found, add that directory to your shell's PATH"
    )
