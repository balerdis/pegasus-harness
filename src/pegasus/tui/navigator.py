"""What is on screen right now, and what a key does next.

Nothing in this module knows a terminal exists. A screen is a plain value —
a :class:`Menu` or a :class:`Placeholder` — and a :class:`Navigator` is the
sequence of screens a person has walked into plus the cursor left on each
one. Handing it an :class:`Action` returns the next `Navigator`; nothing here
reads a key or draws a line. That split is what lets every scenario below run
without a terminal at all: there is nothing here for one to be needed by.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, auto
from typing import Union

import pegasus


class Action(Enum):
    """Every thing a key can mean, independent of which key spelled it."""

    MOVE_UP = auto()
    MOVE_DOWN = auto()
    CHOOSE = auto()
    BACK = auto()
    QUIT = auto()


class Quit:
    """The target of the one entry that ends the session rather than opening a screen."""


QUIT = Quit()


@dataclass(frozen=True)
class Placeholder:
    """A screen the doc names but this change does not build.

    Choosing it says so plainly instead of opening something that only looks
    finished — ``note`` is shown to the person, never left implicit.
    """

    title: str
    note: str


@dataclass(frozen=True)
class Entry:
    """One line of a menu: what it says, and where choosing it leads."""

    label: str
    target: Union["Menu", Placeholder, Quit]


@dataclass(frozen=True)
class Menu:
    """A vertical list of entries with one of them selected."""

    title: str
    entries: tuple[Entry, ...]


Screen = Union[Menu, Placeholder]
"""Everything a :class:`Navigator` can have open. `Quit` is never open — it
ends the session the moment it is chosen, so it is a target, not a screen."""

NOT_BUILT_YET = "This screen has not been built yet."


def main_menu() -> Menu:
    """The menu from the architecture doc, in the order it lists them."""
    return Menu(
        title=f"Pegasus Harness {pegasus.__version__}",
        entries=(
            Entry("Install", Placeholder("Install", NOT_BUILT_YET)),
            Entry("Configure models", Placeholder("Configure models", NOT_BUILT_YET)),
            Entry("Status and diagnostics", Placeholder("Status and diagnostics", NOT_BUILT_YET)),
            Entry("Uninstall", Placeholder("Uninstall", NOT_BUILT_YET)),
            Entry("Exit", QUIT),
        ),
    )


@dataclass(frozen=True)
class Navigator:
    """The screens a person has walked into, most recent last, and the cursor
    left on each one.

    Immutable: every :meth:`handle` call returns a new `Navigator` rather than
    changing this one, so a test can hold onto a step and compare it against a
    later one without a snapshot of its own.
    """

    _stack: tuple[Screen, ...]
    _cursors: tuple[int, ...]
    quit: bool = False

    @staticmethod
    def starting() -> "Navigator":
        return Navigator(_stack=(main_menu(),), _cursors=(0,))

    @property
    def current(self) -> Screen:
        return self._stack[-1]

    @property
    def cursor(self) -> int:
        return self._cursors[-1]

    def handle(self, action: Action) -> "Navigator":
        if self.quit:
            return self
        if action is Action.QUIT:
            return replace(self, quit=True)
        screen = self.current
        if isinstance(screen, Menu):
            return self._handle_on_menu(screen, action)
        return self._handle_on_placeholder(action)

    def _handle_on_menu(self, screen: Menu, action: Action) -> "Navigator":
        count = len(screen.entries)
        if action is Action.MOVE_DOWN:
            return self._with_cursor((self.cursor + 1) % count)
        if action is Action.MOVE_UP:
            return self._with_cursor((self.cursor - 1) % count)
        if action is Action.CHOOSE:
            target = screen.entries[self.cursor].target
            if isinstance(target, Quit):
                return replace(self, quit=True)
            return replace(self, _stack=self._stack + (target,), _cursors=self._cursors + (0,))
        if action is Action.BACK:
            return self._pop() if len(self._stack) > 1 else self
        return self

    def _handle_on_placeholder(self, action: Action) -> "Navigator":
        # There is nothing to do here yet but leave: both keys acknowledge the
        # screen and return to whatever opened it.
        if action in (Action.BACK, Action.CHOOSE):
            return self._pop()
        return self

    def _pop(self) -> "Navigator":
        return replace(self, _stack=self._stack[:-1], _cursors=self._cursors[:-1])

    def _with_cursor(self, index: int) -> "Navigator":
        return replace(self, _cursors=self._cursors[:-1] + (index,))
