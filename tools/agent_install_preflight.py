#!/usr/bin/env python3
"""Read-only, JSON-only validation for selected final or RC Pegasus assets."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

FINAL_TAG = "v3.1.1"
PROMOTION_RC_TAG = "v3.1.1-rc.1"
RC_TAG = re.compile(r"v3\.1\.1-rc\.[1-9]\d*\Z")
MCP_NAMES = ("cbm", "engram", "playwright", "context7")
DOCUMENTS = ("README.md", "INSTALL.md", "INSTALL_BY_AGENT.md", "MANUAL.md", "docs/release-distribution.md")
VERSION = re.compile(r"\b\d+(?:\.\d+)+(?:[-+][A-Za-z0-9.-]+)?\b")


class PreflightError(ValueError):
    """A bounded, safe reason why commands must not be distributed."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def regular(path: Path, label: str) -> None:
    if not path.is_file() or path.is_symlink():
        raise PreflightError(f"{label} must be a regular non-symlink file")


def discover_executable(name: str) -> str | None:
    return shutil.which(name)


def probe(path: str, flag: str = "--version") -> str:
    """Run an allowlisted fixed argv and return only a bounded version token."""
    result = subprocess.run([path, flag], text=True, capture_output=True, timeout=5, check=False)
    if result.returncode != 0:
        raise PreflightError("required executable probe failed")
    match = VERSION.search(result.stdout)
    return match.group(0) if match else "unreported"


def validate_assets(archive: Path, checksum: Path, manifest_path: Path) -> dict:
    for path, label in ((archive, "archive"), (checksum, "checksum"), (manifest_path, "release manifest")):
        regular(path, label)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PreflightError("release manifest is invalid JSON") from error
    digest = sha256(archive)
    fields = checksum.read_text(encoding="utf-8").strip().split()
    if len(fields) != 2 or fields[1].lstrip("*") != archive.name or fields[0] != digest:
        raise PreflightError("checksum does not match the supplied archive")
    tag = manifest.get("tag")
    if manifest.get("release_kind") == "final":
        root = f"pegasus-harness-{FINAL_TAG}"
        if (manifest.get("schema") != "pegasus-harness-release/v3" or tag != FINAL_TAG
                or manifest.get("promotion_rc_tag") != PROMOTION_RC_TAG or manifest.get("archive_root") != root
                or manifest.get("assets") != [{"name": archive.name, "sha256": digest}]
                or manifest.get("published_assets") != [archive.name, checksum.name, manifest_path.name]):
            raise PreflightError("final identity does not describe the supplied assets")
        expected_docs = manifest.get("documentation_evidence")
        if not isinstance(expected_docs, list) or {item.get("path") for item in expected_docs if isinstance(item, dict)} != set(DOCUMENTS):
            raise PreflightError("final manifest lacks required documentation evidence")
        expected = list(manifest.get("archive_evidence", [])) + expected_docs
        identity = "final"
    elif isinstance(tag, str) and RC_TAG.fullmatch(tag):
        root = f"pegasus-harness-{tag}"
        expected_archive = f"pegasus-harness-{tag}.tar.gz"
        if (manifest.get("schema") != "pegasus-harness-release/v3" or manifest.get("release_kind") is not None
                or manifest.get("promotion_rc_tag") is not None or manifest.get("archive_root") != root
                or archive.name != expected_archive
                or manifest.get("assets") != [{"name": archive.name, "sha256": digest}]):
            raise PreflightError("RC identity does not describe the supplied assets")
        expected = list(manifest.get("archive_evidence", []))
        identity = "RC"
    else:
        raise PreflightError("release tag is not an accepted immutable final or RC tag")
    if not expected or any(not isinstance(item, dict) for item in expected):
        raise PreflightError(f"{identity} manifest lacks archive evidence")
    try:
        with tarfile.open(archive, "r:gz") as contents:
            members = contents.getmembers()
            if any(member.issym() or member.islnk() or not (member.isfile() or member.isdir()) for member in members):
                raise PreflightError("archive contains unsafe member types")
            if any(member.mode & ~0o777 for member in members):
                raise PreflightError("archive contains unsafe permission bits")
            if not any(member.name.rstrip("/") == root and member.isdir() for member in members):
                raise PreflightError(f"archive has no {identity} root")
            for member in members:
                if member.name.rstrip("/") != root and (not member.name.startswith(root + "/") or ".." in member.name.split("/")):
                    raise PreflightError("archive has an unexpected top-level path")
            for item in expected:
                member = contents.getmember(f"{root}/{item['path']}")
                payload = contents.extractfile(member)
                if not member.isfile() or payload is None or hashlib.sha256(payload.read()).hexdigest() != item.get("sha256"):
                    raise PreflightError(f"archive evidence does not match the {identity} manifest")
    except (KeyError, tarfile.TarError) as error:
        raise PreflightError(f"archive cannot satisfy the {identity} manifest") from error
    return {"tag": tag, "archive": archive.name, "sha256": digest}


