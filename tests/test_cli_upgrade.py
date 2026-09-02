"""`pegasus upgrade`: replace the running binary with the newest published one.

Separate from `update`, deliberately: `update` reapplies an installation's own
recorded selection into a CLI's configuration, while `upgrade` replaces the
`pegasus` program itself -- it takes no `--cli`, and it never touches a
journal, a snapshot, or any CLI's configuration at all.

Every test here drives `cli.upgrade` through `FakeDownloader` and
`FakeFileSystem` -- nothing is ever really fetched or really replaced. The one
piece of real disk any of this touches is a throwaway zip file `setUp` builds
fresh per test, standing in for "the zipapp this process is running from":
`cli._running_binary_path` decides whether it is running from a zipapp by
calling `zipfile.is_zipfile` on `Runtime.sys_path0`, and that is a real
filesystem check nothing can fake -- so a real (empty, tiny, disposable) zip
is what a positive case needs, and a real ordinary file or directory is what
a negative case needs.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import pegasus
from fakes import EXECUTABLE_MODE, FakeDownloader, FakeFileSystem
from pegasus import cli
from pegasus.core import ownership
from pegasus.core import upgrade as upgrade_module

AT = "2026-08-14T00:00:00+00:00"
HOME = Path("/home/person")
CURRENT_VERSION = pegasus.__version__
NEWER_VERSION = "99.0.0"


def release_body(tag: str) -> bytes:
    return json.dumps({"tag_name": tag}).encode("utf-8")


def sha256sum_line(content: bytes) -> bytes:
    digest = ownership.digest_of_bytes(content).removeprefix(ownership.PREFIX)
    return f"{digest}  pegasus\n".encode("utf-8")


def upgrade_downloader(*, version: str = NEWER_VERSION, content: bytes = b"new pegasus bytes") -> FakeDownloader:
    return FakeDownloader(
        {
            cli.UPDATE_CHECK_URL: release_body(f"v{version}"),
            upgrade_module.checksum_url(version): sha256sum_line(content),
            upgrade_module.binary_url(version): content,
        }
    )


class UpgradeTestCase(unittest.TestCase):
    """`self.destination` is a real, empty zip file -- exactly what
    `zipfile.is_zipfile` needs to recognise `sys_path0` as a zipapp's own
    path -- while every actual read and write against it goes through
    `FakeFileSystem` instead, which knows nothing about the real file
    sharing its path and never touches it.
    """

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.destination = Path(self._directory.name) / "pegasus"
        with zipfile.ZipFile(self.destination, "w") as archive:
            archive.writestr("__main__.py", "pass\n")

    def make_filesystem(self, **kwargs) -> FakeFileSystem:
        """A `FakeFileSystem` whose destination already carries the
        executable mode, as the binary this process is actually running from
        always does. `replace_binary` now preserves whatever mode is already
        there (see `pegasus.core.upgrade`), so a fixture that left it at the
        fake's plain-file default (`0o644`) would assert against a
        precondition no real running binary could ever have."""
        kwargs.setdefault("files", {self.destination: b"old bytes"})
        modes = dict(kwargs.pop("modes", {}))
        modes.setdefault(self.destination, EXECUTABLE_MODE)
        return FakeFileSystem(modes=modes, **kwargs)

    def runtime(self, *, downloader=None, filesystem=None, sys_path0: str | None = None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=filesystem if filesystem is not None else self.make_filesystem(),
            home=HOME,
            now=AT,
            out=io.StringIO(),
            variables={},
            downloader=downloader if downloader is not None else upgrade_downloader(),
            sys_path0=str(self.destination) if sys_path0 is None else sys_path0,
        )


class ZipappPathTest(unittest.TestCase):
    """Proof, against a real (throwaway) zip, that `zipfile.is_zipfile` is
    what actually tells a zipapp's own path apart from an ordinary file --
    the fact `cli._running_binary_path` leans on."""

    def test_a_real_zip_is_recognised_and_an_ordinary_file_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            zip_path = Path(directory) / "probe.pyz"
            with zipfile.ZipFile(zip_path, "w") as archive:
                archive.writestr("__main__.py", "pass\n")
            plain_path = Path(directory) / "plain.txt"
            plain_path.write_bytes(b"not a zip")
            self.assertTrue(zipfile.is_zipfile(zip_path))
            self.assertFalse(zipfile.is_zipfile(plain_path))


class NotRunningFromAZipappTest(UpgradeTestCase):
    def test_an_empty_sys_path0_refuses_honestly(self):
        runtime = self.runtime(sys_path0="")
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn("not running from an installed executable", str(caught.exception))

    def test_a_sys_path0_that_is_not_a_zip_refuses_honestly(self):
        with tempfile.TemporaryDirectory() as directory:
            # A real directory, exactly what `sys.path[0]` is for `python -m
            # pegasus` run from a source checkout with `PYTHONPATH=src` --
            # the very case this whole refusal exists for.
            runtime = self.runtime(sys_path0=directory)
            with self.assertRaises(cli.CommandError) as caught:
                cli.upgrade(runtime)
            self.assertIn("not running from an installed executable", str(caught.exception))

    def test_an_ordinary_file_that_is_not_a_zip_refuses_honestly(self):
        plain = Path(self._directory.name) / "plain.txt"
        plain.write_bytes(b"not a zip")
        runtime = self.runtime(sys_path0=str(plain))
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn("not running from an installed executable", str(caught.exception))

    def test_the_refusal_never_touches_the_downloader(self):
        downloader = upgrade_downloader()
        runtime = self.runtime(downloader=downloader, sys_path0="")
        with self.assertRaises(cli.CommandError):
            cli.upgrade(runtime)
        self.assertEqual(downloader.calls, [])


class RunningFromAZipappTest(UpgradeTestCase):
    def test_a_real_zip_path_resolves_and_the_upgrade_proceeds(self):
        runtime = self.runtime()
        report = cli.upgrade(runtime)
        self.assertEqual(report["status"], "upgraded")
        self.assertEqual(report["destination"], str(self.destination))


class UnwritableDestinationTest(UpgradeTestCase):
    """`is_writable` is queried once, against the destination itself: the
    real `PosixFileSystem` already answers that from the *containing*
    directory's own permissions (see its own docstring), so there is no
    separate real-world case for "the directory itself is unwritable" to
    probe here that a second call would add -- that distinction is proven
    for real disk in `test_filesystem.py`. What used to be a second test
    here, marking `self.destination.parent` unwritable, tested exactly the
    same single call with a path this fake never actually receives; removed
    rather than kept redundant."""

    def test_refuses_before_any_fetch(self):
        downloader = upgrade_downloader()
        filesystem = self.make_filesystem(unwritable={self.destination})
        runtime = self.runtime(downloader=downloader, filesystem=filesystem)
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn("not writable", str(caught.exception))
        self.assertEqual(downloader.calls, [])

    def test_names_a_manual_replacement_command(self):
        filesystem = self.make_filesystem(unwritable={self.destination})
        runtime = self.runtime(filesystem=filesystem)
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn(str(self.destination), str(caught.exception))


class OwnedBySomeoneElseTest(UpgradeTestCase):
    """`is_writable` no longer looks at the destination's own bits at all
    (see `fs_posix.PosixFileSystem.is_writable`'s own docstring), which
    removes a check that used to also -- accidentally -- refuse taking over
    a file owned by someone else. This is the check that now carries that
    safety on purpose, and it must refuse before any network call, exactly
    like the writability check right next to it."""

    def test_refuses_before_any_fetch(self):
        downloader = upgrade_downloader()
        filesystem = self.make_filesystem(unowned={self.destination})
        runtime = self.runtime(downloader=downloader, filesystem=filesystem)
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn("not owned", str(caught.exception))
        self.assertEqual(downloader.calls, [])

    def test_names_a_manual_replacement_command(self):
        filesystem = self.make_filesystem(unowned={self.destination})
        runtime = self.runtime(filesystem=filesystem)
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn(str(self.destination), str(caught.exception))


class AlreadyCurrentTest(UpgradeTestCase):
    def test_refuses_when_the_newest_published_release_matches_the_running_version(self):
        downloader = upgrade_downloader(version=CURRENT_VERSION)
        runtime = self.runtime(downloader=downloader)
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn("already", str(caught.exception).lower())
        self.assertIn(CURRENT_VERSION, str(caught.exception))


class UnreachableNetworkTest(UpgradeTestCase):
    def test_refuses_plainly_rather_than_claiming_nothing_new(self):
        filesystem = self.make_filesystem()
        runtime = self.runtime(downloader=FakeDownloader({}), filesystem=filesystem)
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        message = str(caught.exception).lower()
        self.assertNotIn("already", message)
        self.assertTrue("could not" in message or "unreachable" in message or "network" in message)

    def test_does_not_touch_the_destination(self):
        filesystem = self.make_filesystem()
        runtime = self.runtime(downloader=FakeDownloader({}), filesystem=filesystem)
        with self.assertRaises(cli.CommandError):
            cli.upgrade(runtime)
        self.assertEqual(filesystem.files[self.destination], b"old bytes")
        self.assertEqual(filesystem.writes, [])


class SuccessfulUpgradeTest(UpgradeTestCase):
    def test_verifies_then_replaces_and_reports_old_new_destination_and_restart(self):
        filesystem = self.make_filesystem()
        runtime = self.runtime(filesystem=filesystem)
        report = cli.upgrade(runtime)
        self.assertEqual(report["status"], "upgraded")
        self.assertEqual(report["old_version"], CURRENT_VERSION)
        self.assertEqual(report["new_version"], NEWER_VERSION)
        self.assertEqual(report["destination"], str(self.destination))
        self.assertTrue(report["restart_required"])
        self.assertEqual(filesystem.files[self.destination], b"new pegasus bytes")
        self.assertEqual(filesystem.modes[self.destination], filesystem.mode_for(executable=True))

    def test_the_temporary_file_is_created_in_the_destinations_own_directory(self):
        filesystem = self.make_filesystem()
        runtime = self.runtime(filesystem=filesystem)
        cli.upgrade(runtime)
        # `FakeFileSystem.write_atomic` records the final path it wrote, but the
        # port's own contract (and the real `PosixFileSystem`) is what actually
        # guarantees the *temporary* file lives in `path.parent` before the
        # rename -- pinned for real disk in `test_filesystem.py`. Here the
        # thing worth pinning is that `cli.upgrade` hands `write_atomic`
        # exactly the destination, never some other path, which is what makes
        # that real guarantee apply to the binary at all.
        self.assertEqual(filesystem.writes, [self.destination])
        self.assertEqual(self.destination.parent, Path(self._directory.name))


class DigestMismatchTest(UpgradeTestCase):
    def test_aborts_and_leaves_the_original_byte_for_byte_intact(self):
        downloader = FakeDownloader(
            {
                cli.UPDATE_CHECK_URL: release_body(f"v{NEWER_VERSION}"),
                upgrade_module.checksum_url(NEWER_VERSION): sha256sum_line(b"not what arrives"),
                upgrade_module.binary_url(NEWER_VERSION): b"the actual download",
            }
        )
        filesystem = self.make_filesystem()
        runtime = self.runtime(downloader=downloader, filesystem=filesystem)
        with self.assertRaises(cli.CommandError) as caught:
            cli.upgrade(runtime)
        self.assertIn("checksum", str(caught.exception).lower())
        self.assertEqual(filesystem.files[self.destination], b"old bytes")
        self.assertEqual(filesystem.writes, [])


class DryRunTest(UpgradeTestCase):
    def test_writes_nothing_and_reports_the_plan(self):
        filesystem = self.make_filesystem()
        runtime = self.runtime(filesystem=filesystem)
        report = cli.upgrade(runtime, dry_run=True)
        self.assertEqual(report["status"], "planned")
        self.assertEqual(report["old_version"], CURRENT_VERSION)
        self.assertEqual(report["new_version"], NEWER_VERSION)
        self.assertEqual(report["destination"], str(self.destination))
        self.assertTrue(report["restart_required"])
        self.assertEqual(filesystem.files[self.destination], b"old bytes")
        self.assertEqual(filesystem.writes, [])

    def test_never_fetches_the_checksum_or_the_binary_itself(self):
        downloader = upgrade_downloader()
        runtime = self.runtime(downloader=downloader)
        cli.upgrade(runtime, dry_run=True)
        self.assertNotIn(upgrade_module.checksum_url(NEWER_VERSION), downloader.calls)
        self.assertNotIn(upgrade_module.binary_url(NEWER_VERSION), downloader.calls)


class CliWiringTest(UpgradeTestCase):
    def test_the_flag_takes_no_cli_argument(self):
        runtime = self.runtime()
        code = cli.main(["upgrade", "--json"], runtime=runtime)
        report = json.loads(runtime.out.getvalue())
        self.assertEqual(code, cli.OK)
        self.assertEqual(report["command"], "upgrade")
        self.assertEqual(report["status"], "upgraded")

    def test_dry_run_flag_is_accepted(self):
        runtime = self.runtime()
        code = cli.main(["upgrade", "--dry-run", "--json"], runtime=runtime)
        report = json.loads(runtime.out.getvalue())
        self.assertEqual(code, cli.OK)
        self.assertEqual(report["status"], "planned")

    def test_a_bogus_extra_argument_is_rejected_by_the_parser(self):
        with self.assertRaises(SystemExit):
            cli.main(["upgrade", "--cli", "claude-code"], runtime=self.runtime())

    def test_prose_names_old_and_new_version_and_restart(self):
        runtime = self.runtime()
        cli.main(["upgrade"], runtime=runtime)
        prose = runtime.out.getvalue()
        self.assertIn(CURRENT_VERSION, prose)
        self.assertIn(NEWER_VERSION, prose)
        self.assertIn("restart", prose.lower())

    def test_a_refusal_reports_failed_status_through_safe_report(self):
        runtime = self.runtime(downloader=FakeDownloader({}))
        code = cli.main(["upgrade", "--json"], runtime=runtime)
        report = json.loads(runtime.out.getvalue())
        self.assertEqual(code, cli.FAILED)
        self.assertEqual(report["status"], "failed")
        self.assertIn("error", report)


if __name__ == "__main__":
    unittest.main()
