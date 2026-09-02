"""The thin layer that actually touches a terminal.

Everything above this module — :mod:`~pegasus.tui.navigator` and
:mod:`~pegasus.tui.view` — is pure: given the same input it always returns
the same value, and nothing in it can fail for lack of a terminal. This
module is deliberately the opposite. It reads real keys and writes to a real
window, decides which colour or attribute a :class:`~pegasus.tui.view.Style`
becomes, and owns the worker thread an install runs on -- concurrency, the
clock, and curses itself all live here and nowhere else. `action_for` is a
lookup table, not a choice, and `draw` copies :class:`~pegasus.tui.view.Line`
onto the screen exactly as handed.

`draw` and the pure colour-fallback helper (`accent_choice`) are tested here
against a fake window and fake curses facts, since what they hand `addstr`
and how they choose a colour is real behaviour worth pinning down; the
interactive loop itself (`run`) is not constructed by any test -- proving it
needs a real terminal, and `test_tui_pty.py` drives the real binary through
one instead.
"""
from __future__ import annotations

import curses
import io
import threading
import time

from pegasus import cli
from pegasus.tui import session
from pegasus.tui.navigator import STARTUP_MESSAGE, Action, InstallPlanScreen, Navigator, busy_message_for
from pegasus.tui.view import Line, Style, render, render_busy, render_progress

KEYS: dict[int, Action] = {
    curses.KEY_UP: Action.MOVE_UP,
    ord("k"): Action.MOVE_UP,
    curses.KEY_DOWN: Action.MOVE_DOWN,
    ord("j"): Action.MOVE_DOWN,
    curses.KEY_ENTER: Action.CHOOSE,
    ord("\n"): Action.CHOOSE,
    ord("\r"): Action.CHOOSE,  # what Enter sends on a terminal in raw mode.
    27: Action.BACK,  # ESC has no curses constant of its own.
    ord("q"): Action.QUIT,
    ord("d"): Action.REMOVE,
    ord(" "): Action.TOGGLE,
}


def action_for(key: int) -> Action | None:
    """What a key code means, or ``None`` when it means nothing to this app."""
    return KEYS.get(key)


#: The installer's own colour, as a 256-colour index -- used when the
#: terminal actually offers that many.
ACCENT_COLOR_INDEX = 214
_ACCENT_PAIR = 1


def accent_choice(has_colors: bool, colors: int) -> tuple[str, int]:
    """What `_init_colors` should do to render `Style.ACCENT`, decided from
    plain facts about the terminal so the decision can be tested without one.

    ``("color", n)`` names a colour index `_init_colors` still has to turn
    into a pair; ``("attr", a)`` is a plain attribute needing no colour
    support at all, for a terminal that offers none.
    """
    if not has_colors:
        return ("attr", curses.A_BOLD)
    if colors >= 256:
        return ("color", ACCENT_COLOR_INDEX)
    return ("color", curses.COLOR_YELLOW)


def _init_colors() -> int:
    """The attribute to OR onto a `Style.ACCENT` span, decided defensively:
    `curses.has_colors()` may be false and `curses.COLORS` may be 8 or 16,
    and this must still leave the TUI legible either way. Called once, from
    `run`, since it is the one place actually touching a terminal.
    """
    kind, value = accent_choice(curses.has_colors(), curses.COLORS if curses.has_colors() else 0)
    if kind == "attr":
        return value
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(_ACCENT_PAIR, value, -1)
    except curses.error:
        # `accent_choice` decided from `has_colors()`/`COLORS` alone, but a
        # terminal whose terminfo claims colour support can still lack a
        # capability one of these calls needs -- falling back to the same
        # plain attribute the no-colour branch already uses is safer than
        # taking the whole TUI down before a single frame is drawn.
        return curses.A_BOLD
    return curses.color_pair(_ACCENT_PAIR)


_STYLE_ATTRS = {Style.NORMAL: curses.A_NORMAL, Style.DIM: curses.A_DIM}


