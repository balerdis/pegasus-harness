"""The one thing in the drawing layer worth testing on its own: turning a key
code into an :class:`Action`. It is a lookup table, not a decision, and
reading `curses`'s key constants needs no terminal — only starting one does,
and nothing here does that.

`draw` and `accent_choice` are tested too, against a fake window and fake
curses facts respectively -- neither needs a real terminal, only real curses
constants, which are plain module attributes available without one.
"""
from __future__ import annotations

import curses
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from pegasus import cli
from pegasus.tui import app as app_module
from pegasus.tui.app import accent_choice, action_for, draw
from pegasus.tui.navigator import Action, BehindInstall, CliOption, InstallPlanScreen, Navigator, UpdateNotice
from pegasus.tui.view import Line, Span, Style


class KeyMappingTest(unittest.TestCase):
    def test_the_arrow_keys_map_to_movement(self):
        self.assertEqual(action_for(curses.KEY_UP), Action.MOVE_UP)
        self.assertEqual(action_for(curses.KEY_DOWN), Action.MOVE_DOWN)

    def test_vi_style_keys_map_to_the_same_movement(self):
        self.assertEqual(action_for(ord("k")), Action.MOVE_UP)
        self.assertEqual(action_for(ord("j")), Action.MOVE_DOWN)

    def test_enter_chooses(self):
        self.assertEqual(action_for(curses.KEY_ENTER), Action.CHOOSE)
        self.assertEqual(action_for(ord("\n")), Action.CHOOSE)

    def test_escape_goes_back(self):
        self.assertEqual(action_for(27), Action.BACK)

    def test_q_quits(self):
        self.assertEqual(action_for(ord("q")), Action.QUIT)

    def test_d_removes(self):
        self.assertEqual(action_for(ord("d")), Action.REMOVE)

    def test_space_toggles(self):
        self.assertEqual(action_for(ord(" ")), Action.TOGGLE)

    def test_an_unmapped_key_means_nothing(self):
        self.assertIsNone(action_for(ord("z")))


class _FakeWindow:
    """Just enough of a curses window for `draw` to write into and for a
    test to inspect what it wrote: every `addstr` call recorded verbatim,
    and the one call `curses` itself would refuse -- the bottom-right cell.
    """

    def __init__(self, height: int, width: int) -> None:
        self.height = height
        self.width = width
        self.calls: list[tuple[int, int, str, int]] = []

    def erase(self) -> None:
        self.calls.clear()

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def addstr(self, row: int, column: int, text: str, attribute: int) -> None:
        if row == self.height - 1 and column + len(text) >= self.width:
            raise curses.error("cannot write to the bottom-right cell")
        self.calls.append((row, column, text, attribute))

    def refresh(self) -> None:
        pass


class DrawSpanTest(unittest.TestCase):
    def test_each_span_becomes_its_own_addstr_call_advancing_the_column(self):
        window = _FakeWindow(height=5, width=80)
        line = Line((Span("PEGASUS  ", Style.DIM), Span("HARNESS", Style.NORMAL)))
        draw(window, (line,))
        texts = [(column, text) for _, column, text, _ in window.calls]
        self.assertEqual(texts, [(0, "PEGASUS  "), (9, "HARNESS")])

    def test_dim_style_carries_the_dim_attribute(self):
        window = _FakeWindow(height=5, width=80)
        draw(window, (Line((Span("x", Style.DIM),)),))
        _, _, _, attribute = window.calls[0]
        self.assertTrue(attribute & curses.A_DIM)

    def test_accent_style_carries_the_given_accent_attribute(self):
        window = _FakeWindow(height=5, width=80)
        marker = curses.A_UNDERLINE
        draw(window, (Line((Span("x", Style.ACCENT),)),), accent_attr=marker)
        _, _, _, attribute = window.calls[0]
        self.assertTrue(attribute & marker)

    def test_highlighted_reverses_every_span_on_the_line(self):
        window = _FakeWindow(height=5, width=80)
        draw(window, (Line((Span("a"), Span("b")), highlighted=True),))
        for _, _, _, attribute in window.calls:
            self.assertTrue(attribute & curses.A_REVERSE)

    def test_a_line_longer_than_the_width_is_clipped_not_raised(self):
        window = _FakeWindow(height=5, width=10)
        draw(window, (Line("x" * 50),))  # would raise if handed to addstr whole
        _, _, text, _ = window.calls[0]
        self.assertEqual(len(text), 10)

    def test_the_bottom_right_cell_is_never_written_to(self):
        """Writing to it raises in real curses; `draw` must leave one column
        of room on the last row instead of ever attempting it."""
        window = _FakeWindow(height=3, width=10)
        lines = tuple(Line("x" * 10) for _ in range(3))
        draw(window, lines)  # would raise via _FakeWindow.addstr if this room were not left
        last_row_text = next(text for row, _, text, _ in window.calls if row == 2)
        self.assertEqual(len(last_row_text), 9)

    def test_rows_past_the_window_height_are_simply_not_drawn(self):
        window = _FakeWindow(height=2, width=80)
        lines = tuple(Line(f"row {i}") for i in range(5))
        draw(window, lines)
        drawn_rows = {row for row, _, _, _ in window.calls}
        self.assertEqual(drawn_rows, {0, 1})


