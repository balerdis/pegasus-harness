"""`Upgrade`, through `session`: the same menu-plan-confirm shape as `Update`
and `Install`, but with no `CliOption` of its own -- `pegasus upgrade` takes
no `--cli`, so `session._upgrade_preview` and `session.upgrade_task` build
and confirm the plan with `PEGASUS_PROGRAM` standing in for "the program
itself" wherever `InstallPlanScreen`/`InstallResultScreen` need a `CliOption`
to render.

Every test here drives `cli.upgrade` through `FakeDownloader` and
`FakeFileSystem` -- see `test_cli_upgrade.py`'s own docstring for why a real,
throwaway, empty zip is what proves `sys_path0` resolves to a zipapp.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import pegasus
from fakes import FakeDownloader, FakeFileSystem
from pegasus import cli
from pegasus.core import ownership
from pegasus.tui import session
from pegasus.tui.navigator import (
    PEGASUS_PROGRAM,
    Action,
    InstallPlanScreen,
    InstallResultScreen,
    Menu,
    Navigator,
    UpgradeTarget,
)

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
    from pegasus.core import upgrade as upgrade_module

    return FakeDownloader(
        {
            cli.UPDATE_CHECK_URL: release_body(f"v{version}"),
            upgrade_module.checksum_url(version): sha256sum_line(content),
            upgrade_module.binary_url(version): content,
        }
    )


class UpgradeSessionTestCase(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.destination = Path(self._directory.name) / "pegasus"
        with zipfile.ZipFile(self.destination, "w") as archive:
            archive.writestr("__main__.py", "pass\n")

    def runtime(self, *, downloader=None, filesystem=None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=(
                filesystem if filesystem is not None else FakeFileSystem(files={self.destination: b"old bytes"})
            ),
            home=HOME,
            now=AT,
            out=io.StringIO(),
            variables={},
            downloader=downloader if downloader is not None else upgrade_downloader(),
            sys_path0=str(self.destination),
        )

    def to_upgrade_target(self, navigator: Navigator) -> Navigator:
        index = [entry.label for entry in navigator.current.entries].index("Upgrade")
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator


class ChoosingUpgradeFromTheMenuTest(UpgradeSessionTestCase):
    def test_a_good_upgrade_opens_a_plan_screen_naming_the_versions(self):
        runtime = self.runtime()
        navigator = self.to_upgrade_target(Navigator.starting())
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, InstallPlanScreen)
        self.assertEqual(navigator.current.command, "upgrade")
        self.assertEqual(navigator.current.cli, PEGASUS_PROGRAM)
        self.assertEqual(navigator.current.report["status"], "planned")
        self.assertEqual(navigator.current.report["new_version"], NEWER_VERSION)

    def test_the_preview_writes_nothing(self):
        filesystem = FakeFileSystem(files={self.destination: b"old bytes"})
        runtime = self.runtime(filesystem=filesystem)
        navigator = self.to_upgrade_target(Navigator.starting())
        session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(filesystem.files[self.destination], b"old bytes")
        self.assertEqual(filesystem.writes, [])

    def test_already_current_goes_straight_to_a_result_screen_not_a_plan(self):
        """No plan to preview and nothing to confirm when the destination is
        already current -- lands directly on a result screen, not a plan
        screen with nothing real to show, the same as an unresolved `update`
        binding does. Unlike that case, though, this is not a failure: being
        current already is the successful outcome asking to upgrade was
        for."""
        runtime = self.runtime(downloader=upgrade_downloader(version=CURRENT_VERSION))
        navigator = self.to_upgrade_target(Navigator.starting())
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, InstallResultScreen)
        self.assertEqual(navigator.current.command, "upgrade")
        self.assertEqual(navigator.current.report["status"], "already-current")
        self.assertEqual(navigator.current.report["version"], CURRENT_VERSION)


class ConfirmingTheUpgradePlanTest(UpgradeSessionTestCase):
    def test_confirming_replaces_the_binary_and_opens_a_result_screen(self):
        filesystem = FakeFileSystem(files={self.destination: b"old bytes"})
        runtime = self.runtime(filesystem=filesystem)
        navigator = self.to_upgrade_target(Navigator.starting())
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # confirms it
        self.assertIsInstance(navigator.current, InstallResultScreen)
        self.assertEqual(navigator.current.command, "upgrade")
        report = navigator.current.report
        self.assertEqual(report["status"], "upgraded")
        self.assertEqual(report["old_version"], CURRENT_VERSION)
        self.assertEqual(report["new_version"], NEWER_VERSION)
        self.assertEqual(filesystem.files[self.destination], b"new pegasus bytes")

    def test_upgrade_task_reports_progress_through_the_sink_and_matches_the_synchronous_result(self):
        sync_filesystem = FakeFileSystem(files={self.destination: b"old bytes"})
        sync_runtime = self.runtime(filesystem=sync_filesystem)
        navigator = self.to_upgrade_target(Navigator.starting())
        navigator = session.step(navigator, sync_runtime, Action.CHOOSE)  # fetches the plan
        sync_result = session.step(navigator, sync_runtime, Action.CHOOSE)

        task_filesystem = FakeFileSystem(files={self.destination: b"old bytes"})
        task_runtime = self.runtime(filesystem=task_filesystem)
        navigator = self.to_upgrade_target(Navigator.starting())
        navigator = session.step(navigator, task_runtime, Action.CHOOSE)  # fetches the plan
        plan_screen = navigator.current

        events = []
        run = session.plan_task(navigator, task_runtime, plan_screen)
        task_result = run(events.append)

        self.assertTrue(events, "no Progress event reached the sink")
        self.assertIsInstance(task_result.current, InstallResultScreen)
        self.assertEqual(task_result.current.report["status"], sync_result.current.report["status"])
        self.assertEqual(task_result.current.report["new_version"], sync_result.current.report["new_version"])
        self.assertEqual(task_filesystem.files[self.destination], sync_filesystem.files[self.destination])


if __name__ == "__main__":
    unittest.main()
