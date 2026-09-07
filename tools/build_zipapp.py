#!/usr/bin/env python3
"""Build the single-file `pegasus` artifact: a `zipapp` with a shebang, made executable.

Pegasus has zero runtime dependencies and reads its content and assets from inside a zip just as
well as from a directory (see `pegasus.core.content`), so nothing stands between a checkout and a
single file that *is* the command: no venv, no shim, no PATH-shaped install step at all. Download it,
verify its checksum, `chmod +x` (or `install -m 755`), and run it.

The build is reproducible: every staged file's mtime and mode are pinned before zipping (see
`_normalize`), so rebuilding from the same tagged source, on the same Python feature release,
reproduces the published SHA-256 -- the checksum proves not just "these are the bytes you
downloaded" but "these are the bytes this source actually produces".

    python3 tools/build_zipapp.py --out dist/pegasus

`zipapp` looks for `__main__.py` at the archive root, not inside the package it runs -- `stage()`
writes one there, copied verbatim from the package's own `src/pegasus/__main__.py` so the two can
never drift apart into two different entry points.

    python3 -m zipapp <staged dir> -o pegasus -p "/usr/bin/env python3"
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil
import sys
import tempfile
import types
import uuid
import zipapp
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_SOURCE = ROOT / "src" / "pegasus"

#: A marker file present only at the package root, never at the extraction root above it.
#: `stage()` also copies `__main__.py` to the extraction root, so checking for that file alone
#: cannot tell `--source <tree>` (the extraction root) apart from `--source <tree>/pegasus` (the
#: package itself) -- the former builds a nested `pegasus/pegasus/` archive that fails at runtime
#: with `ModuleNotFoundError: No module named 'pegasus.cli'`. `core/content.py` exists only inside
#: the package, so requiring it too closes that gap.
_PACKAGE_MARKER = Path("core") / "content.py"

INTERPRETER = "/usr/bin/env python3"

#: Never staged into the archive: build caches only Python itself writes back, never read by a
#: fresh interpreter running the zip.
_PRUNED = {"__pycache__"}

#: Reproducible-builds convention (https://reproducible-builds.org/specs/source-date-epoch/):
#: `zipapp.create_archive` bakes each staged file's mtime into its `ZipInfo`, so a build has to
#: pin every mtime to the same value regardless of when the source happens to sit on disk, or two
#: checkouts of byte-identical content produce two different SHA-256 hashes of the artifact. Read
#: from the environment when set, so a release pipeline can pin it to the commit's own timestamp;
#: otherwise this fixed constant (2024-01-01T00:00:00Z) -- never "now".
DEFAULT_SOURCE_DATE_EPOCH = 1704067200

#: Mode bits normalized onto every staged file and directory before zipping, so the archive's
#: recorded permissions do not depend on the source checkout's own umask or filesystem history.
_FILE_MODE = 0o644
_DIR_MODE = 0o755


def _ignore(_directory: str, names: list[str]) -> set[str]:
    return {name for name in names if name in _PRUNED or name.endswith((".pyc", ".pyo"))}


def _source_date_epoch() -> int:
    value = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    return int(value) if value else DEFAULT_SOURCE_DATE_EPOCH


def _normalize(destination: Path, epoch: int) -> None:
    """Pin every staged entry's mtime and mode, in sorted order, so the walk itself is deterministic.

    `zipapp.create_archive` already zips `sorted(source.rglob("*"))`, so file ordering in the
    archive is not the source of non-determinism -- what it bakes in verbatim from each entry's
    `os.stat` is the mtime and the permission bits, and those come straight from the checkout.
    """
    for path in sorted(destination.rglob("*")):
        os.utime(path, (epoch, epoch))
        path.chmod(_DIR_MODE if path.is_dir() else _FILE_MODE)
    os.utime(destination, (epoch, epoch))


def stage(source: Path, destination: Path, identity: Path) -> None:
    """Copy the package into ``destination/pegasus``, plus a root `__main__.py` for `zipapp` to find.

    `identity`'s bytes are staged as the package's own `identity.json`, overriding whatever
    `source` already carried -- so a distribution's identity always wins over the pinned engine's,
    and forgetting to pass one is an `argparse` error in `main()`, never a silent inheritance.
    """
    package_dir = destination / "pegasus"
    shutil.copytree(source, package_dir, ignore=_ignore)
    shutil.copy2(package_dir / "__main__.py", destination / "__main__.py")
    shutil.copy2(identity, package_dir / "identity.json")


def _load_identity_module(source: Path) -> types.ModuleType:
    """Load `<source>/core/identity.py` as a standalone module, by file path.

    Not `sys.path.insert(0, source.parent); import pegasus.core.identity`: that only works when
    `source` is itself named `pegasus`, and it would silently resolve to whatever `pegasus` package
    is already imported (the real engine under test, when this runs from inside the test suite)
    rather than the one actually being built. Loading the file directly validates against the
    exact source tree `--source` names, regardless of its directory name.

    `exec_module` runs whatever code is actually in `<source>/core/identity.py`, arbitrary as far
    as this function is concerned -- acceptable because whoever runs a build already controls the
    `--source` tree being built.

    This *does* touch `sys.modules`, briefly and on purpose: `identity.py` uses
    `from __future__ import annotations`, so its `@dataclass(frozen=True)` fields are deferred
    string annotations, and `dataclasses._is_type()` resolves them by looking `cls.__module__` up
    in `sys.modules`. Without registering the module there first, `exec_module` raises
    `AttributeError: 'NoneType' object has no attribute '__dict__'` before this function's own
    validation ever runs. The `finally` removes the registration again as soon as `exec_module`
    returns (or raises), so nothing of this transient load lingers in `sys.modules` afterward.
    """
    identity_module_path = source / "core" / "identity.py"
    if not identity_module_path.is_file():
        raise ValueError(
            f"{source} has no core/identity.py; it cannot validate the identity it is asked to stage"
        )
    # Unique per call, not a fixed name: two builds in the same process on different threads must
    # not delete each other's still-running `exec_module` registration out from under it.
    module_name = f"_build_zipapp_identity_validator_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, identity_module_path)
    if spec is None or spec.loader is None:
        raise ValueError(f"could not load {identity_module_path} to validate identity")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[module_name]
    return module


def validate_identity(source: Path, identity: Path) -> None:
    """Parse `identity` with the exact validation rules the built artifact itself will run.

    Reusing `core/identity.py`'s `parse()` -- rather than re-declaring the wordmark charset and
    length limit here -- is the only way the build-time check and the runtime check can never
    drift apart into two different rules for the same name.
    """
    if not identity.is_file():
        raise ValueError(f"--identity does not exist: {identity}")
    identity_module = _load_identity_module(source)
    try:
        identity_module.parse(identity.read_bytes())
    except identity_module.IdentityError as error:
        raise ValueError(str(error)) from error


def validate_source_layout(source: Path) -> None:
    """Refuse a `--source` that is the extraction root instead of the package itself."""
    if not (source / "__main__.py").is_file():
        raise ValueError(f"{source} has no __main__.py; it is not the pegasus package")
    if not (source / _PACKAGE_MARKER).is_file():
        raise ValueError(
            f"{source} has no {_PACKAGE_MARKER}; pass the package directory itself "
            f"(e.g. .../pegasus), not the extraction root above it -- passing the wrong "
            f"directory builds a nested pegasus/pegasus/ archive that fails at runtime with "
            f"ModuleNotFoundError: No module named 'pegasus.cli'"
        )


def build(source: Path, output: Path, identity: Path) -> None:
    """Stage `source`, zip it with a shebang, `chmod +x` it, and write its `.sha256` beside it.

    Deterministic by construction: `_normalize` pins every staged file's mtime and mode before
    `zipapp.create_archive` reads them, and `compressed=False` keeps the compression setting fixed
    (`ZIP_STORED`) rather than leaving it to whatever the caller passes. Two builds from
    byte-identical source content, on the same CPython feature release and `zipfile`/`zipapp`
    implementation, produce byte-identical output. The residual sources of variation this cannot
    remove are the ones outside this script's control: a different Python version whose `zipapp`
    or `zipfile` module changed how it writes an entry, or extra members added by a modified
    `zipapp` implementation.
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    epoch = _source_date_epoch()
    with tempfile.TemporaryDirectory() as stage_dir:
        stage_path = Path(stage_dir)
        stage(source, stage_path, identity)
        _normalize(stage_path, epoch)
        zipapp.create_archive(stage_dir, target=output, interpreter=INTERPRETER, compressed=False)
    output.chmod(0o755)
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(f"{checksum}  {output.name}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=PACKAGE_SOURCE, help="the pegasus package to bundle")
    parser.add_argument("--out", type=Path, required=True, help="where to write the artifact (e.g. dist/pegasus)")
    parser.add_argument(
        "--identity", type=Path, required=True,
        help=(
            "identity.json to stage into the artifact -- required even for Pegasus's own release "
            "build, so a distribution can never forget to supply its own identity and silently "
            "ship as Pegasus"
        ),
    )
    arguments = parser.parse_args()

    try:
        validate_source_layout(arguments.source)
        validate_identity(arguments.source, arguments.identity)
    except ValueError as error:
        parser.error(str(error))
    if arguments.out.exists():
        parser.error(f"--out must not already exist: {arguments.out}")

    build(arguments.source, arguments.out, arguments.identity)
    print(f"WROTE artifact: {arguments.out}")
    print(f"WROTE checksum: {arguments.out.with_name(arguments.out.name + '.sha256')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
