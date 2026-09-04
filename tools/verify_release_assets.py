#!/usr/bin/env python3
"""Verify a published GitHub release actually serves what its manifest certifies.

`build_release_evidence.py` writes `release-manifest.json`, which names every asset the release
is supposed to ship and the SHA-256 each one must have. That only proves what *should* be true --
the manual step, "publish these files on GitHub Releases", still has to happen correctly, and there
is nothing in the manifest that checks it did. Forget to attach `install.sh` (or attach a stale
copy) and the one-liner in `README.md`/`INSTALL.md` breaks for every new user until someone
notices by hand.

This script is that hand-check, automated: for every asset the manifest names, it downloads the
tagged-release copy (`releases/download/<tag>/<name>`) and compares its SHA-256 to the manifest.
Separately, because `README.md` and `INSTALL.md` advertise the *unversioned* one-liner, it also
checks that `releases/latest/download/<name>` serves the same bytes -- a distinct claim from the
versioned path, since GitHub only updates what "latest" points to when a release is published
non-draft and non-prerelease. Comparing `latest` against a tag that a newer release has since
superseded would fail for a reason that has nothing to do with this tag's own correctness, so this
script resolves whether `--tag` actually names the latest release first, and reports that case
rather than failing it.

    python3 tools/verify_release_assets.py \\
        --manifest dist/release-manifest.json \\
        --tag v5.0.0

Network access is the entire point of this script -- unlike the test suite, which drives it with a
fake `fetch` that never leaves the machine (see `tests/test_verify_release_assets.py`).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path
from typing import Callable

REPO = "balerdis/pegasus-harness"
DOWNLOAD_TAGGED = "https://github.com/{repo}/releases/download/{tag}/{name}"
DOWNLOAD_LATEST = "https://github.com/{repo}/releases/latest/download/{name}"
LATEST_RELEASE_API = "https://api.github.com/repos/{repo}/releases/latest"
FETCH_TIMEOUT_SECONDS = 30

Fetch = Callable[[str], bytes]


def default_fetch(url: str) -> bytes:
    """The real network call. Tests never use this -- they inject a fake instead."""
    request = urllib.request.Request(url, headers={"User-Agent": "pegasus-harness-release-check"})
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_SECONDS) as response:  # noqa: S310
        return response.read()


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def resolve_latest_tag(fetch: Fetch) -> str:
    """The tag GitHub Releases currently serves under `releases/latest/`."""
    url = LATEST_RELEASE_API.format(repo=REPO)
    payload = json.loads(fetch(url).decode("utf-8"))
    return payload["tag_name"]


def verify_release_assets(manifest: dict, tag: str, fetch: Fetch = default_fetch) -> tuple[bool, list[str]]:
    """Check every manifest asset against the published release. Returns (ok, report lines)."""
    ok = True
    lines: list[str] = []

    for asset in manifest.get("assets", []):
        name = asset["name"]
        expected_sha256 = asset["sha256"]
        tagged_url = DOWNLOAD_TAGGED.format(repo=REPO, tag=tag, name=name)
        try:
            data = fetch(tagged_url)
        except Exception as error:  # noqa: BLE001 -- any fetch failure is a hard failure to report
            ok = False
            lines.append(f"FAIL {name}: could not fetch {tagged_url} ({error})")
            continue
        actual_sha256 = sha256_of(data)
        if actual_sha256 != expected_sha256:
            ok = False
            lines.append(
                f"FAIL {name}: {tagged_url} has sha256 {actual_sha256}, "
                f"manifest expects {expected_sha256}"
            )
            continue
        lines.append(f"OK   {name}: {tagged_url} matches the manifest")

    try:
        latest_tag = resolve_latest_tag(fetch)
    except Exception as error:  # noqa: BLE001
        ok = False
        lines.append(f"FAIL could not resolve the latest release: {error}")
        return ok, lines

    if latest_tag != tag:
        lines.append(
            f"SKIP latest-path check: {tag} is not the latest release ({latest_tag} is); "
            "verifying releases/latest/download/ against an older tag would fail for a reason "
            "that is not a defect in this release"
        )
        return ok, lines

    for asset in manifest.get("assets", []):
        name = asset["name"]
        expected_sha256 = asset["sha256"]
        latest_url = DOWNLOAD_LATEST.format(repo=REPO, name=name)
        try:
            data = fetch(latest_url)
        except Exception as error:  # noqa: BLE001
            ok = False
            lines.append(f"FAIL {name}: could not fetch {latest_url} ({error})")
            continue
        actual_sha256 = sha256_of(data)
        if actual_sha256 != expected_sha256:
            ok = False
            lines.append(
                f"FAIL {name}: {latest_url} has sha256 {actual_sha256}, "
                f"manifest expects {expected_sha256}"
            )
            continue
        lines.append(f"OK   {name}: {latest_url} matches the manifest")

    return ok, lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True, help="release-manifest.json to check against")
    parser.add_argument("--tag", required=True, help="the release tag whose assets should be verified")
    args = parser.parse_args()

    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"could not read --manifest: {error}")

    ok, lines = verify_release_assets(manifest, args.tag)
    for line in lines:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
