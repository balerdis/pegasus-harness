"""Fetching, verifying and placing a `download`-distributed MCP server."""
from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath

from fakes import FakeDownloader, FakeFileSystem

from pegasus.core import dependencies
from pegasus.core import ownership
from pegasus.core.content import Distribution, Mcp

DEPENDENCIES_DIR = Path("/home/probe/.local/share/pegasus-harness/mcp")
AT = "2026-08-14T00:00:00+00:00"


def download_server(**overrides) -> Mcp:
    content = overrides.pop("content", b"the real binary bytes")
    fields = dict(
        name="probe",
        description="d",
        body="convention",
        distribution=Distribution.DOWNLOAD,
        endpoint="https://example.test/releases/probe-linux-x64",
        source=PurePosixPath("mcp/probe.md"),
        version="1.2.3",
        checksum=ownership.digest_of_bytes(content),
    )
    fields.update(overrides)
    return Mcp(**fields), content


class TargetPathTest(unittest.TestCase):
    def test_the_target_directory_is_named_by_id_and_version(self):
        item, _ = download_server()
        self.assertEqual(
            dependencies.target_dir(DEPENDENCIES_DIR, item), DEPENDENCIES_DIR / "probe" / "1.2.3"
        )

    def test_the_binary_lands_under_the_target_directory_named_by_the_endpoint(self):
        item, _ = download_server()
        self.assertEqual(
            dependencies.binary_path(DEPENDENCIES_DIR, item),
            DEPENDENCIES_DIR / "probe" / "1.2.3" / "probe-linux-x64",
        )


class MaterializeTest(unittest.TestCase):
    def setUp(self):
        self.filesystem = FakeFileSystem()

    def materialize(self, item, downloader):
        return dependencies.materialize(self.filesystem, downloader, DEPENDENCIES_DIR, item, at=AT)

    def test_a_verified_download_is_placed_at_the_binary_path(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        self.materialize(item, downloader)
        target = dependencies.binary_path(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.files[target], content)

    def test_the_placed_binary_is_executable(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        self.materialize(item, downloader)
        target = dependencies.binary_path(DEPENDENCIES_DIR, item)
        self.assertEqual(self.filesystem.modes[target], self.filesystem.mode_for(executable=True))

    def test_the_record_identifies_what_was_fetched(self):
        item, content = download_server()
        downloader = FakeDownloader({item.endpoint: content})
        record = self.materialize(item, downloader)
        self.assertEqual(record.id, "dependency:probe")
        self.assertEqual(record.kind, "dependency-tree")
        self.assertEqual(record.target, dependencies.target_dir(DEPENDENCIES_DIR, item))
        self.assertEqual(record.after_digest, item.checksum)

    def test_a_checksum_mismatch_is_refused_naming_expected_and_arrived(self):
        item, _ = download_server()
        wrong = b"not the bytes anyone pinned"
        downloader = FakeDownloader({item.endpoint: wrong})
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, downloader)
        message = str(raised.exception)
        self.assertIn(item.checksum, message)
        self.assertIn(ownership.digest_of_bytes(wrong), message)

    def test_a_checksum_mismatch_leaves_nothing_on_disk(self):
        item, _ = download_server()
        downloader = FakeDownloader({item.endpoint: b"not the bytes anyone pinned"})
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, downloader)
        self.assertEqual(self.filesystem.files, {})
        self.assertEqual(self.filesystem.writes, [])

    def test_a_fetch_failure_names_the_server_and_the_url(self):
        item, _ = download_server()
        downloader = FakeDownloader({})  # nothing registered for item.endpoint
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, downloader)
        self.assertIn(item.name, str(raised.exception))
        self.assertIn(item.endpoint, str(raised.exception))

    def test_a_remote_server_is_refused_rather_than_fetched(self):
        item, content = download_server(distribution=Distribution.REMOTE, version=None, checksum=None)
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, FakeDownloader({item.endpoint: content}))
