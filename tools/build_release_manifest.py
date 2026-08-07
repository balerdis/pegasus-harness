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
RC_TAG = re.compile(r"^v3\.1\.(?:0|1)-rc\.[1-9][0-9]*$")
FINAL_TAG = "v3.1.1"
FINAL_PROMOTION_RC_TAG = "v3.1.1-rc.1"
RELEASE_VERSION = "3.1.0"
FINAL_DOCUMENTS = (
    "README.md",
    "INSTALL.md",
    "INSTALL_BY_AGENT.md",
    "MANUAL.md",
    "docs/release-distribution.md",
)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checksum_line(archive: Path) -> str:
    """Return the portable checksum record for a published archive asset."""
    return f"{digest(archive)}  {archive.name}\n"


def tagged_file(tag: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{tag}:{path}"], cwd=ROOT, capture_output=True, check=True
    ).stdout


def curated_cbm(tag: str) -> dict[str, str]:
    provenance = json.loads(tagged_file(tag, "manifests/cbm-linux-x64-provenance.json"))
    contract = json.loads(tagged_file(tag, "manifests/release-contract.json"))
    expected = provenance.get("artifact_sha256")
    build_command = provenance.get("build_command")
    dependency = next((item for item in contract.get("dependencies", []) if item.get("id") == "cbm"), {})
    if not isinstance(expected, str) or len(expected) != 64:
        raise ValueError("tagged CBM provenance must declare an artifact SHA-256")
    if (not isinstance(build_command, str)
            or provenance.get("build_command_sha256") != hashlib.sha256(build_command.encode("utf-8")).hexdigest()):
        raise ValueError("tagged CBM provenance must declare the canonical build command SHA-256")
    source_url = dependency.get("source_url", "")
    if not source_url.startswith("release-bundle:dependencies/"):
        raise ValueError("tagged CBM dependency must expose its bundled archive path to the installer")
    path = source_url.removeprefix("release-bundle:")
    cbm_artifact = ROOT / path
    if (not cbm_artifact.is_file() or cbm_artifact.is_symlink()
            or digest(cbm_artifact) != expected
            or hashlib.sha256(tagged_file(tag, path)).hexdigest() != expected):
        raise ValueError("curated CBM artifact is missing or has an unexpected checksum")
    return {"path": path, "sha256": expected,
            "provenance": "manifests/cbm-linux-x64-provenance.json"}


def build_archive(tag: str, archive: Path) -> dict[str, str]:
    curated = curated_cbm(tag)
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
    cbm_path = f"pegasus-harness-{tag}/{curated['path']}"
    with tarfile.open(fileobj=io.BytesIO(source.stdout), mode="r:") as input_tar:
        with tarfile.open(archive, "w:gz") as output_tar:
            for member in input_tar:
                output_member = copy.copy(member)
                if output_member.name == installer_path:
                    output_member.mode = 0o755
                elif output_member.name == cbm_path:
                    output_member.mode = 0o644
                contents = input_tar.extractfile(member) if member.isfile() else None
                output_tar.addfile(output_member, contents)
    return curated


def release_installer(tag: str, archive: Path) -> dict[str, str | int]:
    manifest = json.loads(tagged_file(tag, "manifests/release-contract.json"))
    if manifest.get("schema") != "pegasus-harness-release-contract/v3" or manifest.get("version") != RELEASE_VERSION:
        raise ValueError(f"tagged release contract must be v{RELEASE_VERSION}")
    installer = {"path": "install.sh", "sha256": hashlib.sha256(tagged_file(tag, "install.sh")).hexdigest()}

    if git("ls-tree", tag, "--", "install.sh").split(maxsplit=1)[0] != "100755":
        raise ValueError("tagged install.sh must be tracked with Git mode 100755")
    expected_digest = installer["sha256"]
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


