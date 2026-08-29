"""Installing and retiring a `download`-distributed MCP server, end to end.

The real content this release ships names no `download` server -- shipping
one honestly would need a checksum for a URL nobody here can verify without
reaching the network, which this suite refuses to do structurally (see the
socket patch in `fakes.py`). So the form is proven with a descriptor built by
the test itself, patched in for `content.load()`, against the real POSIX
filesystem and a throwaway home -- the same discipline `test_cli.py` already
holds every other command to.
"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import PurePosixPath
from unittest.mock import patch

from fakes import FakeDownloader
from test_dependencies import make_archive

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core import ownership
from pegasus.core.content import Content, Distribution, Mcp
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}
BYTES = b"the real released binary"
CHECKSUM = ownership.digest_of_bytes(BYTES)

PROBE = Mcp(
    name="probe",
    description="A downloaded probe server",
    body="Convention body.",
    distribution=Distribution.DOWNLOAD,
    endpoint="https://example.test/releases/probe-linux-x64",
    source=PurePosixPath("mcp/probe.md"),
    version="1.2.3",
    checksum=CHECKSUM,
)
PROBE_CONTENT = Content(mcp=(PROBE,))


class RealHomeTestCase(_RealHomeTestCase):
    def runtime(self, downloader=None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem,
            home=self.home,
            now=AT,
            out=io.StringIO(),
            variables=NO_BINARY,
            downloader=downloader or FakeDownloader({PROBE.endpoint: BYTES}),
        )

    def environment(self) -> Environment:
        return Environment(home=self.home, data_dir=self.filesystem.data_dir(self.home))

    def layout(self):
        return available().get(CLI).layout(self.environment())

    def present(self) -> None:
        self.layout().config_dir.mkdir(parents=True, exist_ok=True)

    def run_cli(self, *argv, downloader=None) -> tuple[int, dict]:
        context = self.runtime(downloader)
        code = cli.main([*argv, "--json"], runtime=context)
        return code, json.loads(context.out.getvalue())

    def installed_entries(self):
        store = cli.journal_store(self.runtime())
        install = journal_module.install_for(store.load(), CLI)
        return install.entries if install is not None else ()

    def target(self):
        return self.layout().dependencies_dir / "probe" / "1.2.3"

    def binary(self):
        return self.target() / "probe-linux-x64"


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class InstallDownloadTest(RealHomeTestCase):
    def test_naming_the_server_fetches_and_places_it(self, _load):
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.assertEqual(code, cli.OK)
        self.assertEqual(self.binary().read_bytes(), BYTES)

    def test_the_binary_is_placed_executable(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.assertTrue(self.binary().stat().st_mode & 0o111)

    def test_the_journal_records_a_dependency_tree_identified_by_the_checksum(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        entry = next(e for e in self.installed_entries() if e.kind == "dependency-tree")
        self.assertEqual(entry.id, "dependency:probe")
        self.assertEqual(entry.after_digest, CHECKSUM)
        self.assertEqual(entry.target, self.target())

    def test_not_naming_the_server_never_fetches_it(self, _load):
        self.present()
        downloader = FakeDownloader({PROBE.endpoint: BYTES})
        self.run_cli("install", "--cli", CLI, downloader=downloader)
        self.assertEqual(downloader.calls, [])
        self.assertFalse(self.binary().exists())

    def test_a_checksum_mismatch_fails_the_install(self, _load):
        self.present()
        code, report = self.run_cli(
            "install", "--cli", CLI, "--mcp", "probe", downloader=FakeDownloader({PROBE.endpoint: b"wrong"})
        )
        self.assertEqual(code, cli.FAILED)
        self.assertIn(CHECKSUM, report["error"])

    def test_a_checksum_mismatch_leaves_the_directory_as_it_found_it(self, _load):
        self.present()
        self.run_cli(
            "install", "--cli", CLI, "--mcp", "probe", downloader=FakeDownloader({PROBE.endpoint: b"wrong"})
        )
        self.assertFalse(self.target().exists())
        self.assertFalse(self.target().parent.exists())

    def test_a_checksum_mismatch_records_no_dependency_tree(self, _load):
        self.present()
        self.run_cli(
            "install", "--cli", CLI, "--mcp", "probe", downloader=FakeDownloader({PROBE.endpoint: b"wrong"})
        )
        self.assertFalse(any(e.kind == "dependency-tree" for e in self.installed_entries()))

    def test_reinstalling_the_same_version_does_not_refetch(self, _load):
        self.present()
        downloader = FakeDownloader({PROBE.endpoint: BYTES})
        self.run_cli("install", "--cli", CLI, "--mcp", "probe", downloader=downloader)
        self.run_cli("install", "--cli", CLI, "--mcp", "probe", downloader=downloader)
        self.assertEqual(downloader.calls, [PROBE.endpoint])


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class UninstallDownloadTest(RealHomeTestCase):
    def test_uninstalling_removes_the_whole_materialized_tree(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.assertTrue(self.binary().exists())
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.assertFalse(self.target().exists())
        self.assertIn("dependency:probe", report["removed"])

    def test_uninstalling_leaves_no_journal_entry_behind(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.run_cli("uninstall", "--cli", CLI)
        journal = cli.journal_store(self.runtime()).load()
        self.assertIsNone(journal_module.install_for(journal, CLI))

    def test_dropping_the_flag_on_reinstall_retires_it_without_uninstalling(self, _load):
        """`--mcp` still decides what installs: not naming a previously
        installed server on a later run retires exactly that server, the
        rest of the installation stays."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        code, report = self.run_cli("install", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.assertFalse(self.target().exists())
        self.assertIn("dependency:probe", [item["id"] for item in report["retired"]])
        self.assertNotIn("dependency:probe", [e.id for e in self.installed_entries()])
        self.assertTrue(self.layout().config_dir.is_dir())


