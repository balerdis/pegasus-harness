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
class CliOption:
    """One CLI this release supports, found present on this machine.

    Carries exactly what the doc's `¿Dónde instalar Pegasus?` row shows —
    name, where it lives, how complete its support is — plus the `id` the
    engine needs to act on it. Built once, outside the pure layer, from a
    real probe of the machine; nothing here does that probing itself.
    """

    id: str
    display_name: str
    config_dir: str
    tier: str


@dataclass(frozen=True)
class InstallTarget:
    """Chosen a detected CLI to install into. Fetching its plan is a real
    engine call, so choosing this is not itself a new screen — it is a
    request for one, which is why it is not a member of `Screen`."""

    cli: CliOption
    command: str = "install"


@dataclass(frozen=True)
class InstallPlanScreen:
    """What `pegasus install --dry-run` would report, shown before anything
    is written. `report` is the exact document the flag produces — this
    screen renders it, it does not recompute it."""

    cli: CliOption
    report: dict


@dataclass(frozen=True)
class InstallResultScreen:
    """What the real install left behind — or, on failure, what was rolled
    back and what was not. Same report shape either way, the one `install
    --json` would print for the run that just happened."""

    cli: CliOption
    report: dict


@dataclass(frozen=True)
class Entry:
    """One line of a menu: what it says, and where choosing it leads."""

    label: str
    target: Union["Menu", Placeholder, Quit, InstallTarget]


@dataclass(frozen=True)
class Menu:
    """A vertical list of entries with one of them selected."""

    title: str
    entries: tuple[Entry, ...]


Screen = Union[Menu, Placeholder, InstallPlanScreen, InstallResultScreen]
"""Everything a :class:`Navigator` can have open. `Quit` is never open — it
ends the session the moment it is chosen, so it is a target, not a screen.
Neither is `InstallTarget`: choosing it asks for a screen, real engine work
away, rather than opening one directly."""

NOT_BUILT_YET = "This screen has not been built yet."


def install_menu(detections: tuple[CliOption, ...]) -> Union[Menu, Placeholder]:
    """The doc's `¿Dónde instalar Pegasus?` screen: one entry per detected
    CLI, selection of one. A machine with none detected gets the same
    placeholder shape every other unbuilt entry gets, worded for the actual
    reason there is nothing to choose from."""
    if not detections:
        return Placeholder("Install", "No supported CLI was detected on this machine.")
    return Menu(
        title="Where would you like to install Pegasus?",
        entries=tuple(
            Entry(f"{option.display_name:<18} {option.config_dir:<32} {option.tier}", InstallTarget(option))
            for option in detections
        ),
    )


def main_menu(detections: tuple[CliOption, ...] = ()) -> Menu:
    """The menu from the architecture doc, in the order it lists them."""
    return Menu(
        title=f"Pegasus Harness {pegasus.__version__}",
        entries=(
            Entry("Install", install_menu(detections)),
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
    def starting(detections: tuple[CliOption, ...] = ()) -> "Navigator":
        return Navigator(_stack=(main_menu(detections),), _cursors=(0,))

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
        if isinstance(screen, InstallResultScreen):
            # A finished install leaves the plan beneath it stale — it
            # described a preview of a disk that has since changed — so
            # acknowledging the result returns all the way to the main menu
            # rather than back into it.
            return replace(self, _stack=self._stack[:1], _cursors=self._cursors[:1]) if action in (
                Action.BACK, Action.CHOOSE
            ) else self
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
            if isinstance(target, InstallTarget):
                # Fetching its plan is real engine work, which only `session`
                # can do; handled here, this would open the request itself as
                # if it were a screen.
                return self
            return self.opened(target)
        if action is Action.BACK:
            return self._pop() if len(self._stack) > 1 else self
        return self

    def opened(self, screen: Screen) -> "Navigator":
        """Push a screen fetched from outside the pure layer — the plan or
        the result of an install — on top of the one that led to it. Public
        because whoever ran the engine call `session` holds no `Navigator`
        internals of its own to build the next state from."""
        return replace(self, _stack=self._stack + (screen,), _cursors=self._cursors + (0,))

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
