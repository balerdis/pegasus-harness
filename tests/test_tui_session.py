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
from pegasus.core import content as content_module
from pegasus.core import model_assignments as model_assignments_module
from pegasus.core.types import Environment
from pegasus.infra.fs_posix import PosixFileSystem
from pegasus.infra.journal_store_file import journal_path
from pegasus.infra.snapshot_store_file import snapshots_root
from pegasus.tui import session
from pegasus.tui.navigator import (
    Action,
    InstallPlanScreen,
    InstallResultScreen,
    McpSelectionScreen,
    Menu,
    ModelsScreen,
    ModelsTarget,
    Navigator,
    Placeholder,
    RestoreResultScreen,
    StatusRequest,
    StatusScreen,
    UninstallResultScreen,
)
from pegasus.tui.view import render
from platform_conditions import make_unwritable
from real_home import RealHomeTestCase

AT = "2026-08-14T00:00:00+00:00"
CLI = available().ids()[0]
NO_BINARY = {"PATH": ""}
CONFIGURABLE_AGENT = "sdd-apply"


def _configurable_agent_names() -> frozenset[str]:
    return frozenset(agent.name for agent in content_module.load().agents if agent.model_configurable)


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

    def to_continue(self, navigator: Navigator) -> Navigator:
        """Move the cursor from wherever it sits on an `McpSelectionScreen`
        onto Continue, touching no checkbox along the way."""
        for _ in range(len(navigator.current.options) - navigator.cursor):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator


class DetectClisTest(SessionTestCase):
    def test_a_present_cli_is_offered(self):
        _present(self.home)
        options = session.detect_clis(self.runtime())
        self.assertEqual([option.id for option in options], [CLI])

    def test_an_absent_cli_is_not_offered(self):
        self.assertEqual(session.detect_clis(self.runtime()), ())


class PlanStepTest(SessionTestCase):
    def test_choosing_a_detected_cli_opens_the_mcp_selection_first(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, McpSelectionScreen)
        self.assertEqual(navigator.current.chosen, ())
        self.assertEqual([path for path in _layout(self.home).config_dir.rglob("*") if path.is_file()], [])

    def test_continuing_past_the_selection_fetches_a_preview_and_writes_nothing(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertIsInstance(navigator.current, InstallPlanScreen)
        self.assertEqual(navigator.current.report["status"], "planned")
        self.assertEqual([path for path in _layout(self.home).config_dir.rglob("*") if path.is_file()], [])


class McpSelectionDefaultsTest(SessionTestCase):
    """What opens pre-checked, and what a person sees to decide with."""

    def test_every_shipped_server_is_offered_with_its_own_description(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        offered = {option.id: option.description for option in navigator.current.options}
        expected = {server.name: server.description for server in content_module.load().mcp}
        self.assertEqual(offered, expected)
        self.assertTrue(all(description for description in offered.values()))

    def test_a_previously_installed_server_opens_pre_checked(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])

        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertIsInstance(navigator.current, McpSelectionScreen)
        self.assertEqual(navigator.current.chosen, ("context7",))

    def test_the_default_cursor_sits_on_the_first_server_not_continue(self):
        """Unlike a destructive confirmation, where the safe entry is
        Cancel, nothing here is destroyed by pressing enter on the first
        row -- it only toggles a checkbox that already opened checked or
        unchecked to match the machine's own state. The unsafe move would be
        a cursor that starts on Continue, one keystroke away from silently
        retiring whatever the journal already lists; starting on the first
        server instead makes that impossible by construction."""
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)
        self.assertEqual(navigator.cursor, 0)
        self.assertLess(navigator.cursor, len(navigator.current.options))

    def test_leaving_a_previously_installed_server_checked_keeps_it_after_reinstalling(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])

        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection, context7 pre-checked
        navigator = self.to_continue(navigator)  # touches nothing
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertEqual(navigator.current.report["retired"], [])
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # confirms it

        self.assertEqual(navigator.current.report["status"], "installed")
        self.assertEqual(session.detect_installed(runtime)[0].id, CLI)
        self.assertEqual(session._currently_chosen_mcp(CLI, runtime), ("context7",))

    def test_unchecking_a_previously_installed_server_retires_it_on_confirm(self):
        _present(self.home)
        runtime = self.runtime()
        cli.install(CLI, runtime, mcp=["context7"])

        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection, context7 pre-checked
        index = next(i for i, option in enumerate(navigator.current.options) if option.id == "context7")
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        navigator = navigator.handle(Action.CHOOSE)  # unchecks context7
        self.assertEqual(navigator.current.chosen, ())
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        self.assertEqual(
            {item["id"] for item in navigator.current.report["retired"]},
            {"mcp:context7", "mcp-convention:context7"},
        )
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # confirms it

        self.assertEqual(navigator.current.report["status"], "installed")
        self.assertEqual(session._currently_chosen_mcp(CLI, runtime), ())


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
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # opens the mcp selection
            navigator = self.to_continue(navigator)  # nothing checked, matching no `--mcp` at all
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # fetches the plan
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # confirms it

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


