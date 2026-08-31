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

from pegasus.ports.filesystem import FileSystem, FileSystemError
from pegasus.ports.venv_provisioner import VenvProvisioner

VENV_DIRNAME = "venv"
SHIM_NAME = "pegasus"

# What `setup` preserves beside the venv the first time it has a checkout to
# read from, so a later run against the same data directory -- an installed
# Pegasus, with no checkout in reach -- still has something to rebuild from.
SOURCES_DIRNAME = "setup-sources"
PACKAGE_DIRNAME = "package"

#: Skipped while mirroring a checkout beside the venv: version control, test
#: and doc trees, and build caches -- none of it is read by a rebuild, so
#: none of it belongs in a copy kept only so a rebuild has something to read.
_EXCLUDED_FROM_PRESERVATION = frozenset({
    ".git", ".github", ".claude", "tests", "docs", "tools", "venv", ".venv",
    "node_modules", "__pycache__", ".pytest_cache", "dist", "build",
})


def venv_dir(data_dir: Path) -> Path:
    """Where the private venv sits inside Pegasus's own data directory."""
    return data_dir / VENV_DIRNAME


def setup_sources_dir(data_dir: Path) -> Path:
    """Where a `setup` run keeps a copy of the checkout inputs it read.

    A sibling of the venv, inside the same data directory Pegasus already
    manages of its own -- nothing here is any more hidden than the venv
    itself, and a person who wants both gone can delete them the same way.
    """
    return data_dir / SOURCES_DIRNAME


def preserve_inputs(filesystem: FileSystem, sources_dir: Path, *, source: Path, shim: Path) -> None:
    """Copy this run's own checkout-provided inputs beside the venv.

    Called only once `setup` has actually provisioned from its own checkout:
    a run that provisioned from a previously preserved copy has nothing new
    to add here, and copying that copy back onto itself would only spend
    time confirming what was already true.
    """
    _copy_file(filesystem, shim, sources_dir / SHIM_NAME)
    _mirror_tree(filesystem, source, sources_dir / PACKAGE_DIRNAME)


def _copy_file(filesystem: FileSystem, source: Path, target: Path) -> None:
    mode = filesystem.mode_of(source)
    filesystem.write_atomic(
        target, filesystem.read_bytes(source), mode=mode if mode is not None else filesystem.mode_for(executable=False)
    )


def _mirror_tree(filesystem: FileSystem, source: Path, target: Path) -> None:
    for name in filesystem.list_dir(source):
        if name in _EXCLUDED_FROM_PRESERVATION or name.endswith(".egg-info"):
            continue
        child = source / name
        try:
            filesystem.list_dir(child)
        except FileSystemError:
            _copy_file(filesystem, child, target / name)
        else:
            _mirror_tree(filesystem, child, target / name)


def provision(provisioner: VenvProvisioner, *, venv: Path, source: Path) -> None:
    """Build the venv, then stock it.

    Both steps are idempotent (see :class:`VenvProvisioner`), so a rerun --
    picking up a newer ``source`` checkout -- costs nothing when nothing
    changed and lands the update when something did. Neither step is
    attempted, nor its failure swallowed: a
    :class:`~pegasus.ports.venv_provisioner.VenvProvisionerError` from either
    propagates as is, since there is nothing partial here for a caller to
    clean up -- there is no journal entry for a venv, and the venv directory
    itself is safe to leave half-built for the next rerun to finish.
    """
    provisioner.create(venv)
    provisioner.install(venv, source=source)


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
