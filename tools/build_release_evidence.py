#!/usr/bin/env python3
"""Create the release evidence for v5's distribution shape: one runnable file.

v3 distributed a tarball extracted by `install.sh`; `build_release_manifest.py` still reproduces
that evidence for the tags that shipped it, and stays untouched for exactly that reason -- it reads
its inputs with `git show <tag>:path`, so it can still answer for `v3.1.1` after `install.sh` is
gone from the working tree. v4 shipped a wheel plus a boot shim, verified by an earlier version of
this script through the wheel's own METADATA and the shim's tracked Git mode. Neither exists any
more: Pegasus has zero runtime dependencies and reads its content from inside a zip as readily as
from a directory, so the wheel and the venv it needed are both gone, and with them the second file.

v5 ships one thing: `pegasus`, a `zipapp` built by `tools/build_zipapp.py` -- a single executable
file that is the whole command. What was missing is evidence tying that file to the commit that
produced it, so a person can verify what they downloaded *before* running it. That evidence is this
script's only job. It does not build the artifact -- that is `build_zipapp.py`'s job, and rebuilding
it here would make this script a second place that has to agree about how. It runs the artifact it
is given and reads what it reports, the same thing a person verifying a release would do by hand.

`build_zipapp.py` pins the mtime and mode of everything it stages before zipping, so the SHA-256
this script records is not only a claim about the exact bytes someone downloaded -- it is also what
rebuilding `commit` with `build_zipapp.py`, on the same Python feature release, reproduces. That is
what makes `commit` in the manifest worth anything beyond a label.

    python3 tools/build_release_evidence.py \\
        --artifact dist/pegasus \\
        --output dist/release-manifest.json

Add `--tag v5.0.0` once a release actually gets an annotated tag; the commit and the expected version
are then read from that tag with `git show` instead of from `HEAD`, the same discipline the v3 and v4
tools use to stay honest about which commit they are describing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pegasus-harness-release/v5"
ARTIFACT_NAME = "pegasus"
DOCTOR_TIMEOUT_SECONDS = 30

# Not pinned to a specific version the way v3's `RC_TAG`/`FINAL_TAG` were -- that hardcoding is
# exactly what made the old tool need an edit for every release. Only the shape is fixed: an
# optional `-rc.N` suffix, same as v3 used, so a release candidate can be evidenced the same way
# a final release is.
TAG = re.compile(r"^v(?:\d+)\.(?:\d+)\.(?:\d+)(?:-rc\.[1-9][0-9]*)?$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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


def artifact_evidence(artifact: Path, expected_version: str) -> dict[str, str]:
    """Run the artifact and check what it reports, rather than inspecting its bytes.

    A wheel carries its version in a filename and a METADATA entry that never runs; a `zipapp` has
    neither, so the only place its version lives is in the code it bundles. Running `doctor --json`
    is the same proof a person following `INSTALL.md` gets before they trust the file they
    downloaded, so it doubles as the check that the shebang and the executable bit actually work.
    """
    if artifact.name != ARTIFACT_NAME:
        raise ValueError(f"--artifact must be named {ARTIFACT_NAME!r}, got {artifact.name!r}")
    if not stat.S_IMODE(artifact.stat().st_mode) & stat.S_IXUSR:
        raise ValueError(f"{artifact} is not executable; chmod +x it before evidencing it")
    try:
        result = subprocess.run(
            [str(artifact), "doctor", "--json"],
            capture_output=True, text=True, timeout=DOCTOR_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError(f"{artifact} doctor --json could not run: {error}") from error
    if result.returncode != 0:
        raise ValueError(f"{artifact} doctor --json exited {result.returncode}: {result.stderr.strip()}")
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"{artifact} doctor --json did not print JSON: {error}") from error
    reported = report.get("pegasus_version")
    if reported != expected_version:
        raise ValueError(f"{artifact} reports version {reported!r}, expected {expected_version!r}")
    return {"name": artifact.name, "sha256": digest(artifact)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--artifact", type=Path, required=True, help="the already-built zipapp to evidence")
    parser.add_argument("--tag", help="an annotated release tag; defaults to a clean HEAD")
    parser.add_argument("--output", type=Path, required=True, help="where to write release-manifest.json")
    args = parser.parse_args()

    if not args.artifact.is_file():
        parser.error(f"--artifact does not exist: {args.artifact}")
    if args.output.exists():
        parser.error("--output must not already exist")

    try:
        commit, tag = resolve_commit(args.tag)
        expected_version = package_version_at(commit)
        artifact = artifact_evidence(args.artifact, expected_version)
    except (subprocess.CalledProcessError, KeyError, ValueError, tomllib.TOMLDecodeError) as error:
        parser.error(str(error))

    payload = {
        "schema": SCHEMA,
        "tag": tag,
        "commit": commit,
        "package_version": expected_version,
        "assets": [artifact],
        "install": {"artifact": f"install -m 755 {artifact['name']} <bin_dir>/pegasus"},
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    checksum = args.output.parent / f"{artifact['name']}.sha256"
    checksum.write_text(checksum_line(artifact["name"], artifact["sha256"]), encoding="utf-8")
    print(f"WROTE checksum: {checksum}")
    print(f"WROTE release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
