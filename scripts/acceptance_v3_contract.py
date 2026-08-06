#!/usr/bin/env python3
"""Pure contract checks for the manual v3 RC acceptance laboratory."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path


RC_TAG = re.compile(r"^v3\.1\.0-rc\.[1-9][0-9]*$")
PROFILE_PLANS = {
    "cbm": {"user": "pegasus-harness", "confirm": ("cbm",), "decline": ("engram", "playwright", "context7")},
    "engram": {"user": "pegasus-harness-engram", "confirm": ("engram",), "decline": ("cbm", "playwright", "context7")},
    "playwright": {"user": "pegasus-harness-playwright", "confirm": ("playwright",), "decline": ("cbm", "engram", "context7")},
    "context7": {"user": "pegasus-harness-context7", "confirm": ("context7",), "decline": ("cbm", "engram", "playwright")},
    "final": {"user": "pegasus-harness-final", "confirm": ("cbm", "engram", "playwright", "context7"), "decline": ()},
}
MCP_CONFIG_KEYS = {"cbm": "codebase-memory-mcp", "engram": "engram", "playwright": "playwright", "context7": "context7"}


def profile_plan(profile: str) -> dict[str, object]:
    try:
        return dict(PROFILE_PLANS[profile])
    except KeyError as error:
        raise ValueError(f"unknown acceptance profile: {profile}") from error


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular_file(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular non-symlink file")


def checksum_digest(checksum: Path, archive: Path) -> str:
    regular_file(checksum, "RC checksum")
    fields = checksum.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or fields[1].lstrip("*") != archive.name or not re.fullmatch(r"[0-9a-f]{64}", fields[0]):
        raise ValueError("RC checksum must name exactly the supplied archive")
    return fields[0]


def archive_member_in_root(name: str, root: str) -> bool:
    if name in {root, root + "/"}:
        return True
    return name.startswith(root + "/") and all(part not in {"", ".", ".."} for part in name.split("/"))


def validate_rc_inputs(profile: str, archive: Path, checksum: Path, manifest_path: Path) -> str:
    profile_plan(profile)
    regular_file(archive, "RC archive")
    regular_file(manifest_path, "RC release manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("RC release manifest is invalid JSON") from error
    tag = manifest.get("tag")
    if not isinstance(tag, str) or not RC_TAG.fullmatch(tag):
        raise ValueError("release manifest must declare v3.1.0-rc.N")
    expected_name = f"pegasus-harness-{tag}.tar.gz"
    root = f"pegasus-harness-{tag}"
    archive_digest = sha256(archive)
    if checksum_digest(checksum, archive) != archive_digest:
        raise ValueError("RC checksum does not match the archive")
    if (archive.name != expected_name or manifest.get("schema") != "pegasus-harness-release/v3"
            or manifest.get("archive_root") != root
            or manifest.get("assets") != [{"name": archive.name, "sha256": archive_digest}]):
        raise ValueError("RC archive and release manifest do not describe the same immutable artifact")
    curated = manifest.get("curated_dependencies")
    evidence = manifest.get("archive_evidence")
    if not isinstance(curated, list) or len(curated) != 1 or curated[0].get("id") != "cbm" or not isinstance(evidence, list):
        raise ValueError("release manifest lacks curated CBM or archive evidence")
    required = {"manifests/release-contract.json", "manifests/artifact-catalog.json", "manifests/cbm-linux-x64-provenance.json", curated[0].get("path")}
    if {item.get("path") for item in evidence if isinstance(item, dict)} != required:
        raise ValueError("release manifest evidence is incomplete")
    try:
        with tarfile.open(archive, "r:gz") as contents:
            members = contents.getmembers()
            if any(member.issym() or member.islnk() or not (member.isfile() or member.isdir()) for member in members):
                raise ValueError("RC archive contains unsafe member types")
            if (not any(member.name in {root, root + "/"} and member.isdir() for member in members)
                    or any(not archive_member_in_root(member.name, root) for member in members)):
                raise ValueError("RC archive has an unexpected top-level path")
            for item in evidence:
                member = contents.getmember(f"{root}/{item['path']}")
                payload = contents.extractfile(member)
                if not member.isfile() or payload is None or sha256_bytes(payload.read()) != item.get("sha256"):
                    raise ValueError(f"archive evidence mismatch: {item['path']}")
    except (KeyError, tarfile.TarError) as error:
        raise ValueError("RC archive cannot satisfy its release manifest") from error
    return root


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def extract_verified_archive(archive: Path, destination: Path, root: str) -> Path:
    if destination.exists():
        raise ValueError("acceptance staging directory must not already exist")
    destination.mkdir(mode=0o700)
    try:
        with tarfile.open(archive, "r:gz") as contents:
            contents.extractall(destination, members=contents.getmembers(), filter="data")
    except Exception:
        destination.rmdir()
        raise
    release_root = destination / root
    if not (release_root / "bin" / "pegasus").is_file() or not (release_root / "install.sh").is_file():
        raise ValueError("validated RC archive lacks Pegasus entrypoints")
    return release_root


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--rc-archive", type=Path, required=True)
    parser.add_argument("--rc-checksum", type=Path, required=True)
    parser.add_argument("--release-manifest", type=Path, required=True)
    parser.add_argument("--extract-dir", type=Path, required=True)
    args = parser.parse_args()
    root = validate_rc_inputs(args.profile, args.rc_archive, args.rc_checksum, args.release_manifest)
    release_root = extract_verified_archive(args.rc_archive, args.extract_dir, root)
    print(json.dumps({"profile": args.profile, "release_root": str(release_root), **profile_plan(args.profile)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
