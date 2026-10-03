#!/usr/bin/env python3
"""List which pinned MCP dependencies have a newer upstream version (maintainer tool).

Run it before each release. For every descriptor in an MCP content directory it reads the pinned
`version` and asks the upstream registry what is newest:

* `distribution: download` with a GitHub release endpoint -> the GitHub releases API
  (drafts and prereleases are skipped);
* `distribution: npm` -> the npm registry (versions containing `-` are skipped);
* `distribution: remote` -> no version to pin, reported as `unversioned`.

Statuses: `up-to-date`, `update-available` (newer version in the same major, major >= 1),
`major-available` (only a higher major exists), `review-0.x` (any newer version of a 0.x pin: 0.x
minors can break, so a human decides), `unversioned`, `error` (that row only; the others go on).

    python3 tools/check_dependency_updates.py
    python3 tools/check_dependency_updates.py --mcp-dir src/darq/content/mcp --format json --strict

Exit codes: 0 report-only (default, even when updates exist); with `--strict`, 1 if any row is
`update-available`, `major-available`, `review-0.x` or `error`; 2 for an operational failure
(unreadable directory or unparseable descriptor). `GITHUB_TOKEN`, if set, is sent as a bearer token
to the GitHub API (never printed).

This file is shared byte-for-byte between sibling products: it imports nothing from them and holds
no identity logic. It is not shipped to users, and it does not edit anything: a bump is a manual
change to the descriptor.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

DEFAULT_MCP_DIR = Path(__file__).resolve().parent.parent / "src" / "pegasus" / "content" / "mcp"
DEFAULT_TIMEOUT_SECONDS = 30
GITHUB_RELEASES_API = "https://api.github.com/repos/{owner}/{repo}/releases?per_page=100"
NPM_REGISTRY = "https://registry.npmjs.org/{package}"
GITHUB_ENDPOINT = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/")
FIELDS = ("name", "distribution", "endpoint", "version", "package")
ATTENTION = ("update-available", "major-available", "review-0.x", "error")

# fetch(url, timeout_seconds) -> response body
Fetch = Callable[[str, float], bytes]


class DescriptorError(Exception):
    """A descriptor that cannot be read or parsed."""


def default_fetch(url: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> bytes:
    """The real network call. Tests never use this -- they inject a fake instead."""
    headers = {"User-Agent": "release-dependency-check", "Accept": "application/json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlparse(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read()


def parse_descriptor(text: str, source: str) -> dict[str, str]:
    """Read the `key: value` frontmatter fields this tool needs; ignore the rest."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise DescriptorError(f"{source}: missing frontmatter")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, sep, value = line.partition(":")
        if sep and key in FIELDS:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            fields[key] = value
    else:
        raise DescriptorError(f"{source}: unterminated frontmatter")
    for required in ("name", "distribution"):
        if not fields.get(required):
            raise DescriptorError(f"{source}: missing `{required}`")
    return fields


def load_descriptors(mcp_dir: Path) -> list[dict[str, str]]:
    try:
        paths = sorted(mcp_dir.glob("*.md"))
    except OSError as error:
        raise DescriptorError(f"cannot read {mcp_dir}: {error}") from error
    if not mcp_dir.is_dir() or not paths:
        raise DescriptorError(f"no descriptors found in {mcp_dir}")
    descriptors = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise DescriptorError(f"cannot read {path}: {error}") from error
        descriptors.append(parse_descriptor(text, str(path)))
    return descriptors


