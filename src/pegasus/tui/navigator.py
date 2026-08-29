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
    REMOVE = auto()


class Quit:
    """The target of the one entry that ends the session rather than opening a screen."""


QUIT = Quit()


class Cancel:
    """The target of an entry that only closes the screen it is on — a
    confirmation's "no": opens nothing, ends nothing."""


CANCEL = Cancel()


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
class StatusRequest:
    """The main menu's `Status and diagnostics` entry: like `InstallTarget`,
    running `doctor` for real is `session`'s job, not a screen of its own."""

    command: str = "doctor"


@dataclass(frozen=True)
class StatusScreen:
    """What `doctor` reports, rendered as-is — the exact document `doctor
    --json` would print. Its one action asks `session` to list the
    generations `restore` could still read: where this release reaches
    `restore` from, since someone here has already looked at the state."""

    report: dict


@dataclass(frozen=True)
class UninstallTarget:
    """Chosen a CLI to take Pegasus back out of — like `InstallTarget`, this
    only asks `session` for the preview screen."""

    cli: CliOption
    command: str = "uninstall"


@dataclass(frozen=True)
class UninstallConfirm:
    """The one entry on an uninstall preview that actually calls
    `cli.uninstall`. Kept apart from `UninstallTarget` so the preview's own
    Cancel/Confirm can never be confused with the outer choice."""

    cli: CliOption
    command: str = "uninstall"


@dataclass(frozen=True)
class UninstallResultScreen:
    """What the real uninstall left behind — the report `uninstall --json`
    would print for the run that just happened."""

    cli: CliOption
    report: dict


@dataclass(frozen=True)
class RestoreTarget:
    """Chosen a generation to look at. What going back to it would touch
    lives in its manifest, so — like `InstallTarget` — this only asks
    `session` for the preview screen."""

    generation: int
    command: str = "restore"


@dataclass(frozen=True)
class RestoreConfirm:
    """The one entry on a restore preview that actually calls `cli.restore`,
    kept apart from `RestoreTarget` the same way `UninstallConfirm` is."""

    generation: int
    command: str = "restore"


@dataclass(frozen=True)
class RestoreResultScreen:
    """What the real restore put back — the report `restore --json` would
    print for the run that just happened."""

    report: dict


@dataclass(frozen=True)
class ModelOption:
    """One model a provider offers, pure enough for the wizard below to
    narrow on without ever touching `core.model_catalog` itself -- the same
    reason `CliOption` exists apart from `Detection`."""

    id: str
    reasoning: bool


@dataclass(frozen=True)
class ProviderOption:
    """A provider the machine can reach, and only the models worth offering."""

    id: str
    models: tuple[ModelOption, ...] = ()


@dataclass(frozen=True)
class AgentRow:
    """One row of the assignment step: an agent that accepts a model, and what
    it currently has -- `None` when it has nothing, which is the ordinary
    starting state every agent ships in, not a problem to flag."""

    agent: str
    current: str | None = None


@dataclass(frozen=True)
class ModelsTarget:
    """Chosen a CLI to configure models for. Fetching its model catalog and
    current assignments is real engine work, same reasoning as `InstallTarget`."""

    cli: CliOption
    command: str = "models"


#: The reasoning-effort choices this screen offers a model that declares
#: `reasoning`. The catalog itself only ever says whether a model *has*
#: variants, not what they are called, so this is the one place the walk
#: names them -- kept short and provider-agnostic on purpose, since asking
#: for anything finer than the flags' own free-form `--effort` string would
#: be inventing a precision the engine does not have either.
EFFORT_OPTIONS: tuple[str, ...] = ("low", "medium", "high")


@dataclass(frozen=True)
class ModelsScreen:
    """The doc's four-step walk -- CLI, already chosen to reach here, then
    agent, provider, model, and an optional effort -- held as one screen
    whose content changes with how much of it is filled in, rather than as
    four screens stacked on top of each other.

    `providers` and `rows` are fetched once, when the CLI is chosen; every
    step after that only narrows them, which is why choosing an agent, a
    provider, or a reasoning model is pure and handled right here, while
    choosing a plain model, an effort, or removing an assignment needs a real
    write and is left to `session` to notice and act on -- the same split
    `_ENGINE_TARGETS` already draws for every other screen.
    """

    cli: CliOption
    providers: tuple[ProviderOption, ...]
    rows: tuple[AgentRow, ...]
    agent: str | None = None
    provider_id: str | None = None
    model_id: str | None = None