def executable(name: str, flag: str = "--version", supplied_path: Path | None = None) -> dict[str, str]:
    path = str(supplied_path) if supplied_path is not None else discover_executable(name)
    if not path:
        raise PreflightError("required executable is unavailable")
    if supplied_path is not None and not supplied_path.is_absolute():
        raise PreflightError("supplied executable path must be absolute")
    return {"path": path, "version": probe(path, flag)}


def browser_executable(browser: Path | None) -> dict[str, str]:
    if browser is None or not browser.is_absolute():
        raise PreflightError("Playwright requires an absolute browser path")
    metadata = os.lstat(browser)
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode) or not metadata.st_mode & 0o111:
        raise PreflightError("Playwright browser path is unsafe")
    return {"path": str(browser), "version": probe(str(browser))}


def collect_preflight(archive: Path, checksum: Path, manifest: Path, mcps: list[str], browser: Path | None = None,
                      opencode: Path | None = None) -> dict:
    if os.geteuid() == 0:
        raise PreflightError("a non-root Linux account is required")
    if len(set(mcps)) != len(mcps):
        raise PreflightError("duplicate MCP request")
    unknown = set(mcps) - set(MCP_NAMES)
    if unknown:
        raise PreflightError("unknown MCP request")
    release = validate_assets(archive, checksum, manifest)
    executables = {"python": executable(Path(sys.executable).name), "opencode": executable("opencode", supplied_path=opencode)}
    statuses: dict[str, dict[str, str]] = {}
    for name in mcps:
        if name == "context7":
            statuses[name] = {"status": "decision-required", "kind": "remote"}
        elif name == "playwright":
            statuses[name] = {"status": "ready", **browser_executable(browser)}
        else:
            command = "codebase-memory-mcp" if name == "cbm" else "engram"
            statuses[name] = {"status": "ready", **executable(command)}
            if name == "cbm":
                probe(statuses[name]["path"], "--help")
    return {"schema": "pegasus-harness-agent-preflight/v3", "status": "ready", "release": release,
            "account": {"non_root": True}, "executables": executables, "mcps": statuses}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--checksum", type=Path)
    parser.add_argument("--release-manifest", type=Path)
    parser.add_argument("--mcp", action="append", default=[])
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--opencode", type=Path)
    try:
        args, unknown = parser.parse_known_args(argv)
        if unknown or not all((args.archive, args.checksum, args.release_manifest)):
            raise PreflightError("archive, checksum, and release manifest are required")
        payload = collect_preflight(args.archive, args.checksum, args.release_manifest, args.mcp, args.browser, args.opencode)
        status = 0
    except PreflightError as error:
        payload, status = {"schema": "pegasus-harness-agent-preflight/v3", "status": "blocked", "reason": str(error)}, 2
    except (OSError, subprocess.SubprocessError, tarfile.TarError):
        payload, status = {"schema": "pegasus-harness-agent-preflight/v3", "status": "blocked", "reason": "required file or executable is unavailable"}, 2
    print(json.dumps(payload, sort_keys=True))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
