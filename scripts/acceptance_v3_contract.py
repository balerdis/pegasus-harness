#!/usr/bin/env python3
"""Pure contract checks for the manual v3 RC acceptance laboratory."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import shutil
import stat
import tarfile
import tempfile
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
HANDOFF_BASE = Path("/var/lib/pegasus-acceptance")


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
            if any(member.mode & ~0o777 for member in members):
                raise ValueError("RC archive contains unsafe permission bits")
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


def rc_release_identity(archive: Path, manifest_path: Path, root: str) -> dict[str, str]:
    """Return the immutable RC identity only after validate_rc_inputs succeeds."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        "tag": manifest["tag"],
        "archive_name": archive.name,
        "archive_sha256": sha256(archive),
        "manifest_sha256": sha256(manifest_path),
        "archive_root": root,
    }


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


def path_from_root(path: Path) -> list[Path]:
    if not path.is_absolute():
        raise ValueError("handoff path must be absolute")
    components = [Path("/")]
    current = Path("/")
    for part in path.parts[1:]:
        current /= part
        components.append(current)
    return components


def validate_root_owned_directory(path: Path, root_uid: int = 0) -> None:
    for component in path_from_root(path):
        metadata = os.lstat(component)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"handoff ancestor is not a real directory: {component}")
        if metadata.st_uid != root_uid or metadata.st_mode & 0o022:
            raise ValueError(f"handoff ancestor is not root-controlled: {component}")


def validate_handoff_payload(payload: Path, target_gid: int, root_uid: int = 0) -> None:
    validate_root_owned_directory(payload.parent, root_uid)
    for current, directories, files in os.walk(payload, topdown=True, followlinks=False):
        current_path = Path(current)
        metadata = os.lstat(current_path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"handoff contains an unsafe directory: {current_path}")
        if (metadata.st_uid != root_uid or metadata.st_gid != target_gid
                or stat.S_IMODE(metadata.st_mode) != 0o750):
            raise ValueError(f"handoff directory has unsafe ownership or mode: {current_path}")
        for name in directories + files:
            item = current_path / name
            item_metadata = os.lstat(item)
            if stat.S_ISLNK(item_metadata.st_mode) or not (stat.S_ISDIR(item_metadata.st_mode) or stat.S_ISREG(item_metadata.st_mode)):
                raise ValueError(f"handoff contains an unsafe entry: {item}")
        for name in files:
            item = current_path / name
            item_metadata = os.lstat(item)
            executable = item == payload / "bin" / "pegasus"
            expected_mode = 0o750 if executable else 0o640
            if (item_metadata.st_uid != root_uid or item_metadata.st_gid != target_gid
                    or stat.S_IMODE(item_metadata.st_mode) != expected_mode):
                raise ValueError(f"handoff file has unsafe ownership or mode: {item}")


def validate_verified_release_tree(release_root: Path) -> None:
    for current, directories, files in os.walk(release_root, topdown=True, followlinks=False):
        current_path = Path(current)
        metadata = os.lstat(current_path)
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise ValueError(f"verified release root contains an unsafe directory: {current_path}")
        for name in directories + files:
            item = current_path / name
            item_metadata = os.lstat(item)
            if stat.S_ISLNK(item_metadata.st_mode) or not (stat.S_ISDIR(item_metadata.st_mode) or stat.S_ISREG(item_metadata.st_mode)):
                raise ValueError(f"verified release root contains an unsafe entry: {item}")


def normalize_handoff_payload(payload: Path, target_gid: int, root_uid: int = 0) -> None:
    entrypoint = payload / "bin" / "pegasus"
    if not entrypoint.is_file() or entrypoint.is_symlink():
        raise ValueError("verified release root lacks a safe Pegasus entrypoint")
    for current, directories, files in os.walk(payload, topdown=False, followlinks=False):
        current_path = Path(current)
        for name in directories + files:
            item = current_path / name
            metadata = os.lstat(item)
            if stat.S_ISLNK(metadata.st_mode) or not (stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)):
                raise ValueError(f"verified release root contains an unsafe entry: {item}")
        os.chown(current_path, root_uid, target_gid)
        os.chmod(current_path, 0o750)
        for name in files:
            item = current_path / name
            os.chown(item, root_uid, target_gid)
            os.chmod(item, 0o750 if item == entrypoint else 0o640)


def prepare_handoff(release_root: Path, target_user: str, handoff_base: Path = HANDOFF_BASE) -> Path:
    if os.geteuid() != 0:
        raise ValueError("root is required to prepare the RC handoff")
    account = pwd.getpwnam(target_user)
    if release_root.is_symlink():
        raise ValueError("verified release root is unsafe")
    release_root = release_root.resolve(strict=True)
    if not release_root.is_dir():
        raise ValueError("verified release root is unsafe")
    validate_verified_release_tree(release_root)

    handoff_base = handoff_base.resolve(strict=False)
    if handoff_base != HANDOFF_BASE:
        raise ValueError("RC handoff base must be /var/lib/pegasus-acceptance")
    for directory in (handoff_base, handoff_base / target_user, handoff_base / target_user / "rc"):
        if directory.exists() or directory.is_symlink():
            validate_root_owned_directory(directory)
            if stat.S_IMODE(os.lstat(directory).st_mode) != 0o711:
                raise ValueError(f"existing handoff path has unsafe mode: {directory}")
        else:
            directory.mkdir(mode=0o711)
            os.chown(directory, 0, 0)
            os.chmod(directory, 0o711)
        validate_root_owned_directory(directory)

    parent = handoff_base / target_user / "rc"
    payload = Path(tempfile.mkdtemp(prefix="payload.", dir=parent))
    try:
        shutil.copytree(release_root, payload, dirs_exist_ok=True, symlinks=False)
        normalize_handoff_payload(payload, account.pw_gid)
        validate_handoff_payload(payload, account.pw_gid)
    except Exception:
        shutil.rmtree(payload, ignore_errors=True)
        raise
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile")
    parser.add_argument("--rc-archive", type=Path)
    parser.add_argument("--rc-checksum", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    parser.add_argument("--extract-dir", type=Path)
    parser.add_argument("--prepare-handoff", action="store_true")
    parser.add_argument("--release-root", type=Path)
    parser.add_argument("--target-user")
    args = parser.parse_args()
    if args.prepare_handoff:
        if not args.release_root or not args.target_user:
            parser.error("--prepare-handoff requires --release-root and --target-user")
        print(prepare_handoff(args.release_root, args.target_user))
        return 0
    if not all((args.profile, args.rc_archive, args.rc_checksum, args.release_manifest, args.extract_dir)):
        parser.error("RC preflight requires profile, archive, checksum, manifest, and extract directory")
    root = validate_rc_inputs(args.profile, args.rc_archive, args.rc_checksum, args.release_manifest)
    release_root = extract_verified_archive(args.rc_archive, args.extract_dir, root)
    print(json.dumps({"profile": args.profile, "release_root": str(release_root),
                      "release_identity": rc_release_identity(args.rc_archive, args.release_manifest, root),
                      **profile_plan(args.profile)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