def _models_provider(screen: ModelsScreen) -> ProviderOption:
    return next(provider for provider in screen.providers if provider.id == screen.provider_id)


def _models_step_count(screen: ModelsScreen) -> int:
    """How many choices the current step offers, for cursor wrapping."""
    if screen.model_id is not None:
        return len(EFFORT_OPTIONS)
    if screen.provider_id is not None:
        return len(_models_provider(screen).models)
    if screen.agent is not None:
        return len(screen.providers)
    return len(screen.rows)


@dataclass(frozen=True)
class Entry:
    """One line of a menu: what it says, and where choosing it leads."""

    label: str
    target: Union[
        "Menu",
        Placeholder,
        Quit,
        Cancel,
        InstallTarget,
        StatusRequest,
        UninstallTarget,
        UninstallConfirm,
        RestoreTarget,
        RestoreConfirm,
        ModelsTarget,
    ]


@dataclass(frozen=True)
class Menu:
    """A vertical list of entries with one of them selected. `preface` is
    read-only context shown above the entries — never itself selectable —
    empty by default, so a menu that predates it renders exactly as before.
    """

    title: str
    entries: tuple[Entry, ...]
    preface: tuple[str, ...] = ()


Screen = Union[
    Menu,
    Placeholder,
    InstallPlanScreen,
    InstallResultScreen,
    StatusScreen,
    UninstallResultScreen,
    RestoreResultScreen,
    ModelsScreen,
]
"""Everything a :class:`Navigator` can have open. `Quit` and `Cancel` are
never open — each ends the current moment (session or screen) the instant it
is chosen. Neither is `InstallTarget` or any of its siblings below: choosing
one asks for a screen, real engine work away, not open one directly."""

#: Targets naming real engine work `Navigator` cannot do — chosen from a
#: menu, each is a no-op here; `session.step` recognizes the type and acts.
_ENGINE_TARGETS = (
    InstallTarget, StatusRequest, UninstallTarget, UninstallConfirm, RestoreTarget, RestoreConfirm, ModelsTarget,
)


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


def uninstall_menu(installed: tuple[CliOption, ...]) -> Union[Menu, Placeholder]:
    """One entry per CLI Pegasus is recorded as installed into, regardless of
    whether it is still detected present — uninstalling never needs that."""
    if not installed:
        return Placeholder("Uninstall", "Pegasus is not recorded as installed in any CLI on this machine.")
    return Menu(
        title="Take Pegasus back out of which CLI?",
        entries=tuple(
            Entry(f"{option.display_name:<18} {option.config_dir:<32} {option.tier}", UninstallTarget(option))
            for option in installed
        ),
    )


def restore_menu(generations: tuple[int, ...]) -> Union[Menu, Placeholder]:
    """One entry per generation `restore` could still read, most recent
    first; nothing captured yet is the same placeholder shape as elsewhere."""
    if not generations:
        return Placeholder("Restore", "There is no snapshot generation to restore.")
    return Menu(
        title="Restore which generation?",
        entries=tuple(Entry(f"Generation {generation}", RestoreTarget(generation)) for generation in generations),
    )


def models_menu(detections: tuple[CliOption, ...]) -> Union[Menu, Placeholder]:
    """One entry per detected CLI, the same set `install_menu` offers: a CLI
    that is not present has no model catalog this release can read either."""
    if not detections:
        return Placeholder("Configure models", "No supported CLI was detected on this machine.")
    return Menu(
        title="Configure models for which CLI?",
        entries=tuple(
            Entry(f"{option.display_name:<18} {option.config_dir:<32} {option.tier}", ModelsTarget(option))
            for option in detections
        ),
    )


