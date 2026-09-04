#!/usr/bin/env python3
"""Create the release evidence for v5's distribution shape: one runnable file.

v3 distributed a tarball extracted by `install.sh`; `build_release_manifest.py` still reproduces
that evidence for the tags that shipped it, and stays untouched for exactly that reason -- it reads
its inputs with `git show <tag>:path`, so it can still answer for `v3.1.1` after `install.sh` is
gone from the working tree. v4 shipped a wheel plus a boot shim, verified by an earlier version of
this script through the wheel's own METADATA and the shim's tracked Git mode. Neither exists any
more: Pegasus has zero runtime dependencies and reads its content from inside a zip as readily as
from a directory, so the wheel and the venv it needed are both gone, and with them the second file.

v5 ships two things: `pegasus`, a `zipapp` built by `tools/build_zipapp.py` -- a single executable
file that is the whole command -- and `install.sh`, the script `README.md` and `INSTALL.md`
advertise as a one-liner served from `releases/latest/download/`. What was missing is evidence
tying both files to the commit that produced them, so a person can verify what they downloaded
*before* running it. That evidence is this script's only job. It does not build the artifact --
that is `build_zipapp.py`'s job, and rebuilding it here would make this script a second place that
has to agree about how. It runs the artifact it is given and reads what it reports, the same thing
a person verifying a release would do by hand. `install.sh` has no runtime version to run and
check the way the zipapp does, but it does have exact bytes a commit holds -- `tagged_file` reads
them straight out of the commit with `git show`, and this script certifies that content, refusing
if the commit lacks the file or if the working-tree copy the release procedure actually uploads
does not match it (see `install_sh_evidence`).

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


#: The one-liner `README.md` and `INSTALL.md` advertise. `install.sh` has to exist, non-empty, at
#: the commit this evidence describes -- and be the exact bytes GitHub Releases serves -- or this
#: URL 404s (or serves a stale script) for every user until someone notices by hand.
INSTALL_ONE_LINER = (
    "curl -fsSL https://github.com/balerdis/pegasus-harness/releases/latest/download/install.sh | bash"
)
INSTALL_SH_NAME = "install.sh"


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checksum_line(name: str, sha256: str) -> str:
    """The portable record `sha256sum -c` expects: hash, two spaces, basename."""
    return f"{sha256}  {name}\n"


def tagged_file(commit: str, path: str, root: Path = ROOT) -> bytes:
    return subprocess.run(
        ["git", "show", f"{commit}:{path}"], cwd=root, capture_output=True, check=True
    ).stdout


def resolve_commit(tag: str | None, root: Path = ROOT) -> tuple[str, str | None]:
    """The commit this evidence describes, and the tag it was asked for, if any.

    Without `--tag` the evidence describes `HEAD`, and only when the worktree has nothing
    uncommitted -- otherwise "the commit" would be a claim about bytes nobody can `git show`
    back out of the repository later, which defeats the point of evidence.
    """
    if tag is None:
        if git("status", "--porcelain", root=root):
            raise ValueError("the worktree has uncommitted changes; commit first or pass --tag")
        return git("rev-parse", "HEAD", root=root), None
    if not TAG.fullmatch(tag):
        raise ValueError("--tag must look like vX.Y.Z or vX.Y.Z-rc.N")
    if git("cat-file", "-t", tag, root=root) != "tag":
        raise ValueError("--tag must name an annotated tag")
    return git("rev-list", "-n", "1", tag, root=root), tag


def package_version_at(commit: str, root: Path = ROOT) -> str:
    pyproject = tomllib.loads(tagged_file(commit, "pyproject.toml", root=root).decode("utf-8"))
    return pyproject["project"]["version"]


def install_sh_evidence(commit: str, root: Path = ROOT) -> dict[str, str]:
    """Certify the exact bytes of `install.sh` the resolved commit holds.

    A previous attempt at this evidence tool left `install.sh` out, reasoning it has "no runtime
    version to check" the way the zipapp does. That missed the mechanism already available here:
    `tagged_file` reads content straight out of the commit with `git show`, which is a real
    verification story for a plain script -- content-addressed, and arguably stronger than a
    version string, because it names the exact bytes that have to be uploaded.

    Two things can go wrong, and both are refused rather than silently evidenced:

    * The commit has no `install.sh` (or an empty one). Without it on the same release, the
      one-liner everyone is told to run (see `INSTALL_ONE_LINER`) 404s.
    * The working tree's `install.sh` -- the file `docs/release-distribution.md` actually has a
      person upload -- does not match the bytes this commit holds. With `--tag` the worktree is
      allowed to be dirty, so it is entirely possible to certify one script and upload another.
    """
    try:
        committed_bytes = tagged_file(commit, INSTALL_SH_NAME, root=root)
    except subprocess.CalledProcessError as error:
        raise ValueError(
            f"commit {commit} has no {INSTALL_SH_NAME}; the advertised one-liner "
            f"({INSTALL_ONE_LINER}) 404s without it on the same release"
        ) from error
    if not committed_bytes:
        raise ValueError(
            f"commit {commit} has an empty {INSTALL_SH_NAME}; the advertised one-liner "
            f"({INSTALL_ONE_LINER}) would download nothing usable"
        )
    committed_sha256 = digest_bytes(committed_bytes)

    worktree_path = root / INSTALL_SH_NAME
    if not worktree_path.is_file():
        raise ValueError(
            f"{worktree_path} does not exist in the working tree, but {commit} has one; "
            "upload the working-tree file that matches what this evidence certifies"
        )
    worktree_sha256 = digest(worktree_path)
    if worktree_sha256 != committed_sha256:
        raise ValueError(
            f"working tree {INSTALL_SH_NAME} (sha256 {worktree_sha256}) does not match "
            f"the {INSTALL_SH_NAME} committed at {commit} (sha256 {committed_sha256}); "
            "the release procedure uploads the working-tree file, so it would not be the one "
            "this manifest certifies"
        )
    return {"name": INSTALL_SH_NAME, "sha256": committed_sha256}


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
        install_sh = install_sh_evidence(commit)
    except (subprocess.CalledProcessError, KeyError, ValueError, tomllib.TOMLDecodeError) as error:
        parser.error(str(error))

    payload = {
        "schema": SCHEMA,
        "tag": tag,
        "commit": commit,
        "package_version": expected_version,
        "assets": [artifact, install_sh],
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