class AccentChoiceTest(unittest.TestCase):
    """What `draw`'s accent attribute should be, decided from plain facts a
    real terminal may or may not offer -- no terminal needed to test it."""

    def test_full_256_colour_support_picks_the_installers_own_colour(self):
        kind, value = accent_choice(has_colors=True, colors=256)
        self.assertEqual(kind, "color")
        self.assertEqual(value, 214)

    def test_more_than_256_colours_still_picks_the_installers_own_colour(self):
        kind, value = accent_choice(has_colors=True, colors=16777216)
        self.assertEqual(kind, "color")
        self.assertEqual(value, 214)

    def test_only_eight_or_sixteen_colours_falls_back_to_a_named_colour(self):
        kind, value = accent_choice(has_colors=True, colors=8)
        self.assertEqual(kind, "color")
        self.assertEqual(value, curses.COLOR_YELLOW)

    def test_no_colour_support_falls_back_to_a_plain_attribute(self):
        kind, value = accent_choice(has_colors=False, colors=0)
        self.assertEqual(kind, "attr")
        self.assertEqual(value, curses.A_BOLD)


class InitColorsTest(unittest.TestCase):
    """`_init_colors` is the one place `accent_choice`'s decision actually
    touches curses state -- these calls can fail even when `accent_choice`
    thought colour was safe, and that must not take the whole TUI down."""

    def test_a_terminal_that_lies_about_colour_support_falls_back_to_plain(self):
        with (
            mock.patch.object(app_module.curses, "has_colors", return_value=True),
            mock.patch.object(app_module.curses, "COLORS", 256, create=True),
            mock.patch.object(app_module.curses, "start_color"),
            mock.patch.object(
                app_module.curses, "use_default_colors", side_effect=curses.error("no such capability")
            ),
            mock.patch.object(app_module.curses, "init_pair"),
        ):
            attribute = app_module._init_colors()
        self.assertEqual(attribute, curses.A_BOLD)


class _FakeInstallWindow:
    """Just enough of a curses window for `_run_install`'s animation loop:
    `getch` can be scripted to return plain tick values or to raise, the way
    a real blocked `getch` raises `KeyboardInterrupt` when `SIGINT` arrives
    during it.
    """

    def __init__(self, height: int = 10, width: int = 40, getch_script=None) -> None:
        self.height = height
        self.width = width
        self.calls: list[tuple[int, int, str, int]] = []
        self.timeouts: list[int] = []
        self._getch_script = list(getch_script or [])

    def erase(self) -> None:
        self.calls.clear()

    def getmaxyx(self) -> tuple[int, int]:
        return self.height, self.width

    def addstr(self, row: int, column: int, text: str, attribute: int) -> None:
        self.calls.append((row, column, text, attribute))

    def refresh(self) -> None:
        pass

    def timeout(self, milliseconds: int) -> None:
        self.timeouts.append(milliseconds)

    def getch(self) -> int:
        if self._getch_script:
            item = self._getch_script.pop(0)
            if isinstance(item, type) and issubclass(item, BaseException):
                raise item
            return item
        return -1

    def drawn_text(self) -> str:
        return " ".join(text for _, _, text, _ in self.calls)


