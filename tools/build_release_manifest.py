#!/usr/bin/env python3
"""Create local release evidence for an existing immutable annotated tag."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    if not args.archive.is_file():
        parser.error("--archive must be an existing source archive")
    commit = git("rev-list", "-n", "1", args.tag)
    payload = {
        "schema": "pegasus-harness-release/v1",
        "tag": args.tag,
        "commit": commit,
        "clients": ["opencode", "claude-code"],
        "assets": [{"name": args.archive.name, "sha256": digest(args.archive)}],
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