def draw(window, lines: tuple[Line, ...], *, accent_attr: int = curses.A_BOLD) -> None:
    """Put the rendered lines on the window, within whatever room there is.

    How big the terminal is happens to be the one fact only this layer can
    know, and `addstr` raises rather than clipping, so a window shorter or
    narrower than the screen would end the program instead of showing less of
    it. Dropping the rows that do not fit and cutting the text that does not
    is not a decision about what to say — it is the surface being smaller
    than the thing drawn on it. Each `Span` on a line gets its own `addstr`
    call, so a row can mix emphases -- the wordmark's bicolor split, the
    progress bar's accent-coloured cells beside its plain-styled neighbours.
    """
    window.erase()
    height, width = window.getmaxyx()
    for row, line in enumerate(lines[:height]):
        base = curses.A_REVERSE if line.highlighted else curses.A_NORMAL
        # The last cell of the last row cannot be written to without the
        # cursor having to advance past it, which curses treats as an error.
        room = width - 1 if row == height - 1 else width
        column = 0
        for span in line.spans:
            if column >= room:
                break
            text = span.text[: room - column]
            if text:
                style_attr = accent_attr if span.style is Style.ACCENT else _STYLE_ATTRS.get(span.style, curses.A_NORMAL)
                window.addstr(row, column, text, base | style_attr)
            column += len(span.text)
    window.refresh()


#: How often the animation loop repaints while an install runs, in
#: milliseconds -- fast enough for the spinner to read as moving, not so
#: fast the loop burns a core waiting on a worker thread doing real disk and
#: network work.
PROGRESS_TICK_MS = 80


def _no_progress_yet() -> cli.Progress:
    """What the bar shows before the worker thread's first real `Progress`
    arrives -- a defensible zero rather than nothing to render at all, since
    some setup inside `cli.install` happens before the total is even known.
    A function rather than a module-level constant: `cli` imports this
    module before its own `Progress` class exists, so building one at import
    time here would be a circular reference to a name not defined yet.
    """
    return cli.Progress(done=0, total=1, phase="", unit="")


def _complete_progress() -> cli.Progress:
    """The frame drawn once the worker thread has returned -- a full bar
    regardless of what the last observed `Progress` said, so a finish that
    raced the animation loop's last read still ends the person's own view of
    it at 100%, matching the guarantee `cli.install` itself already keeps.
    """
    return cli.Progress(done=1, total=1, phase="", unit="")


