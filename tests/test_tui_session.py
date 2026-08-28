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
    Menu,
    Navigator,
    Placeholder,
    RestoreResultScreen,
    StatusRequest,
    StatusScreen,
    UninstallResultScreen,
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


class DetectInstalledTest(SessionTestCase):
    def test_nothing_installed_is_offered_nothing(self):
        self.assertEqual(session.detect_installed(self.runtime()), ())

    def test_an_installed_cli_is_offered_even_once_no_longer_detected(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        self.assertEqual([option.id for option in session.detect_installed(runtime)], [CLI])


class StatusScreenTest(SessionTestCase):
    def test_choosing_status_from_the_main_menu_matches_doctor(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
        for _ in range(2):
            navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertIsInstance(navigator.current.entries[navigator.cursor].target, StatusRequest)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, StatusScreen)
        _, expected = cli.safe_report("doctor", lambda: cli.doctor(runtime))
        self.assertEqual(_sans(navigator.current.report, str(self.home)), _sans(expected, str(self.home)))

    def test_choosing_restore_from_status_with_nothing_captured_says_so(self):
        runtime = self.runtime()
        navigator = Navigator.starting()
        navigator = navigator.handle(Action.MOVE_DOWN).handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # StatusScreen
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # asks for the restore menu
        self.assertIsInstance(navigator.current, Placeholder)


class UninstallThroughTheTuiTest(SessionTestCase):
    def to_preview(self, runtime) -> "Navigator":
        navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
        for _ in range(3):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the CLI choice
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the preview
        return navigator

    def test_the_default_cursor_sits_on_cancel_not_confirm(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = self.to_preview(runtime)
        self.assertEqual(navigator.cursor, 0)
        self.assertIn("Cancel", navigator.current.entries[0].label)

    def test_a_person_who_does_not_confirm_leaves_the_home_untouched(self):
        """The preview shows what would be removed — `preface` is not
        empty — but only ever reads, and a person who does not move onto
        Confirm before pressing enter leaves the home exactly as it was."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        before = _tree(self.home)
        navigator = self.to_preview(runtime)
        self.assertTrue(navigator.current.preface)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # cursor still on Cancel
        self.assertIsInstance(navigator.current, Menu)  # back on the CLI choice
        self.assertEqual(_tree(self.home), before)
        self.assertEqual([option.id for option in session.detect_installed(runtime)], [CLI])

    def test_confirming_matches_the_equivalent_cli_uninstall_on_a_separate_home(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)
                cli.install(CLI, self.runtime(home))

            cli_runtime = self.runtime(self.home)
            cli_code = cli.main(["uninstall", "--cli", CLI, "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            tui_runtime = self.runtime(other_home)
            navigator = self.to_preview(tui_runtime)
            navigator = navigator.handle(Action.MOVE_DOWN)  # onto Confirm
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, UninstallResultScreen)
            self.assertEqual(navigator.current.report["status"], "uninstalled")
            self.assertEqual(_sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home)))

    def test_acknowledging_the_result_returns_to_the_main_menu(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime)
        navigator = self.to_preview(runtime)
        navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        navigator = navigator.handle(Action.CHOOSE)
        self.assertIsInstance(navigator.current, Menu)
        self.assertEqual(navigator.current.title, Navigator.starting().current.title)


class RestoreThroughTheTuiTest(SessionTestCase):
    def _installed_then_uninstalled(self, home: Path) -> cli.Runtime:
        _present(home)
        runtime = self.runtime(home)
        cli.install(CLI, runtime)
        cli.uninstall(CLI, runtime)  # leaves exactly one readable generation behind
        return runtime

    def to_generation_preview(self, runtime) -> "Navigator":
        navigator = Navigator.starting()
        navigator = navigator.handle(Action.MOVE_DOWN).handle(Action.MOVE_DOWN)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # StatusScreen
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # RestoreMenuScreen
        self.assertIsInstance(navigator.current, Menu)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # generation preview
        return navigator

    def test_the_default_cursor_sits_on_cancel_not_confirm(self):
        runtime = self._installed_then_uninstalled(self.home)
        navigator = self.to_generation_preview(runtime)
        self.assertEqual(navigator.cursor, 0)
        self.assertIn("Cancel", navigator.current.entries[0].label)

    def test_a_person_who_does_not_confirm_leaves_the_home_untouched(self):
        """The preview names the generation and what going back to it would
        touch — `preface` is not empty — but only ever reads it back."""
        runtime = self._installed_then_uninstalled(self.home)
        before = _tree(self.home)
        navigator = self.to_generation_preview(runtime)
        self.assertTrue(navigator.current.preface)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # cursor still on Cancel
        self.assertIsInstance(navigator.current, Menu)  # back on the generation choice
        self.assertEqual(_tree(self.home), before)

    def test_confirming_matches_the_equivalent_cli_restore_on_a_separate_home(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            cli_runtime = self._installed_then_uninstalled(self.home)
            tui_runtime = self._installed_then_uninstalled(other_home)

            cli_code = cli.main(["restore", "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            navigator = self.to_generation_preview(tui_runtime)
            navigator = navigator.handle(Action.MOVE_DOWN)  # onto Confirm
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)

            self.assertEqual(cli_code, 0)
            self.assertIsInstance(navigator.current, RestoreResultScreen)
            self.assertEqual(navigator.current.report["status"], "restored")
            self.assertEqual(_sans(cli_report, str(self.home)), _sans(navigator.current.report, str(other_home)))


if __name__ == "__main__":
    unittest.main()


class ConfirmationFitsOnAScreenTest(RealHomeTestCase):
    """A question with a hundred lines above it is a question nobody can see.

    `draw` clamps to the window, so a preface longer than the terminal pushes
    the answers off the bottom — and the one screen where that matters most is
    the one asking whether to remove everything.
    """

    def test_a_long_list_is_counted_rather_than_listed(self):
        lines = tuple(f"item {number}" for number in range(106))
        preface = session._summarised("About to remove", lines, "nothing")
        self.assertLessEqual(len(preface), session.SHOWN_AT_MOST + 2)
        self.assertIn("106", preface[0])
        self.assertIn("and 100 more", preface[-1])

    def test_a_short_list_is_shown_whole_without_a_tail(self):
        preface = session._summarised("About to remove", ("one", "two"), "nothing")
        self.assertEqual(preface, ("About to remove 2:", "  one", "  two"))

    def test_nothing_to_do_says_so_instead_of_counting_zero(self):
        self.assertEqual(session._summarised("About to remove", (), "Nothing recorded to remove."),
                         ("Nothing recorded to remove.",))
