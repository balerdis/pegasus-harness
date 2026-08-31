#!/usr/bin/env python3
"""Create the release evidence for v4's distribution shape: a wheel plus its boot shim.

v3 distributed a tarball extracted by `install.sh`; `build_release_manifest.py` still reproduces
that evidence for the tags that shipped it, and stays untouched for exactly that reason -- it reads
its inputs with `git show <tag>:path`, so it can still answer for `v3.1.1` after `install.sh` is
gone from the working tree. It does not extend to v4: there is no tarball, no installer script, and
no bundled dependency to curate, so bolting a wheel-shaped branch onto its tag pattern would make one
tool understand two unrelated distribution shapes instead of two tools that each understand one.

v4 ships one thing a person installs by hand: a wheel (`pegasus-harness`, built by the standard
`pip wheel . --no-deps` a maintainer already has to run) -- Pegasus has zero runtime dependencies, so
there is no lockfile to curate alongside it any more. What was missing is the second thing: evidence
that ties the wheel to the commit that produced it, so a person can verify what they downloaded
*before* running `pip install` against it. That evidence is this script's only job. It does not build
the wheel -- the wheel is a build artifact, and rebuilding it here would make this script a second
place that has to agree with `pyproject.toml` about how to build it. It only reads what already exists.

    python3 tools/build_release_evidence.py \\
        --wheel dist/pegasus_harness-4.0.0-py3-none-any.whl \\
        --output dist/release-manifest.json

Add `--tag v4.0.0` once a release actually gets an annotated tag; the commit and file contents are
then read from that tag with `git show` instead of from `HEAD`, the same discipline the v3 tool uses
to stay honest about which commit it is describing.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import tomllib
import zipfile
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pegasus-harness-release/v4"

# Not pinned to a specific version the way v3's `RC_TAG`/`FINAL_TAG` were -- that hardcoding is
# exactly what made the old tool need an edit for every release. Only the shape is fixed: an
# optional `-rc.N` suffix, same as v3 used, so a release candidate can be evidenced the same way
# a final release is.
TAG = re.compile(r"^v(?:\d+)\.(?:\d+)\.(?:\d+)(?:-rc\.[1-9][0-9]*)?$")
WHEEL_NAME = re.compile(r"^pegasus_harness-(?P<version>[^-]+)-py3-none-any\.whl$")

SHIM_PATH = "bin/pegasus"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_line(name: str, sha256: str) -> str:
    """The portable record `sha256sum -c` expects: hash, two spaces, basename."""
    return f"{sha256}  {name}\n"


def tagged_file(commit: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, check=True
    ).stdout


def resolve_commit(tag: str | None) -> tuple[str, str | None]:
    """The commit this evidence describes, and the tag it was asked for, if any.

    Without `--tag` the evidence describes `HEAD`, and only when the worktree has nothing
    uncommitted -- otherwise "the commit" would be a claim about bytes nobody can `git show`
    back out of the repository later, which defeats the point of evidence.
    """
    if tag is None:
        if git("status", "--porcelain"):
            raise ValueError("the worktree has uncommitted changes; commit first or pass --tag")
        return git("rev-parse", "HEAD"), None
    if not TAG.fullmatch(tag):
        raise ValueError("--tag must look like vX.Y.Z or vX.Y.Z-rc.N")
    if git("cat-file", "-t", tag) != "tag":
        raise ValueError("--tag must name an annotated tag")
    return git("rev-list", "-n", "1", tag), tag


def package_version_at(commit: str) -> str:
    pyproject = tomllib.loads(tagged_file(commit, "pyproject.toml").decode("utf-8"))
    return pyproject["project"]["version"]


def wheel_evidence(wheel: Path, commit: str) -> dict[str, str]:
    match = WHEEL_NAME.fullmatch(wheel.name)
    if not match:
        raise ValueError(f"--wheel must be named pegasus_harness-<version>-py3-none-any.whl, got {wheel.name}")
    expected_version = package_version_at(commit)
    if match["version"] != expected_version:
        raise ValueError(
            f"wheel filename declares version {match['version']!r}, "
            f"but pyproject.toml at {commit} declares {expected_version!r}"
        )
    with zipfile.ZipFile(wheel) as archive:
        metadata_name = f"pegasus_harness-{expected_version}.dist-info/METADATA"
        try:
            metadata = archive.read(metadata_name).decode("utf-8")
        except KeyError as error:
            raise ValueError(f"{wheel} has no {metadata_name}; it is not a wheel this tool built") from error
    declared = next((line.split(":", 1)[1].strip() for line in metadata.splitlines() if line.startswith("Version:")), None)
    if declared != expected_version:
        raise ValueError(f"wheel METADATA declares version {declared!r}, expected {expected_version!r}")
    return {"name": wheel.name, "sha256": digest(wheel)}


def shim_evidence(commit: str) -> dict[str, str]:
    if git("ls-tree", commit, "--", SHIM_PATH).split(maxsplit=1)[0] != "100755":
        raise ValueError(f"{SHIM_PATH} at {commit} must be tracked with Git mode 100755")
    tracked = tagged_file(commit, SHIM_PATH)
    return {"name": Path(SHIM_PATH).name, "sha256": digest_bytes(tracked)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wheel", type=Path, required=True, help="the already-built wheel to evidence")
    parser.add_argument("--tag", help="an annotated release tag; defaults to a clean HEAD")
    parser.add_argument("--output", type=Path, required=True, help="where to write release-manifest.json")
    args = parser.parse_args()

    if not args.wheel.is_file():
        parser.error(f"--wheel does not exist: {args.wheel}")
    if args.output.exists():
        parser.error("--output must not already exist")

    try:
        commit, tag = resolve_commit(args.tag)
        wheel = wheel_evidence(args.wheel, commit)
        shim = shim_evidence(commit)
    except (subprocess.CalledProcessError, KeyError, ValueError, tomllib.TOMLDecodeError, zipfile.BadZipFile) as error:
        parser.error(str(error))

    payload = {
        "schema": SCHEMA,
        "tag": tag,
        "commit": commit,
        "package_version": package_version_at(commit),
        "assets": [wheel, shim],
        "install": {
            "package": f"pip install --no-deps {wheel['name']}",
            "shim": f"install -m 755 {shim['name']} <bin_dir>/pegasus",
        },
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    for asset in (wheel, shim):
        checksum = args.output.parent / f"{asset['name']}.sha256"
        checksum.write_text(checksum_line(asset["name"], asset["sha256"]), encoding="utf-8")
        print(f"WROTE checksum: {checksum}")

    print(f"WROTE release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