def main_menu(detections: tuple[CliOption, ...] = (), installed: tuple[CliOption, ...] = ()) -> Menu:
    """The menu from the architecture doc, in the order it lists them.

    `restore` has no entry of its own here on purpose: the doc's menu is
    five entries, Install through Exit, and a sixth for a command the doc
    never lists would break that parity for no reason `restore` itself
    needs — it is reached from the status screen instead, see
    :class:`StatusScreen`.
    """
    return Menu(
        title=f"Pegasus Harness {pegasus.__version__}",
        entries=(
            Entry("Install", install_menu(detections)),
            Entry("Configure models", models_menu(detections)),
            Entry("Status and diagnostics", StatusRequest()),
            Entry("Uninstall", uninstall_menu(installed)),
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
    def starting(detections: tuple[CliOption, ...] = (), installed: tuple[CliOption, ...] = ()) -> "Navigator":
        return Navigator(_stack=(main_menu(detections, installed),), _cursors=(0,))

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
        if isinstance(screen, ModelsScreen):
            return self._handle_on_models(screen, action)
        if isinstance(screen, (InstallResultScreen, UninstallResultScreen, RestoreResultScreen)):
            # A finished install, uninstall, or restore leaves whatever led to
            # it stale — each described a disk that has since changed — so
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
            if isinstance(target, Cancel):
                return self._pop()
            if isinstance(target, _ENGINE_TARGETS):
                # Fetching what it needs is real engine work, which only
                # `session` can do; handled here, this would open the request
                # itself as if it were a screen.
                return self
            return self.opened(target)
        if action is Action.BACK:
            return self._pop() if len(self._stack) > 1 else self
        return self

    def _handle_on_models(self, screen: ModelsScreen, action: Action) -> "Navigator":
        count = _models_step_count(screen)
        if action is Action.MOVE_DOWN:
            return self._with_cursor((self.cursor + 1) % count) if count else self
        if action is Action.MOVE_UP:
            return self._with_cursor((self.cursor - 1) % count) if count else self
        if action is Action.BACK:
            return self._back_on_models(screen)
        if action is Action.CHOOSE:
            return self._choose_on_models(screen)
        # `Action.REMOVE`, and a `CHOOSE` that lands on a plain model or an
        # effort, are real writes only `session.step` can make; here, exactly
        # like an `_ENGINE_TARGETS` member, they are a no-op.
        return self

    def _back_on_models(self, screen: ModelsScreen) -> "Navigator":
        """Clear the last field the walk filled in, one step at a time; with
        nothing left to clear, leave the wizard the way a `Menu`'s `BACK`
        leaves any other screen."""
        if screen.model_id is not None:
            return self.replaced(replace(screen, model_id=None))
        if screen.provider_id is not None:
            return self.replaced(replace(screen, provider_id=None))
        if screen.agent is not None:
            return self.replaced(replace(screen, agent=None))
        return self._pop()

    def _choose_on_models(self, screen: ModelsScreen) -> "Navigator":
        if screen.agent is None:
            if not screen.rows:
                return self
            return self.replaced(replace(screen, agent=screen.rows[self.cursor].agent))
        if screen.provider_id is None:
            if not screen.providers:
                return self
            return self.replaced(replace(screen, provider_id=screen.providers[self.cursor].id))
        if screen.model_id is None:
            provider = _models_provider(screen)
            if not provider.models:
                return self
            chosen = provider.models[self.cursor]
            if chosen.reasoning:
                return self.replaced(replace(screen, model_id=chosen.id))
            return self  # a plain model: `session.step` commits it.
        return self  # an effort: `session.step` commits it.

    def replaced(self, screen: Screen) -> "Navigator":
        """Swap the screen on top for a freshly computed one at the same
        depth, cursor reset. Used both by the models wizard's own pure
        narrowing above and by `session`, after a write that leaves the
        screen it was made from stale without leaving the walk that reached
        it — unlike a finished install, uninstall, or restore, which leaves
        everything below stale and returns to the main menu instead."""
        return replace(self, _stack=self._stack[:-1] + (screen,), _cursors=self._cursors[:-1] + (0,))

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