ARCHIVE_BYTES = make_archive({"probe": b"the real program bytes", "README.md": b"read me"})
ARCHIVE_CHECKSUM = ownership.digest_of_bytes(ARCHIVE_BYTES)

ARCHIVE_PROBE = Mcp(
    name="probe",
    description="An archived probe server",
    body="Convention body.",
    distribution=Distribution.DOWNLOAD,
    endpoint="https://example.test/releases/probe-linux-x64.tar.gz",
    source=PurePosixPath("mcp/probe.md"),
    version="1.2.3",
    checksum=ARCHIVE_CHECKSUM,
    archive_members=("probe", "README.md"),
    archive_executable="probe",
)
ARCHIVE_CONTENT = Content(mcp=(ARCHIVE_PROBE,))


@patch("pegasus.core.content.load", return_value=ARCHIVE_CONTENT)
class InstallArchiveDownloadTest(RealHomeTestCase):
    """The same install path, proven against a real archive on the real
    POSIX filesystem: `tarfile`'s extraction and the real executable bit are
    outside what a fake filesystem can promise, so this is proven here."""

    def runtime(self, downloader=None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=self.filesystem,
            home=self.home,
            now=AT,
            out=io.StringIO(),
            variables=NO_BINARY,
            downloader=downloader or FakeDownloader({ARCHIVE_PROBE.endpoint: ARCHIVE_BYTES}),
        )

    def target(self):
        return self.layout().dependencies_dir / "probe" / "1.2.3"

    def test_every_declared_member_is_extracted(self, _load):
        self.present()
        code, _ = self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.assertEqual(code, cli.OK)
        self.assertEqual((self.target() / "probe").read_bytes(), b"the real program bytes")
        self.assertEqual((self.target() / "README.md").read_bytes(), b"read me")

    def test_only_the_declared_executable_is_executable(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.assertTrue((self.target() / "probe").stat().st_mode & 0o111)
        self.assertFalse((self.target() / "README.md").stat().st_mode & 0o111)

    def test_a_checksum_mismatch_leaves_nothing_behind(self, _load):
        self.present()
        code, report = self.run_cli(
            "install",
            "--cli",
            CLI,
            "--mcp",
            "probe",
            downloader=FakeDownloader({ARCHIVE_PROBE.endpoint: b"not the archive anyone pinned"}),
        )
        self.assertEqual(code, cli.FAILED)
        self.assertFalse(self.target().exists())

    def test_uninstalling_removes_the_whole_extracted_tree(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        code, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertEqual(code, cli.OK)
        self.assertFalse(self.target().exists())
        self.assertIn("dependency:probe", report["removed"])


if __name__ == "__main__":
    unittest.main()
