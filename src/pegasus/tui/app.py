"""The thin layer that actually touches a terminal.

Everything above this module — :mod:`~pegasus.tui.navigator` and
:mod:`~pegasus.tui.view` — is pure: given the same input it always returns
the same value, and nothing in it can fail for lack of a terminal. This
module is deliberately the opposite. It reads real keys and writes to a real
window, and it decides nothing on its own: `action_for` is a lookup table,
not a choice, and `draw` copies :class:`~pegasus.tui.view.Line` onto the
screen exactly as handed. No test constructs this module — a fake `curses`
window would only prove the fake behaves, never the real one — so the split
above is what carries the coverage instead.
"""
from __future__ import annotations

import curses

from pegasus.tui.navigator import Action, Navigator
from pegasus.tui.view import Line, render

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
}


def action_for(key: int) -> Action | None:
    """What a key code means, or ``None`` when it means nothing to this app."""
    return KEYS.get(key)


def draw(window, lines: tuple[Line, ...]) -> None:
    """Put the rendered lines on the window, within whatever room there is.

    How big the terminal is happens to be the one fact only this layer can
    know, and `addstr` raises rather than clipping, so a window shorter or
    narrower than the screen would end the program instead of showing less of
    it. Dropping the rows that do not fit and cutting the text that does not
    is not a decision about what to say — it is the surface being smaller
    than the thing drawn on it.
    """
    window.erase()
    height, width = window.getmaxyx()
    for row, line in enumerate(lines[:height]):
        attribute = curses.A_REVERSE if line.highlighted else curses.A_NORMAL
        # The last cell of the last row cannot be written to without the
        # cursor having to advance past it, which curses treats as an error.
        room = width - 1 if row == height - 1 else width
        window.addstr(row, 0, line.text[:room], attribute)
    window.refresh()


def run(window) -> None:
    curses.curs_set(0)
    window.keypad(True)
    navigator = Navigator.starting()
    draw(window, render(navigator.current, navigator.cursor))
    while not navigator.quit:
        action = action_for(window.getch())
        if action is None:
            continue
        navigator = navigator.handle(action)
        draw(window, render(navigator.current, navigator.cursor))


def main() -> None:
    curses.wrapper(run)
