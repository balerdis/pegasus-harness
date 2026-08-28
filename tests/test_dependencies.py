"""Fetching, verifying and placing a `download`- or `npm`-distributed MCP server."""
from __future__ import annotations

import unittest
from pathlib import Path, PurePosixPath

from fakes import FakeDownloader, FakeFileSystem, FakeNpmInstaller

from pegasus.core import dependencies
from pegasus.core import ownership
from pegasus.core.content import Distribution, Mcp

DEPENDENCIES_DIR = Path("/home/probe/.local/share/pegasus-harness/mcp")
AT = "2026-08-14T00:00:00+00:00"
INTEGRITY = "sha512-" + "a" * 86 + "=="


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


def npm_server(**overrides) -> Mcp:
    fields = dict(
        name="probe",
        description="d",
        body="convention",
        distribution=Distribution.NPM,
        endpoint="https://registry.npmjs.org/probe-mcp/-/probe-mcp-1.2.3.tgz",
        source=PurePosixPath("mcp/probe.md"),
        version="1.2.3",
        package="probe-mcp",
        integrity=INTEGRITY,
        entry="cli.js",
    )
    fields.update(overrides)
    return Mcp(**fields)


class NpmScriptPathTest(unittest.TestCase):
    def test_the_script_lands_under_node_modules_by_package_and_entry(self):
        cases = {
            "probe-mcp": "node_modules/probe-mcp/cli.js",
            "@playwright/mcp": "node_modules/@playwright/mcp/cli.js",
        }
        for package, expected in cases.items():
            with self.subTest(package=package):
                item = npm_server(package=package)
                self.assertEqual(
                    dependencies.npm_script_path(DEPENDENCIES_DIR, item),
                    DEPENDENCIES_DIR / "probe" / "1.2.3" / expected,
                )


class MaterializeNpmTest(unittest.TestCase):
    def setUp(self):
        self.filesystem = FakeFileSystem()

    def materialize(self, item, installer, *, node_present=True):
        return dependencies.materialize_npm(
            self.filesystem, installer, DEPENDENCIES_DIR, item, node_present=node_present, at=AT
        )

    def test_a_successful_install_runs_npm_ci_in_the_target_directory(self):
        item = npm_server()
        installer = FakeNpmInstaller()
        self.materialize(item, installer)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        self.assertEqual(installer.calls, [target])

    def test_the_lockfile_pins_the_descriptors_own_resolved_url_and_integrity(self):
        item = npm_server()
        installer = FakeNpmInstaller()
        self.materialize(item, installer)
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        lock = self.filesystem.files[target / "package-lock.json"].decode("utf-8")
        self.assertIn(item.endpoint, lock)
        self.assertIn(item.integrity, lock)
        self.assertIn(item.package, lock)
        self.assertIn(item.version, lock)

    def test_the_record_identifies_what_was_installed(self):
        item = npm_server()
        record = self.materialize(item, FakeNpmInstaller())
        self.assertEqual(record.id, "dependency:probe")
        self.assertEqual(record.kind, "dependency-tree")
        self.assertEqual(record.target, dependencies.target_dir(DEPENDENCIES_DIR, item))
        self.assertEqual(record.after_digest, item.integrity)

    def test_a_missing_node_is_refused_before_anything_is_written(self):
        item = npm_server()
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, FakeNpmInstaller(), node_present=False)
        self.assertIn("node", str(raised.exception).lower())
        self.assertEqual(self.filesystem.files, {})
        self.assertEqual(self.filesystem.writes, [])

    def test_a_failed_install_leaves_nothing_on_disk(self):
        item = npm_server()
        target = dependencies.target_dir(DEPENDENCIES_DIR, item)
        installer = FakeNpmInstaller(failures={target: "registry unreachable"})
        with self.assertRaises(dependencies.MaterializeError) as raised:
            self.materialize(item, installer)
        self.assertIn("registry unreachable", str(raised.exception))
        self.assertEqual(self.filesystem.files, {})
        self.assertFalse(
            any(target in candidate.parents or candidate == target for candidate in self.filesystem.directories)
        )

    def test_a_remote_server_is_refused_rather_than_installed(self):
        item = npm_server(distribution=Distribution.REMOTE, version=None, package=None, integrity=None, entry=None)
        with self.assertRaises(dependencies.MaterializeError):
            self.materialize(item, FakeNpmInstaller())