class RunInstallTest(unittest.TestCase):
    """`_run_install` has never had a test of its own -- precisely why a
    worker exception collapsing into a meaningless `IndexError`, and a
    `Ctrl+C` abandoning an in-flight install on a daemon thread, both shipped
    unnoticed. These pin the two fixes down."""

    def _navigator(self) -> SimpleNamespace:
        # `busy_message_for` falls through to `None` for a screen it does
        # not recognise, so a bare stand-in is enough -- `_run_install` never
        # inspects the screen itself beyond handing it to `session`, which
        # every test here replaces.
        return SimpleNamespace(current=None, cursor=0)

    def test_a_non_command_error_from_the_worker_surfaces_unchanged(self):
        window = _FakeInstallWindow()

        def task(_sink):
            raise TypeError("sink chain exploded")

        with (
            mock.patch.object(app_module.session, "plan_task", return_value=task),
            mock.patch.object(app_module.curses, "flushinp"),
        ):
            with self.assertRaises(TypeError) as caught:
                app_module._run_install(window, self._navigator(), runtime=None, accent_attr=curses.A_BOLD)
        self.assertEqual(str(caught.exception), "sink chain exploded")

    def test_a_bare_os_error_from_the_worker_also_surfaces_unchanged(self):
        # `cli.safe_report` only catches `COMMAND_ERRORS`; a disk-full or
        # permission failure is a bare `OSError` that escapes it entirely.
        window = _FakeInstallWindow()

        def task(_sink):
            raise OSError("No space left on device")

        with (
            mock.patch.object(app_module.session, "plan_task", return_value=task),
            mock.patch.object(app_module.curses, "flushinp"),
        ):
            with self.assertRaises(OSError) as caught:
                app_module._run_install(window, self._navigator(), runtime=None, accent_attr=curses.A_BOLD)
        self.assertEqual(str(caught.exception), "No space left on device")

    def test_keyboard_interrupt_still_joins_the_worker_and_restores_blocking_input(self):
        finished = threading.Event()

        def task(_sink):
            time.sleep(0.05)
            finished.set()
            return "install-result"

        window = _FakeInstallWindow(getch_script=[KeyboardInterrupt])

        with (
            mock.patch.object(app_module.session, "plan_task", return_value=task),
            mock.patch.object(app_module.curses, "flushinp") as flushinp,
        ):
            with self.assertRaises(KeyboardInterrupt):
                app_module._run_install(window, self._navigator(), runtime=None, accent_attr=curses.A_BOLD)

        # The join in `finally` must have actually waited -- if it merely
        # detached, the worker's `Event` would still be unset here.
        self.assertTrue(finished.is_set())
        self.assertIn(-1, window.timeouts)
        flushinp.assert_called_once()

    def test_keyboard_interrupt_draws_a_waiting_message_before_blocking_on_join(self):
        def task(_sink):
            time.sleep(0.02)
            return "install-result"

        window = _FakeInstallWindow(width=120, getch_script=[KeyboardInterrupt])

        with (
            mock.patch.object(app_module.session, "plan_task", return_value=task),
            mock.patch.object(app_module.curses, "flushinp"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                app_module._run_install(window, self._navigator(), runtime=None, accent_attr=curses.A_BOLD)

        self.assertIn("cannot be safely interrupted", window.drawn_text())

    def test_the_happy_path_still_returns_the_worker_outcome(self):
        window = _FakeInstallWindow(getch_script=[-1, -1, -1])

        def task(_sink):
            return "install-result"

        with (
            mock.patch.object(app_module.session, "plan_task", return_value=task),
            mock.patch.object(app_module.curses, "flushinp") as flushinp,
        ):
            result = app_module._run_install(window, self._navigator(), runtime=None, accent_attr=curses.A_BOLD)

        self.assertEqual(result, "install-result")
        self.assertIn(-1, window.timeouts)
        flushinp.assert_called_once()


def _fake_clock(*ticks: float):
    """An injectable `now=` that hands out `ticks` one at a time, in order --
    driven explicitly by the test rather than by real elapsed time, per this
    module's own constraint that a rate computed from a clock must be
    provable without ever sleeping."""
    values = iter(ticks)
    return lambda: next(values)


def _progress(bytes_downloaded, unit="engram"):
    return cli.Progress(done=1, total=5, phase="dependencies", unit=unit, bytes_downloaded=bytes_downloaded, bytes_total=100)


class DownloadRateTrackerTest(unittest.TestCase):
    """Turning successive `(bytes, wall-clock-time)` observations into a
    bytes/second rate -- the one piece of arithmetic this feature needs a
    real clock for, and the reason it lives in `app.py` and nowhere else
    (see `_DownloadRateTracker`'s own docstring for the full argument).
    """

    def test_the_first_observation_has_no_rate_yet(self):
        tracker = app_module._DownloadRateTracker(now=_fake_clock(0.0))
        self.assertIsNone(tracker.observe(_progress(1000)))

    def test_a_second_observation_too_soon_still_has_no_rate(self):
        """Below the minimum interval, two observations are too close
        together to trust the arithmetic -- reporting a rate anyway would be
        reporting noise, not a slow or fast download."""
        tracker = app_module._DownloadRateTracker(now=_fake_clock(0.0, 0.05))
        tracker.observe(_progress(1000))
        self.assertIsNone(tracker.observe(_progress(2000)))

    def test_a_rate_appears_once_enough_time_has_passed(self):
        tracker = app_module._DownloadRateTracker(now=_fake_clock(0.0, 1.0))
        tracker.observe(_progress(1000))
        rate = tracker.observe(_progress(2024))
        self.assertAlmostEqual(rate, 1024.0)

    def test_a_stale_rate_keeps_reading_until_the_next_window_closes(self):
        """A tick that arrives before the next window has closed must not
        report `None` and erase a rate that was already trustworthy --
        `view.py`'s honest-degradation rule is for *no rate ever computed*,
        not for *no new rate this particular tick*."""
        tracker = app_module._DownloadRateTracker(now=_fake_clock(0.0, 1.0, 1.05))
        tracker.observe(_progress(1000))
        first_rate = tracker.observe(_progress(2024))
        second_rate = tracker.observe(_progress(2100))
        self.assertEqual(first_rate, second_rate)

    def test_a_new_download_starting_resets_the_tracker(self):
        """A different unit name is a different fetch entirely -- carrying a
        stale rate over from whatever downloaded before it would be exactly
        the wrong number on screen."""
        tracker = app_module._DownloadRateTracker(now=_fake_clock(0.0, 1.0, 1.0))
        tracker.observe(_progress(1000, unit="first-server"))
        tracker.observe(_progress(2024, unit="first-server"))
        self.assertIsNone(tracker.observe(_progress(10, unit="second-server")))

    def test_a_non_download_progress_value_resets_the_tracker_too(self):
        tracker = app_module._DownloadRateTracker(now=_fake_clock(0.0, 1.0))
        tracker.observe(_progress(1000))
        no_bytes = cli.Progress(done=2, total=5, phase="artifacts", unit="a.md")
        self.assertIsNone(tracker.observe(no_bytes))

    def test_the_real_clock_is_the_default(self):
        tracker = app_module._DownloadRateTracker()
        self.assertIs(tracker._now, time.monotonic)


class UpdateCheckHolderTest(unittest.TestCase):
    """Same lock-guarded-value shape `_ProgressHolder` already uses, for the
    same reason -- proven the same way, no thread required to exercise it."""

    def test_starts_undone(self):
        holder = app_module._UpdateCheckHolder()
        done, latest = holder.snapshot()
        self.assertFalse(done)
        self.assertIsNone(latest)

    def test_set_marks_it_done_and_carries_the_answer(self):
        holder = app_module._UpdateCheckHolder()
        holder.set("5.11.0")
        done, latest = holder.snapshot()
        self.assertTrue(done)
        self.assertEqual(latest, "5.11.0")

    def test_set_to_none_is_still_done(self):
        """`None` is a legitimate answer -- disabled, or every failure mode
        `cli.check_for_update` collapses to -- and must not read the same as
        `snapshot`'s own initial, not-yet-answered state."""
        holder = app_module._UpdateCheckHolder()
        holder.set(None)
        done, latest = holder.snapshot()
        self.assertTrue(done)
        self.assertIsNone(latest)


class StartUpdateCheckTest(unittest.TestCase):
    """`_start_update_check`: the background version check now gets the
    same exception boundary and join-ability `_run_install`'s own worker
    already has, rather than a bare `threading.Thread(...)` with neither.
    """

    def test_the_happy_path_still_reaches_the_holder(self):
        with mock.patch.object(app_module.cli, "check_for_update", return_value="5.11.0"):
            holder = app_module._UpdateCheckHolder()
            thread = app_module._start_update_check(runtime=None, holder=holder)
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(holder.snapshot(), (True, "5.11.0"))

    def test_an_exception_from_check_for_update_does_not_escape_the_thread(self):
        """Regression pin: the old bare `threading.Thread(target=lambda: ...)`
        had no `try/except` at all, so anything `check_for_update` failed to
        collapse to `None` itself would vanish through `threading.excepthook`
        instead of leaving `holder` with a legitimate answer."""
        with mock.patch.object(app_module.cli, "check_for_update", side_effect=RuntimeError("boom")):
            holder = app_module._UpdateCheckHolder()
            thread = app_module._start_update_check(runtime=None, holder=holder)
            thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(holder.snapshot(), (True, None))

    def test_the_returned_thread_is_a_daemon(self):
        with mock.patch.object(app_module.cli, "check_for_update", return_value=None):
            holder = app_module._UpdateCheckHolder()
            thread = app_module._start_update_check(runtime=None, holder=holder)
            thread.join(timeout=1)
        self.assertTrue(thread.daemon)


class MergedNoticeTest(unittest.TestCase):
    """`_merged_notice`: folding the remote answer into the navigator once
    it lands, without ever touching a window or a clock."""

    def test_still_waiting_leaves_the_navigator_untouched(self):
        navigator = Navigator.starting()
        holder = app_module._UpdateCheckHolder()
        notice = UpdateNotice(running="5.10.0")
        merged, done = app_module._merged_notice(navigator, notice, holder)
        self.assertFalse(done)
        self.assertIs(merged, navigator)

    def test_a_resolved_answer_is_folded_into_the_main_menu(self):
        navigator = Navigator.starting()
        holder = app_module._UpdateCheckHolder()
        holder.set("5.11.0")
        notice = UpdateNotice(running="5.10.0")
        merged, done = app_module._merged_notice(navigator, notice, holder)
        self.assertTrue(done)
        self.assertTrue(any("5.11.0" in line for line in merged.current.preface))

    def test_a_resolved_none_answer_is_folded_in_as_no_remote_fact(self):
        navigator = Navigator.starting()
        holder = app_module._UpdateCheckHolder()
        holder.set(None)
        notice = UpdateNotice(running="5.10.0")
        merged, done = app_module._merged_notice(navigator, notice, holder)
        self.assertTrue(done)
        self.assertEqual(merged.current.preface, ())

    def test_the_local_half_of_the_notice_survives_the_merge(self):
        local_behind = (BehindInstall(display_name="Demo CLI", recorded="5.9.0"),)
        navigator = Navigator.starting(notice=UpdateNotice(running="5.10.0", local_behind=local_behind))
        holder = app_module._UpdateCheckHolder()
        holder.set("5.11.0")
        notice = UpdateNotice(running="5.10.0", local_behind=local_behind)
        merged, done = app_module._merged_notice(navigator, notice, holder)
        self.assertTrue(done)
        self.assertTrue(any("Update" in line for line in merged.current.preface))
        self.assertTrue(any("5.11.0" in line for line in merged.current.preface))


class MainLoopUpdateCheckTest(unittest.TestCase):
    """`_main_loop`: the menu answers keys from its very first tick, and the
    background update check never blocks it -- proven here by resolving the
    check only after several ordinary key presses have already been acted
    on, then checking that blocking input (`timeout(-1)`) is restored once
    it does resolve.
    """

    def test_navigation_works_before_the_check_resolves_and_input_blocks_again_after(self):
        navigator = Navigator.starting()
        holder = app_module._UpdateCheckHolder()
        notice = UpdateNotice(running="5.10.0")
        exit_index = len(navigator.current.entries) - 1

        # Reach and choose Exit while the check is still pending for the
        # first two polls -- if the loop ever blocked on the check instead
        # of acting on these keys, `final.quit` below would never be true.
        window = _FakeInstallWindow(getch_script=[curses.KEY_DOWN] * exit_index + [curses.KEY_ENTER])

        calls = {"n": 0}
        real_snapshot = holder.snapshot

        def snapshot():
            calls["n"] += 1
            if calls["n"] <= 2:
                return False, None
            return real_snapshot()

        holder.set(None)  # the answer that will be picked up once `snapshot` stops faking "pending"
        window.timeout(app_module.UPDATE_CHECK_POLL_MS)  # what `run` does before entering `_main_loop`
        with mock.patch.object(holder, "snapshot", side_effect=snapshot):
            final = app_module._main_loop(
                window, navigator, runtime=None, accent_attr=curses.A_BOLD, notice=notice, holder=holder
            )

        self.assertTrue(final.quit, "the menu never reached Exit -- navigation was blocked by the update check")
        self.assertIn(app_module.UPDATE_CHECK_POLL_MS, window.timeouts)
        self.assertIn(-1, window.timeouts)
        # Blocking is restored only once the check resolves, never before.
        self.assertEqual(window.timeouts[0], app_module.UPDATE_CHECK_POLL_MS)

    def test_entering_install_while_the_check_is_pending_does_not_break_the_poll_window(self):
        """Regression pin: `_run_install`'s `finally` used to hardcode
        `window.timeout(-1)`, clobbering `_main_loop`'s own poll window
        whenever an install was confirmed before the background check
        resolved. Once `_run_install` returns, `_main_loop` must reassert
        its own poll timeout on its very next iteration -- before blocking
        on the next `getch` -- rather than leaving the terminal in blocking
        mode for however long the check has left.
        """
        starting = Navigator.starting()
        exit_index = len(starting.current.entries) - 1
        navigator = starting.opened(
            InstallPlanScreen(cli=CliOption(id="demo", display_name="Demo", config_dir="", tier="full"), report={})
        )
        holder = app_module._UpdateCheckHolder()  # never resolved: `checking` stays True throughout
        notice = UpdateNotice(running="5.10.0")

        window = _FakeInstallWindow(
            getch_script=[curses.KEY_ENTER]
            + [-1] * 20
            + [curses.KEY_DOWN] * exit_index
            + [curses.KEY_ENTER]
        )
        window.timeout(app_module.UPDATE_CHECK_POLL_MS)  # what `run` does before entering `_main_loop`

        def task(_sink):
            return starting  # a fresh, non-quit navigator to land the outer loop back on

        with (
            mock.patch.object(app_module.session, "plan_task", return_value=task),
            mock.patch.object(app_module.curses, "flushinp"),
        ):
            final = app_module._main_loop(
                window, navigator, runtime=None, accent_attr=curses.A_BOLD, notice=notice, holder=holder
            )

        self.assertTrue(final.quit)
        finally_index = window.timeouts.index(-1)
        self.assertEqual(
            window.timeouts[finally_index + 1],
            app_module.UPDATE_CHECK_POLL_MS,
            f"poll timeout was not reasserted right after the install's own timeout(-1): {window.timeouts}",
        )

    def test_quitting_while_the_check_is_still_pending_still_works(self):
        navigator = Navigator.starting()
        holder = app_module._UpdateCheckHolder()  # never resolved
        notice = UpdateNotice(running="5.10.0")
        exit_index = len(navigator.current.entries) - 1
        window = _FakeInstallWindow(
            getch_script=[curses.KEY_DOWN] * exit_index + [curses.KEY_ENTER]
        )
        final = app_module._main_loop(window, navigator, runtime=None, accent_attr=curses.A_BOLD, notice=notice, holder=holder)
        self.assertTrue(final.quit)


if __name__ == "__main__":
    unittest.main()
