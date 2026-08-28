"""The one place engine calls happen for the TUI: proving the screens they
produce describe exactly what `cli.install` did, on real disk.

`Navigator` and `view` are proven pure elsewhere, so everything here is about
`session.step` — the bridge that calls the same `cli.install` the flags call,
through the same `cli.safe_report` `main` uses, and hands the report back to
`Navigator` untouched.
"""
from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path

from pegasus import cli
from pegasus.adapters import available
from pegasus.core.types import Environment
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import journal_path
from pegasus.infra.snapshot_store_file import snapshots_root
from pegasus.tui import session
from pegasus.tui.navigator import (
    Action,
    InstallPlanScreen,
    InstallResultScreen,
    Navigator,
)
from platform_conditions import make_unwritable
from real_home import RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}


def _layout(home: Path):
    return available().get(CLI).layout(Environment(home=home))


def _present(home: Path) -> None:
    _layout(home).config_dir.mkdir(parents=True, exist_ok=True)


def _sans(value, needle: str):
    """`value`, with every mention of `needle` (one throwaway home's own
    absolute path) replaced by a placeholder, so a report or a file produced
    against one throwaway home compares equal to the same run against a
    different one."""
    if isinstance(value, str):
        return value.replace(needle, "<home>")
    if isinstance(value, list):
        return [_sans(item, needle) for item in value]
    if isinstance(value, dict):
        return {key: _sans(item, needle) for key, item in value.items()}
    return value


def _tree(home: Path, *, skip: frozenset[str] = frozenset()) -> dict[str, bytes]:
    """Every file under `home`, keyed by its path relative to it, with the
    home's own path scrubbed out of the bytes the same way `_sans` scrubs it
    out of a report."""
    return {
        str(path.relative_to(home)): _sans(path.read_bytes().decode("utf-8", "surrogateescape"), str(home)).encode(
            "utf-8", "surrogateescape"
        )
        for path in home.rglob("*")
        if path.is_file() and str(path.relative_to(home)) not in skip
    }


def _journal_shape(home: Path) -> dict:
    """The journal, home path scrubbed and every digest dropped.

    A digest hashes bytes that themselves quote the installing home's own
    absolute path — a rendered prompt names where its own skills live — so
    two different throwaway homes never produce the same digest for
    otherwise identical content. What the journal claims about *which*
    artifact exists and where is exactly what installing the same thing
    twice, on two different homes, should agree on; whether its bytes happen
    to hash the same is not, and comparing it as raw bytes elsewhere would
    fail the way `test_a_tui_install_matches...` did before this existed.
    """
    document = json.loads(journal_path(PosixFileSystem(), home).read_text())
    return _drop_digests(_sans(document, str(home)))


def _drop_digests(value):
    if isinstance(value, dict):
        return {key: _drop_digests(item) for key, item in value.items() if key != "after_digest"}
    if isinstance(value, list):
        return [_drop_digests(item) for item in value]
    return value


class SessionTestCase(RealHomeTestCase):
    def runtime(self, home: Path | None = None) -> cli.Runtime:
        return cli.Runtime(
            filesystem=PosixFileSystem(), home=home or self.home, now=AT, out=io.StringIO(), variables=NO_BINARY
        )


class DetectClisTest(SessionTestCase):
    def test_a_present_cli_is_offered(self):
        _present(self.home)
        options = session.detect_clis(self.runtime())
        self.assertEqual([option.id for option in options], [CLI])

    def test_an_absent_cli_is_not_offered(self):
        self.assertEqual(session.detect_clis(self.runtime()), ())


class PlanStepTest(SessionTestCase):
    def test_choosing_a_detected_cli_fetches_a_preview_and_writes_nothing(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, InstallPlanScreen)
        self.assertEqual(navigator.current.report["status"], "planned")
        self.assertEqual([path for path in _layout(self.home).config_dir.rglob("*") if path.is_file()], [])


class ParityWithCliInstallTest(SessionTestCase):
    def test_a_tui_install_matches_the_equivalent_cli_install_on_a_separate_home(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)

            cli_runtime = self.runtime(self.home)
            cli_code = cli.main(["install", "--cli", CLI, "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            tui_runtime = self.runtime(other_home)
            navigator = Navigator.starting(session.detect_clis(tui_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, InstallResultScreen)
            self.assertEqual(navigator.current.report["status"], "installed")
            self.assertEqual(
                _sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home))
            )
            journal_relative = str(journal_path(PosixFileSystem(), self.home).relative_to(self.home))
            self.assertEqual(
                _tree(self.home, skip=frozenset({journal_relative})),
                _tree(other_home, skip=frozenset({journal_relative})),
            )
            self.assertEqual(_journal_shape(self.home), _journal_shape(other_home))


class InstallFailureThroughTheTuiTest(SessionTestCase):
    def test_a_real_failure_reaches_the_result_screen_as_a_report_not_a_traceback(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, InstallPlanScreen)

        # A real failure: the directory holding the journal refuses the write
        # that would record what this run is about to place -- the same
        # condition test_cli.py drives `_unrecordable` with, produced here
        # rather than mocked.
        snapshots_root(runtime.filesystem, self.home).mkdir(parents=True, exist_ok=True)
        data_dir = journal_path(runtime.filesystem, self.home).parent
        self.addCleanup(make_unwritable(data_dir))

        navigator = session.step(navigator, runtime, Action.CHOOSE)

        self.assertIsInstance(navigator.current, InstallResultScreen)
        report = navigator.current.report
        self.assertEqual(report["status"], "failed")
        self.assertTrue(report["rolled_back"])
        prose = cli.prose_for(report)
        self.assertNotIn("Traceback", prose)
        self.assertIn("taken back out", prose)


if __name__ == "__main__":
    unittest.main()