def archive_evidence(tag: str, archive: Path, curated: dict[str, str]) -> list[dict[str, str]]:
    prefix = f"pegasus-harness-{tag}/"
    evidence = []
    with tarfile.open(archive, "r:gz") as contents:
        for path in ("manifests/release-contract.json", "manifests/artifact-catalog.json", curated["provenance"], curated["path"]):
            member = contents.getmember(prefix + path)
            payload = contents.extractfile(member)
            if not member.isfile() or payload is None or payload.read() != tagged_file(tag, path):
                raise ValueError(f"release archive {path} does not match the selected tag")
            evidence.append({"path": path, "sha256": hashlib.sha256(tagged_file(tag, path)).hexdigest()})
    return evidence


def documentation_evidence(tag: str, archive: Path) -> list[dict[str, str]]:
    """Prove the final archive includes the selected authored installation guides."""
    prefix = f"pegasus-harness-{tag}/"
    evidence = []
    with tarfile.open(archive, "r:gz") as contents:
        for path in FINAL_DOCUMENTS:
            member = contents.getmember(prefix + path)
            payload = contents.extractfile(member)
            expected = tagged_file(tag, path)
            if not member.isfile() or payload is None or payload.read() != expected:
                raise ValueError(f"release archive documentation does not match the selected tag: {path}")
            evidence.append({"path": path, "sha256": hashlib.sha256(expected).hexdigest()})
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--promotion-rc-tag")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    is_final = args.tag == FINAL_TAG
    if not is_final and not RC_TAG.fullmatch(args.tag):
        parser.error("--tag must be v3.1.1 or an RC tag matching v3.1.0-rc.N or v3.1.1-rc.N")
    if is_final and args.promotion_rc_tag != FINAL_PROMOTION_RC_TAG:
        parser.error("v3.1.1 requires --promotion-rc-tag v3.1.1-rc.1")
    if not is_final and args.promotion_rc_tag:
        parser.error("--promotion-rc-tag is valid only for v3.1.1")
    if git("cat-file", "-t", args.tag) != "tag":
        parser.error("--tag must name an annotated tag")
    if is_final and git("cat-file", "-t", args.promotion_rc_tag) != "tag":
        parser.error("--promotion-rc-tag must name an annotated tag")
    if args.archive.exists():
        parser.error("--archive must name a new source archive")
    commit = git("rev-list", "-n", "1", args.tag)
    tag_object = git("rev-parse", f"{args.tag}^{{tag}}")
    if is_final and commit != git("rev-list", "-n", "1", args.promotion_rc_tag):
        parser.error("v3.1.1 and its accepted v3.1.1-rc.1 promotion input must name the same commit")
    try:
        curated = build_archive(args.tag, args.archive)
        installer = release_installer(args.tag, args.archive)
        evidence = archive_evidence(args.tag, args.archive, curated)
        docs = documentation_evidence(args.tag, args.archive) if is_final else []
    except (subprocess.CalledProcessError, KeyError, ValueError, tarfile.TarError) as error:
        parser.error(str(error))
    checksum = args.archive.with_name(args.archive.name + ".sha256")
    checksum.write_text(checksum_line(args.archive), encoding="utf-8")
    payload = {
        "schema": "pegasus-harness-release/v3",
        "tag": args.tag,
        "tag_object": tag_object,
        "commit": commit,
        "clients": ["opencode", "claude-code"],
        "assets": [{"name": args.archive.name, "sha256": digest(args.archive)}],
        "distribution_assets": [installer],
        "archive_root": f"pegasus-harness-{args.tag}",
        "archive_evidence": evidence,
        "curated_dependencies": [{"id": "cbm", **curated}],
    }
    if is_final:
        payload.update({
            "release_kind": "final",
            "promotion_rc_tag": args.promotion_rc_tag,
            "documentation_evidence": docs,
            "published_assets": [args.archive.name, checksum.name, args.output.name],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE checksum: {checksum}")
    print(f"WROTE release manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
