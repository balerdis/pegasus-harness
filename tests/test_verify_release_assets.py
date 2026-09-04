"""Tests for tools/verify_release_assets.py.

`verify_release_assets` takes an injectable `fetch` callable, so every test here drives it with a
fake that serves bytes from an in-memory table -- no test in this file reaches the network. The
fake mimics the same failure shape a real fetch has (raising on a missing URL) so the module's
error handling is exercised the same way it would be against a real, broken release.
"""
from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from verify_release_assets import (  # noqa: E402
    DOWNLOAD_LATEST,
    DOWNLOAD_TAGGED,
    LATEST_RELEASE_API,
    REPO,
    verify_release_assets,
)

PEGASUS_BYTES = b"pretend zipapp bytes\n"
INSTALL_SH_BYTES = b"#!/bin/sh\necho hi\n"


def _manifest() -> dict:
    return {
        "schema": "pegasus-harness-release/v5",
        "tag": "v5.1.0",
        "assets": [
            {"name": "pegasus", "sha256": hashlib.sha256(PEGASUS_BYTES).hexdigest()},
            {"name": "install.sh", "sha256": hashlib.sha256(INSTALL_SH_BYTES).hexdigest()},
        ],
    }


def _fake_fetch(responses: dict[str, bytes]):
    def fetch(url: str) -> bytes:
        if url not in responses:
            raise RuntimeError(f"404 not found: {url}")
        return responses[url]

    return fetch


def _tagged_urls(tag: str) -> dict[str, str]:
    return {
        name: DOWNLOAD_TAGGED.format(repo=REPO, tag=tag, name=name)
        for name in ("pegasus", "install.sh")
    }


def _latest_urls() -> dict[str, str]:
    return {name: DOWNLOAD_LATEST.format(repo=REPO, name=name) for name in ("pegasus", "install.sh")}


class VerifyReleaseAssetsTest(unittest.TestCase):
    def test_passes_when_both_tagged_and_latest_paths_serve_matching_bytes(self):
        tag = "v5.1.0"
        tagged = _tagged_urls(tag)
        latest = _latest_urls()
        responses = {
            tagged["pegasus"]: PEGASUS_BYTES,
            tagged["install.sh"]: INSTALL_SH_BYTES,
            latest["pegasus"]: PEGASUS_BYTES,
            latest["install.sh"]: INSTALL_SH_BYTES,
            LATEST_RELEASE_API.format(repo=REPO): b'{"tag_name": "v5.1.0"}',
        }

        ok, lines = verify_release_assets(_manifest(), tag, fetch=_fake_fetch(responses))

        self.assertTrue(ok, lines)
        self.assertTrue(any("pegasus" in line and "OK" in line for line in lines))
        self.assertTrue(any("install.sh" in line and "OK" in line for line in lines))

    def test_fails_when_a_tagged_asset_is_missing(self):
        tag = "v5.1.0"
        tagged = _tagged_urls(tag)
        responses = {
            tagged["pegasus"]: PEGASUS_BYTES,
            # install.sh missing entirely
            LATEST_RELEASE_API.format(repo=REPO): b'{"tag_name": "v5.1.0"}',
        }

        ok, lines = verify_release_assets(_manifest(), tag, fetch=_fake_fetch(responses))

        self.assertFalse(ok)
        self.assertTrue(any(line.startswith("FAIL install.sh") for line in lines), lines)

    def test_fails_when_a_tagged_asset_bytes_differ(self):
        tag = "v5.1.0"
        tagged = _tagged_urls(tag)
        responses = {
            tagged["pegasus"]: PEGASUS_BYTES,
            tagged["install.sh"]: b"#!/bin/sh\necho tampered\n",
            LATEST_RELEASE_API.format(repo=REPO): b'{"tag_name": "v5.1.0"}',
        }

        ok, lines = verify_release_assets(_manifest(), tag, fetch=_fake_fetch(responses))

        self.assertFalse(ok)
        failure = next(line for line in lines if line.startswith("FAIL install.sh"))
        self.assertIn("sha256", failure)
        self.assertIn(hashlib.sha256(INSTALL_SH_BYTES).hexdigest(), failure)

    def test_reports_rather_than_fails_when_tag_is_not_the_latest_release(self):
        tag = "v5.1.0"
        tagged = _tagged_urls(tag)
        responses = {
            tagged["pegasus"]: PEGASUS_BYTES,
            tagged["install.sh"]: INSTALL_SH_BYTES,
            LATEST_RELEASE_API.format(repo=REPO): b'{"tag_name": "v5.2.0"}',
        }

        ok, lines = verify_release_assets(_manifest(), tag, fetch=_fake_fetch(responses))

        self.assertTrue(ok, lines)
        self.assertTrue(
            any("not the latest release" in line and "skip" in line.lower() for line in lines),
            lines,
        )

    def test_fails_when_a_latest_path_asset_differs_while_this_tag_is_latest(self):
        tag = "v5.1.0"
        tagged = _tagged_urls(tag)
        latest = _latest_urls()
        responses = {
            tagged["pegasus"]: PEGASUS_BYTES,
            tagged["install.sh"]: INSTALL_SH_BYTES,
            latest["pegasus"]: PEGASUS_BYTES,
            latest["install.sh"]: b"#!/bin/sh\necho stale\n",
            LATEST_RELEASE_API.format(repo=REPO): b'{"tag_name": "v5.1.0"}',
        }

        ok, lines = verify_release_assets(_manifest(), tag, fetch=_fake_fetch(responses))

        self.assertFalse(ok)
        self.assertTrue(
            any(line.startswith("FAIL install.sh") and "releases/latest" in line for line in lines),
            lines,
        )


if __name__ == "__main__":
    unittest.main()
