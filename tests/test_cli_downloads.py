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
from dataclasses import replace
from pathlib import PurePosixPath
from unittest.mock import patch

from fakes import FakeDownloader
from test_dependencies import make_archive

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import journal as journal_module
from pegasus.core import ownership
from pegasus.core.content import Agent, AgentMode, Content, Distribution, Mcp, SESSION_STARTS_IN
from pegasus.core.types import Environment
from real_home import RealHomeTestCase as _RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
# Pinned to OpenCode, not "whichever adapter is registered first": this
# suite exercises capabilities (mcp, per_agent_model, subagents declared
# inside the settings file, ...) that only OpenCode declares today. Since
# Claude Code registered, "available().ids()[0]" resolves alphabetically
# to "claudecode" instead, which cannot support what this file tests.
CLI = "opencode"
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
#: `render` derives `orchestrator_name` unconditionally now, so a `Content`
#: used with the real adapter through `cli.install` needs a default agent too.
_ORCHESTRATOR = Agent(
    name=SESSION_STARTS_IN,
    description="A probe orchestrator",
    body="Body.\n",
    mode=AgentMode.PRIMARY,
    source=PurePosixPath("agents/orchestrator.md"),
)
PROBE_CONTENT = Content(mcp=(PROBE,), agents=(_ORCHESTRATOR,))


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
class DryRunDownloadTest(RealHomeTestCase):
    """`update --dry-run` must predict `update`'s own real run.

    A `download` server already materialized at the version and checksum
    this release still asks for costs no fetch on a real `update` -- it is
    reported as `unchanged`, alongside every catalog artifact that needed no
    write (see `install`'s `"unchanged"` key). `plan` never sees a
    `dependency-tree` at all (it is materialized outside the catalog
    pipeline entirely), so a dry run that only reads `plan.unchanged` counts
    every artifact except this one, and its total falls one short of what
    the very next real run reports for the identical, untouched install.
    """

    def test_a_kept_dependency_is_previewed_as_unchanged(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        _, dry_report = self.run_cli("update", "--cli", CLI, "--dry-run")
        self.assertIn(
            "dependency:probe", [item["id"] for item in dry_report["unchanged"]]
        )

    def test_the_dry_run_total_matches_the_next_real_run(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        _, dry_report = self.run_cli("update", "--cli", CLI, "--dry-run")
        _, real_report = self.run_cli("update", "--cli", CLI)
        self.assertEqual(len(dry_report["created"]), len(real_report["created"]))
        self.assertEqual(len(dry_report["updated"]), len(real_report["updated"]))
        self.assertEqual(len(dry_report["unchanged"]), len(real_report["unchanged"]))


PROBE_V2_BYTES = b"the newly released binary"
PROBE_V2_CHECKSUM = ownership.digest_of_bytes(PROBE_V2_BYTES)
PROBE_V2 = replace(
    PROBE,
    version="1.2.4",
    checksum=PROBE_V2_CHECKSUM,
    endpoint="https://example.test/releases/probe-linux-x64-v2",
)
PROBE_CONTENT_V2 = Content(mcp=(PROBE_V2,), agents=(_ORCHESTRATOR,))

PROBE_V3_BYTES = b"the third release"
PROBE_V3 = replace(
    PROBE,
    version="1.2.5",
    checksum=ownership.digest_of_bytes(PROBE_V3_BYTES),
    endpoint="https://example.test/releases/probe-linux-x64-v3",
)
PROBE_CONTENT_V3 = Content(mcp=(PROBE_V3,), agents=(_ORCHESTRATOR,))


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class UpdateDownloadReportTest(RealHomeTestCase):
    """A `download` server already installed under an older version and
    checksum has to be refetched -- it is not new, only different from what
    is on disk -- so a run that replaces it must report it as `updated`, the
    same as any other artifact whose bytes changed. Reporting it as
    `created` instead (the historical shape) tells a caller that installed
    nothing before that this is the first time Pegasus ever placed it, which
    is exactly wrong the one time it matters: `upgrade`'s own report is read
    by an agent deciding what changed, not a person who can eyeball it."""

    def test_a_replaced_dependency_is_reported_as_updated_not_created(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        with patch("pegasus.core.content.load", return_value=PROBE_CONTENT_V2):
            downloader = FakeDownloader({PROBE_V2.endpoint: PROBE_V2_BYTES})
            _, report = self.run_cli("update", "--cli", CLI, downloader=downloader)
        self.assertNotIn("dependency:probe", [item["id"] for item in report["created"]])
        self.assertIn("dependency:probe", [item["id"] for item in report["updated"]])

    def test_a_replaced_dependency_is_previewed_as_updated_not_created(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        with patch("pegasus.core.content.load", return_value=PROBE_CONTENT_V2):
            _, report = self.run_cli("update", "--cli", CLI, "--dry-run")
        self.assertNotIn("dependency:probe", [item["id"] for item in report["created"]])
        self.assertIn("dependency:probe", [item["id"] for item in report["updated"]])


@patch("pegasus.core.content.load", return_value=PROBE_CONTENT)
class PruneOldVersionsTest(RealHomeTestCase):
    """`update` drops versions nothing uses, but keeps the previous one so a
    single `restore` still finds its binary."""

    def version_dir(self, version):
        return self.layout().dependencies_dir / "probe" / version

    def bump(self, content, item, payload):
        with patch("pegasus.core.content.load", return_value=content):
            downloader = FakeDownloader({item.endpoint: payload})
            return self.run_cli("update", "--cli", CLI, downloader=downloader)

    def install_v1_then_bump_to_v3(self):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        _, first = self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        _, second = self.bump(PROBE_CONTENT_V3, PROBE_V3, PROBE_V3_BYTES)
        return first, second

    def test_the_first_update_keeps_the_previous_version_for_restore(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        _, report = self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        self.assertTrue(self.version_dir("1.2.3").is_dir())
        self.assertTrue(self.version_dir("1.2.4").is_dir())
        self.assertEqual(report["pruned_dependencies"], {"removed": [], "failed": []})

    def test_the_second_update_drops_the_version_two_back_and_keeps_the_previous(self, _load):
        _, second = self.install_v1_then_bump_to_v3()
        self.assertFalse(self.version_dir("1.2.3").exists())
        self.assertTrue(self.version_dir("1.2.4").is_dir())
        self.assertTrue(self.version_dir("1.2.5").is_dir())
        self.assertEqual(second["pruned_dependencies"]["removed"], [str(self.version_dir("1.2.3"))])
        self.assertEqual(second["pruned_dependencies"]["failed"], [])

    def test_the_report_is_in_the_prose_too(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        context = self.runtime(FakeDownloader({PROBE_V3.endpoint: PROBE_V3_BYTES}))
        with patch("pegasus.core.content.load", return_value=PROBE_CONTENT_V3):
            cli.main(["update", "--cli", CLI], runtime=context)
        self.assertIn("old versions of downloaded servers", context.out.getvalue())
        self.assertIn(str(self.version_dir("1.2.3")), context.out.getvalue())

    def test_a_dry_run_prunes_nothing_and_says_what_it_would(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        orphan = self.version_dir("0.0.1")
        orphan.mkdir(parents=True)
        with patch("pegasus.core.content.load", return_value=PROBE_CONTENT_V2):
            _, report = self.run_cli("update", "--cli", CLI, "--dry-run")
        self.assertTrue(orphan.is_dir())
        # 1.2.3 is the version two back from what is installed (1.2.4), so a
        # real run would drop it as well.
        self.assertEqual(
            sorted(report["pruned_dependencies"]["removed"]),
            sorted([str(orphan), str(self.version_dir("1.2.3"))]),
        )
        self.assertTrue(self.version_dir("1.2.3").is_dir())

    def test_a_failed_prune_does_not_fail_the_update(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        real = self.filesystem.remove_dir

        def busy(path):
            if path == self.version_dir("1.2.3"):
                raise cli.FileSystemError("busy")
            return real(path)

        self.filesystem.remove_dir = busy
        code, report = self.bump(PROBE_CONTENT_V3, PROBE_V3, PROBE_V3_BYTES)
        self.assertEqual(code, cli.OK)
        self.assertEqual(report["pruned_dependencies"]["removed"], [])
        self.assertTrue(report["pruned_dependencies"]["failed"])

    def test_another_cli_still_on_the_old_version_keeps_it(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        # A second install's journal still points at v1.2.3, as an
        # un-updated sibling CLI's would.
        store = cli.journal_store(self.runtime())
        journal = store.load()
        mine = journal_module.install_for(journal, CLI)
        old = replace(
            next(e for e in mine.entries if e.kind == "dependency-tree"), target=self.version_dir("1.2.3")
        )
        sibling = replace(mine, cli="claudecode", entries=(old,))
        store.save(journal_module.with_install(journal, sibling))
        self.bump(PROBE_CONTENT_V3, PROBE_V3, PROBE_V3_BYTES)
        self.assertTrue(self.version_dir("1.2.3").is_dir())
        self.assertTrue(self.version_dir("1.2.4").is_dir())

    def test_restore_after_an_update_still_finds_the_old_binary(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        code, _ = self.run_cli("restore")
        self.assertEqual(code, cli.OK)
        self.assertTrue((self.version_dir("1.2.3") / "probe-linux-x64").is_file())
        self.assertFalse(self.version_dir("1.2.4").exists())
        entry = next(e for e in self.installed_entries() if e.kind == "dependency-tree")
        self.assertEqual(entry.target, self.version_dir("1.2.3"))

    def test_an_orphan_version_is_cleaned_by_the_next_update(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        orphan = self.version_dir("0.0.1")
        orphan.mkdir(parents=True)
        (orphan / "probe-linux-x64").write_bytes(b"old")
        _, report = self.run_cli("update", "--cli", CLI)
        self.assertFalse(orphan.exists())
        self.assertEqual(report["pruned_dependencies"]["removed"], [str(orphan)])
        self.assertTrue(self.target().is_dir())

    def test_uninstalling_after_an_update_leaves_no_server_directory(self, _load):
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        self.bump(PROBE_CONTENT_V2, PROBE_V2, PROBE_V2_BYTES)
        with patch("pegasus.core.content.load", return_value=PROBE_CONTENT_V2):
            _, report = self.run_cli("uninstall", "--cli", CLI)
        self.assertFalse(self.version_dir("1.2.3").parent.exists())
        self.assertEqual(report["pruned_dependencies"]["removed"], [str(self.version_dir("1.2.3"))])


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

    def test_reinstalling_with_mcp_none_retires_it_without_uninstalling(self, _load):
        """`--mcp` still decides what installs: naming an explicit empty
        selection (`--mcp none`) on a later run retires exactly the
        previously-selected server, and the rest of the installation stays.
        A bare reinstall (dropping `--mcp` altogether) no longer reaches this
        at all -- it now refuses instead of guessing, since it would
        otherwise silently retire this same server; the explicit empty
        selection is how a retirement like this one has to be asked for."""
        self.present()
        self.run_cli("install", "--cli", CLI, "--mcp", "probe")
        code, report = self.run_cli("install", "--cli", CLI, "--mcp", "none")
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
ARCHIVE_CONTENT = Content(mcp=(ARCHIVE_PROBE,), agents=(_ORCHESTRATOR,))


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