class ParityWithCliInstallMcpTest(SessionTestCase):
    """The same proof as `ParityWithCliInstallTest`, but with a server
    actually checked: what a person ticks on this screen must land on disk
    exactly as `--mcp context7` would place it, journal included."""

    def test_choosing_a_server_on_screen_matches_the_equivalent_mcp_flag(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)

            cli_runtime = self.runtime(self.home)
            cli_code = cli.main(["install", "--cli", CLI, "--mcp", "context7", "--json"], runtime=cli_runtime)
            cli_report = json.loads(cli_runtime.out.getvalue())

            tui_runtime = self.runtime(other_home)
            navigator = Navigator.starting(session.detect_clis(tui_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # opens the mcp selection
            index = next(i for i, option in enumerate(navigator.current.options) if option.id == "context7")
            for _ in range(index):
                navigator = navigator.handle(Action.MOVE_DOWN)
            navigator = navigator.handle(Action.CHOOSE)  # checks context7
            self.assertEqual(navigator.current.chosen, ("context7",))
            navigator = self.to_continue(navigator)
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # fetches the plan
            self.assertEqual(navigator.current.report["status"], "planned")
            navigator = session.step(navigator, tui_runtime, Action.CHOOSE)  # confirms it

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


class InstallTaskTest(SessionTestCase):
    """`session.install_task` is the seam `app.py` runs on a worker thread:
    a plain callable that performs the real install, reports every tick
    through the sink it is handed, and returns the same `Navigator` update
    `session.step`'s own `InstallPlanScreen` branch produces -- without
    `session` itself ever importing `threading` or `time`.
    """

    def test_it_reports_progress_through_the_given_sink(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
        plan_screen = navigator.current

        run = session.install_task(navigator, runtime, plan_screen)
        events = []
        result = run(events.append)

        self.assertTrue(events, "no Progress event reached the sink")
        self.assertEqual(events[-1].done, events[-1].total)
        self.assertIsInstance(result, Navigator)
        self.assertIsInstance(result.current, InstallResultScreen)
        self.assertEqual(result.current.report["status"], "installed")

    def test_it_matches_session_steps_own_synchronous_result(self):
        with tempfile.TemporaryDirectory(dir=self.home.parent) as other:
            other_home = Path(other)
            for home in (self.home, other_home):
                _present(home)

            sync_runtime = self.runtime(self.home)
            navigator = Navigator.starting(session.detect_clis(sync_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, sync_runtime, Action.CHOOSE)
            navigator = self.to_continue(navigator)
            navigator = session.step(navigator, sync_runtime, Action.CHOOSE)
            sync_result = session.step(navigator, sync_runtime, Action.CHOOSE)

            task_runtime = self.runtime(other_home)
            navigator = Navigator.starting(session.detect_clis(task_runtime)).handle(Action.CHOOSE)
            navigator = session.step(navigator, task_runtime, Action.CHOOSE)
            navigator = self.to_continue(navigator)
            navigator = session.step(navigator, task_runtime, Action.CHOOSE)
            task_result = session.install_task(navigator, task_runtime, navigator.current)(lambda progress: None)

            self.assertEqual(
                _sans(sync_result.current.report, str(self.home)),
                _sans(task_result.current.report, str(other_home)),
            )


class InstallFailureThroughTheTuiTest(SessionTestCase):
    def test_a_real_failure_reaches_the_result_screen_as_a_report_not_a_traceback(self):
        _present(self.home)
        runtime = self.runtime()
        navigator = Navigator.starting(session.detect_clis(runtime)).handle(Action.CHOOSE)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # opens the mcp selection
        navigator = self.to_continue(navigator)
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # fetches the plan
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


def _write_catalog(home: Path, payload: dict) -> None:
    path = home / ".cache" / "opencode" / "models.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_credentials(home: Path, payload: dict) -> None:
    path = home / ".local" / "share" / "opencode" / "auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


ONE_PLAIN_MODEL = {"anthropic": {"builtin": True, "models": {"fast-model": {"tool_call": True}}}}
ONE_REASONING_MODEL = {"anthropic": {"builtin": True, "models": {"deep-thinker": {"tool_call": True, "reasoning": True}}}}


class ModelsScreenTestCase(SessionTestCase):
    def to_models_screen(self, runtime: cli.Runtime) -> Navigator:
        _present(self.home)
        navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
        navigator = navigator.handle(Action.MOVE_DOWN)  # onto "Configure models"
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # the per-CLI choice, pure
        return session.step(navigator, runtime, Action.CHOOSE)  # fetches the catalog


class EmptyCatalogTest(ModelsScreenTestCase):
    def test_no_catalog_yet_is_explained_not_an_error(self):
        navigator = self.to_models_screen(self.runtime())
        self.assertIsInstance(navigator.current, Placeholder)
        self.assertNotIn("Traceback", navigator.current.note)


class AssignmentListTest(ModelsScreenTestCase):
    def test_every_configurable_agent_is_listed_starting_with_no_model(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        navigator = self.to_models_screen(self.runtime())
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertEqual({row.agent for row in navigator.current.rows}, _configurable_agent_names())
        self.assertTrue(all(row.current is None for row in navigator.current.rows))

    def test_only_the_reachable_providers_and_their_models_are_offered(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        navigator = self.to_models_screen(self.runtime())
        self.assertEqual([provider.id for provider in navigator.current.providers], ["anthropic"])
        self.assertEqual([model.id for model in navigator.current.providers[0].models], ["fast-model"])


class WalkTheFourStepsTest(ModelsScreenTestCase):
    def _to_agent_row(self, navigator: Navigator) -> Navigator:
        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator.handle(Action.CHOOSE)

    def test_a_plain_model_is_assigned_immediately_and_matches_models_set(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = self._to_agent_row(navigator)  # agent chosen
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = session.step(navigator, runtime, Action.CHOOSE)  # the one, plain, model: commits

        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertIsNone(navigator.current.agent)  # back at the rows step, refreshed
        assignments = cli.model_assignment_store(runtime).load()
        assignment = model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT)
        self.assertEqual(assignment.full_id, "anthropic/fast-model")
        self.assertIsNone(assignment.effort)
        row = next(row for row in navigator.current.rows if row.agent == CONFIGURABLE_AGENT)
        self.assertEqual(row.current, "anthropic/fast-model")

    def test_a_reasoning_model_asks_for_effort_before_it_is_assigned(self):
        _write_catalog(self.home, ONE_REASONING_MODEL)
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        navigator = self._to_agent_row(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the one provider
        navigator = navigator.handle(Action.CHOOSE)  # the one, reasoning, model: only narrows
        self.assertEqual(navigator.current.model_id, "deep-thinker")

        navigator = session.step(navigator, runtime, Action.CHOOSE)  # the first effort offered: commits
        self.assertIsInstance(navigator.current, ModelsScreen)
        self.assertIsNone(navigator.current.agent)
        assignments = cli.model_assignment_store(runtime).load()
        assignment = model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT)
        self.assertEqual(assignment.full_id, "anthropic/deep-thinker")
        self.assertIsNotNone(assignment.effort)


class RemovingAnAssignmentTest(ModelsScreenTestCase):
    def test_d_unsets_the_assignment_and_matches_models_unset(self):
        _write_catalog(self.home, ONE_PLAIN_MODEL)
        runtime = self.runtime()
        cli.models_set(CLI, CONFIGURABLE_AGENT, "anthropic/fast-model", runtime)

        navigator = self.to_models_screen(runtime)
        index = next(i for i, row in enumerate(navigator.current.rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        self.assertEqual(navigator.current.rows[navigator.cursor].current, "anthropic/fast-model")

        navigator = session.step(navigator, runtime, Action.REMOVE)
        self.assertIsInstance(navigator.current, ModelsScreen)
        assignments = cli.model_assignment_store(runtime).load()
        self.assertIsNone(model_assignments_module.get(assignments, CLI, CONFIGURABLE_AGENT))
        row = next(row for row in navigator.current.rows if row.agent == CONFIGURABLE_AGENT)
        self.assertIsNone(row.current)


class NoCredentialReachesARenderedLineTest(ModelsScreenTestCase):
    """The same guarantee `model_catalog` already proves for itself, proven
    again at the screen level: nothing this screen renders may repeat a
    credential's own value, wherever in the walk it is shown."""

    SECRET = "top-secret-oauth-token"

    def test_a_credential_value_never_appears_in_a_rendered_line(self):
        _write_catalog(self.home, ONE_REASONING_MODEL)
        _write_credentials(self.home, {"anthropic": {"type": "oauth", "access": self.SECRET}})
        runtime = self.runtime()
        navigator = self.to_models_screen(runtime)
        self._assert_secret_free(navigator)

        navigator = self._to_agent_row(navigator)
        self._assert_secret_free(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the provider
        self._assert_secret_free(navigator)
        navigator = navigator.handle(Action.CHOOSE)  # the model: only narrows, it is a reasoning one
        self._assert_secret_free(navigator)

    def _to_agent_row(self, navigator: Navigator) -> Navigator:
        rows = navigator.current.rows
        index = next(i for i, row in enumerate(rows) if row.agent == CONFIGURABLE_AGENT)
        for _ in range(index):
            navigator = navigator.handle(Action.MOVE_DOWN)
        return navigator.handle(Action.CHOOSE)

    def _assert_secret_free(self, navigator: Navigator) -> None:
        lines = render(navigator.current, navigator.cursor)
        for line in lines:
            self.assertNotIn(self.SECRET, line.text)


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