class _ProgressHolder:
    """The one `Progress` value shared between the worker thread that calls
    `on_progress` and the main thread that reads it to repaint. It is an
    immutable value, so only the reference need be guarded -- a `Lock`
    around a plain attribute is all concurrency this needs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._progress = _no_progress_yet()

    def update(self, progress: cli.Progress) -> None:
        with self._lock:
            self._progress = progress

    def snapshot(self) -> cli.Progress:
        with self._lock:
            return self._progress


def _run_install(window, navigator: Navigator, runtime: cli.Runtime, accent_attr: int) -> Navigator:
    """Run the confirmed `InstallPlanScreen` for real, animating a frame
    every `PROGRESS_TICK_MS` instead of blocking on `cli.install` the way a
    synchronous `session.step` call would. The engine call itself runs on a
    worker thread -- `session.install_task` knows nothing about that thread,
    only how to build the call and the `Navigator` it produces; this
    function owns starting it, timing the repaint, and reading progress back
    off it through a lock.
    """
    message = busy_message_for(navigator.current, navigator.cursor, Action.CHOOSE)
    task = session.install_task(navigator, runtime, navigator.current)
    holder = _ProgressHolder()
    outcome: list[Navigator] = []
    failure: list[BaseException] = []

    def worker() -> None:
        # A thread's exception does not propagate to whoever joins it --
        # Python only hands it to `threading.excepthook`, which here would
        # print straight into a curses-controlled terminal and be lost, then
        # leave `outcome` empty so the main thread raises a meaningless
        # `IndexError` instead of whatever actually went wrong. Catching
        # `BaseException`, not `Exception`, is deliberate: crossing a thread
        # boundary is exactly the case where a blanket catch is correct,
        # since the alternative is losing the exception entirely -- and that
        # includes `KeyboardInterrupt`/`SystemExit`, which `cli.safe_report`
        # never sees because they are not among `COMMAND_ERRORS`.
        try:
            outcome.append(task(holder.update))
        except BaseException as exc:  # noqa: BLE001 - see comment above
            failure.append(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

    window.timeout(PROGRESS_TICK_MS)
    started = time.monotonic()
    try:
        while thread.is_alive():
            frame = int((time.monotonic() - started) * 1000 / PROGRESS_TICK_MS)
            _, width = window.getmaxyx()
            draw(window, render_progress(message, holder.snapshot(), frame, width=width), accent_attr=accent_attr)
            window.getch()  # -1 on timeout; either way, just a tick of the clock.
    except KeyboardInterrupt:
        # An install has no cancellation token, so this cannot abandon the
        # worker -- the `finally` below still joins it. All that changes
        # here is the frame on screen: without this the person sees the last
        # animation frame freeze for however long the install has left,
        # which reads as a hang rather than "still working, please wait".
        draw(window, render_busy("Finishing the install — it cannot be safely interrupted…"), accent_attr=accent_attr)
        raise
    finally:
        # The thread is a daemon and `join()` only ran on the happy path
        # before this fix, so a `Ctrl+C` unwound straight out of this
        # function -- `curses.wrapper` then restores the terminal, making it
        # look like the install stopped, while the worker keeps writing the
        # journal, artifacts and snapshot completely unsupervised, and a
        # daemon thread killed at process exit skips its `finally` blocks
        # entirely, which can tear a write. There is no safe way to cancel
        # an in-flight install, so waiting for it here -- even while a
        # `KeyboardInterrupt` is unwinding -- is the correct behaviour, not
        # a missed chance to cancel.
        thread.join()
        window.timeout(-1)
        curses.flushinp()  # discard keys mashed during the install -- see `run`.

    if failure:
        raise failure[0]

    frame = int((time.monotonic() - started) * 1000 / PROGRESS_TICK_MS)
    _, width = window.getmaxyx()
    draw(window, render_progress(message, _complete_progress(), frame, width=width), accent_attr=accent_attr)
    return outcome[0]


def _render_current(window, navigator: Navigator) -> tuple[Line, ...]:
    """The current screen, rendered for the room this window actually has --
    how big the terminal is happens to be the one fact only this layer can
    know, per `draw`'s own docstring, so `render` never reads it any other
    way."""
    _, width = window.getmaxyx()
    return render(navigator.current, navigator.cursor, width=width)


def run(window, runtime: cli.Runtime) -> None:
    curses.curs_set(0)
    window.keypad(True)
    accent_attr = _init_colors()
    draw(window, render_busy(STARTUP_MESSAGE), accent_attr=accent_attr)
    navigator = Navigator.starting(session.detect_clis(runtime), session.detect_installed(runtime))
    draw(window, _render_current(window, navigator), accent_attr=accent_attr)
    while not navigator.quit:
        action = action_for(window.getch())
        if action is None:
            continue
        if action is Action.CHOOSE and isinstance(navigator.current, InstallPlanScreen):
            navigator = _run_install(window, navigator, runtime, accent_attr)
            draw(window, _render_current(window, navigator), accent_attr=accent_attr)
            continue
        message = busy_message_for(navigator.current, navigator.cursor, action)
        if message is not None:
            draw(window, render_busy(message), accent_attr=accent_attr)
        navigator = session.step(navigator, runtime, action)
        draw(window, _render_current(window, navigator), accent_attr=accent_attr)


def main() -> None:
    runtime = cli.default_runtime(io.StringIO())
    curses.wrapper(lambda window: run(window, runtime))