def version_key(version: str) -> tuple[int, ...] | None:
    """`1.2.3` -> (1, 2, 3); anything that is not plain dotted integers -> None."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", version.strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else None


def github_versions(descriptor: dict[str, str], fetch: Fetch, timeout: float) -> list[str]:
    match = GITHUB_ENDPOINT.match(descriptor.get("endpoint", ""))
    if not match:
        raise ValueError(f"endpoint is not a GitHub release URL: {descriptor.get('endpoint')!r}")
    url = GITHUB_RELEASES_API.format(owner=match.group(1), repo=match.group(2))
    releases = json.loads(fetch(url, timeout).decode("utf-8"))
    return [
        release["tag_name"]
        for release in releases
        if not release.get("draft") and not release.get("prerelease")
    ]


def npm_versions(descriptor: dict[str, str], fetch: Fetch, timeout: float) -> list[str]:
    package = descriptor.get("package")
    if not package:
        raise ValueError("npm descriptor has no `package`")
    url = NPM_REGISTRY.format(package=urllib.parse.quote(package, safe="@"))
    payload = json.loads(fetch(url, timeout).decode("utf-8"))
    return [version for version in payload.get("versions", {}) if "-" not in version]


def classify(current: str, candidates: list[str]) -> tuple[str, str | None, str | None]:
    """Return (status, latest same-major or newest 0.x, latest higher major)."""
    current_key = version_key(current)
    if current_key is None:
        raise ValueError(f"pinned version {current!r} is not a plain dotted version")
    newer = sorted(
        {key for key in map(version_key, candidates) if key is not None and key > current_key}
    )
    if not newer:
        return "up-to-date", None, None
    dotted = lambda key: ".".join(map(str, key))  # noqa: E731
    if current_key[0] == 0:
        return "review-0.x", dotted(newer[-1]), None
    same_major = [key for key in newer if key[0] == current_key[0]]
    higher = [key for key in newer if key[0] > current_key[0]]
    if same_major:
        return "update-available", dotted(same_major[-1]), dotted(higher[-1]) if higher else None
    return "major-available", None, dotted(higher[-1])


def check_descriptor(descriptor: dict[str, str], fetch: Fetch, timeout: float) -> dict:
    row = {
        "name": descriptor["name"],
        "distribution": descriptor["distribution"],
        "current": descriptor.get("version"),
        "status": "unversioned",
        "latest": None,
        "latest_major": None,
        "detail": "",
    }
    distribution = descriptor["distribution"]
    if distribution == "remote":
        return row
    try:
        if distribution == "download":
            candidates = github_versions(descriptor, fetch, timeout)
        elif distribution == "npm":
            candidates = npm_versions(descriptor, fetch, timeout)
        else:
            raise ValueError(f"unknown distribution {distribution!r}")
        if not descriptor.get("version"):
            raise ValueError("descriptor has no `version`")
        row["status"], row["latest"], row["latest_major"] = classify(descriptor["version"], candidates)
    except Exception as error:  # noqa: BLE001 -- one bad row must not stop the others
        row["status"] = "error"
        row["detail"] = str(error) or type(error).__name__
    return row


def check_all(descriptors: list[dict[str, str]], fetch: Fetch, timeout: float) -> list[dict]:
    return [check_descriptor(descriptor, fetch, timeout) for descriptor in descriptors]


def render_text(rows: list[dict]) -> str:
    header = ("NAME", "STATUS", "CURRENT", "LATEST", "NOTE")
    table = [header]
    for row in rows:
        latest = row["latest"] or ""
        if row["latest_major"]:
            latest = f"{latest} (major {row['latest_major']})" if latest else f"major {row['latest_major']}"
        table.append((row["name"], row["status"], row["current"] or "-", latest or "-", row["detail"]))
    widths = [max(len(line[i]) for line in table) for i in range(4)]
    lines = ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(line[:4])) + "  " + line[4] for line in table]
    lines = [line.rstrip() for line in lines]
    majors = [row["name"] for row in rows if row["status"] == "major-available"]
    if majors:
        lines += ["", "Major versions only (review separately): " + ", ".join(majors)]
    zero_x = [row["name"] for row in rows if row["status"] == "review-0.x"]
    npm_flagged = any(row["distribution"] == "npm" and row["status"] in ATTENTION[:3] for row in rows)
    if zero_x or npm_flagged:
        lines += ["", "0.x versions are never bumped blindly: read the changelog first."]
    if npm_flagged:
        lines += [
            "playwright also needs its lockfile (playwright-package-lock.json) and integrity regenerated."
        ]
    if any(row["status"] in ATTENTION[:3] for row in rows):
        lines += ["Every bump needs a new checksum in the descriptor."]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mcp-dir", type=Path, default=DEFAULT_MCP_DIR, help="directory with the MCP descriptors")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--strict", action="store_true", help="exit 1 if anything needs attention")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="seconds per request")
    args = parser.parse_args()

    try:
        descriptors = load_descriptors(args.mcp_dir)
    except DescriptorError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    rows = check_all(descriptors, default_fetch, args.timeout)
    if args.format == "json":
        print(json.dumps({"mcp_dir": str(args.mcp_dir), "dependencies": rows}, indent=2))
    else:
        print(render_text(rows))
    if args.strict and any(row["status"] in ATTENTION for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
