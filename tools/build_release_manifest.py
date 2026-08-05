#!/usr/bin/env python3
"""Create local release evidence for an existing immutable annotated tag."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def tagged_file(tag: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{tag}:{path}"], cwd=ROOT, capture_output=True, check=True
    ).stdout


def build_archive(tag: str, archive: Path) -> None:
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise ValueError("--archive must not already exist")
    source = subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            f"--prefix=pegasus-harness-{tag}/",
            tag,
        ],
        cwd=ROOT,
        capture_output=True,
        check=True,
    )
    installer_path = f"pegasus-harness-{tag}/install.sh"
    with tarfile.open(fileobj=io.BytesIO(source.stdout), mode="r:") as input_tar:
        with tarfile.open(archive, "w:gz") as output_tar:
            for member in input_tar:
                output_member = copy.copy(member)
                if output_member.name == installer_path:
                    output_member.mode = 0o755
                contents = input_tar.extractfile(member) if member.isfile() else None
                output_tar.addfile(output_member, contents)


def release_installer(tag: str, archive: Path) -> dict[str, str | int]:
    manifest = json.loads(tagged_file(tag, "manifests/baseline-manifest.json"))
    installer = next(
        (asset for asset in manifest["distribution_assets"] if asset["frozen_path"] == "install.sh"),
        None,
    )
    if installer is None:
        raise ValueError("tagged distribution manifest must checksum install.sh")

    if git("ls-tree", tag, "--", "install.sh").split(maxsplit=1)[0] != "100755":
        raise ValueError("tagged install.sh must be tracked with Git mode 100755")
    expected_digest = installer["frozen_sha256"]
    expected_content = tagged_file(tag, "install.sh")
    prefix = f"pegasus-harness-{tag}/install.sh"
    with tarfile.open(archive, "r:gz") as contents:
        member = contents.getmember(prefix)
        if not member.isfile() or member.mode & 0o777 != 0o755:
            raise ValueError("release archive install.sh must be a regular executable file with mode 0755")
        extracted = contents.extractfile(member)
        if extracted is None or extracted.read() != expected_content:
            raise ValueError("release archive install.sh does not match the selected tag")
    actual_digest = hashlib.sha256(expected_content).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError("tagged install.sh does not match its distribution manifest checksum")
    return {"path": "install.sh", "sha256": actual_digest, "mode": "0755"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not SEMVER.fullmatch(args.tag):
        parser.error("--tag must be a semantic version prefixed with v")
    if git("cat-file", "-t", args.tag) != "tag":
        parser.error("--tag must name an annotated tag")
    if args.archive.exists():
        parser.error("--archive must name a new source archive")
    commit = git("rev-list", "-n", "1", args.tag)
    tag_object = git("rev-parse", f"{args.tag}^{{tag}}")
    try:
        build_archive(args.tag, args.archive)
        installer = release_installer(args.tag, args.archive)
    except (subprocess.CalledProcessError, KeyError, ValueError, tarfile.TarError) as error:
        parser.error(str(error))
    payload = {
        "schema": "pegasus-harness-release/v2",
        "tag": args.tag,
        "tag_object": tag_object,
        "commit": commit,
        "clients": ["opencode", "claude-code"],
        "assets": [{"name": args.archive.name, "sha256": digest(args.archive)}],
        "distribution_assets": [installer],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    checksum = args.archive.with_name(args.archive.name + ".sha256")
    checksum.write_text(f"{payload['assets'][0]['sha256']}  {args.archive.name}\n", encoding="utf-8")
    print(f"WROTE checksum: {checksum}")
    print(f"WROTE release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
