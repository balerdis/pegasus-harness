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
from datetime import datetime
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
    TOGGLE = auto()


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
class McpOption:
    """One mcp server this release can install, pure enough for the
    selection step below to toggle without ever touching `core.content`
    itself — the same reason `CliOption` exists apart from a real `Detection`.
    `description` is the descriptor's own `description` field, verbatim: the
    one sentence a person needs to decide whether they want it."""

    id: str
    description: str


@dataclass(frozen=True)
class McpSelectionScreen:
    """The step between choosing a CLI and seeing its plan: which of the
    servers this release ships should be part of it.

    `chosen` starts as whatever this CLI's journal already records as
    installed — the safe default, since leaving every row exactly as found
    and moving straight to Continue then reproduces the machine's current
    state rather than silently retiring everything, the same as calling
    `install` with no `--mcp` at all when nothing was ever installed through
    it. The row after the last server is Continue itself: reaching it and
    choosing it is real engine work — fetching the plan for exactly the
    servers checked so far — so `Navigator` leaves it a no-op, the same
    reasoning `_ENGINE_TARGETS` already follows for every other request only
    `session` can act on; toggling a server above it, unlike that request,
    is pure and handled right here.
    """

    cli: CliOption
    options: tuple[McpOption, ...]
    chosen: tuple[str, ...]


@dataclass(frozen=True)
class InstallPlanScreen:
    """What `pegasus install --dry-run` would report, shown before anything
    is written. `report` is the exact document the flag produces — this
    screen renders it, it does not recompute it. `mcp` is the selection that
    produced it, carried forward so confirming this plan installs exactly
    what it previewed rather than falling back to naming none at all.

    `command` is `"install"` or `"update"` -- the two flows share this screen
    and `InstallResultScreen` rather than each carrying its own, since a
    preview and its result mean the same thing either way: what confirming
    it would place, or did place. It is what `view` and `busy_message_for`
    read to say "Update" instead of "Install" without either screen needing
    a second, near-identical twin. Defaults to `"install"` so every plan
    built before this field existed still renders exactly as it always did.
    """

    cli: CliOption
    report: dict
    mcp: tuple[str, ...] = ()
    command: str = "install"


@dataclass(frozen=True)
class InstallResultScreen:
    """What the real install left behind — or, on failure, what was rolled
    back and what was not. Same report shape either way, the one `install
    --json` would print for the run that just happened.

    `command` carries the same distinction `InstallPlanScreen.command` does,
    for the same reason -- an update's result is not an install's, even
    though both are `cli.safe_report`'s document for whichever one ran."""

    cli: CliOption
    report: dict
    command: str = "install"


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
class UpdateTarget:
    """Chosen a CLI to reapply its own recorded selection into -- like
    `InstallTarget`, fetching the preview is real engine work, so choosing
    this is only a request for one, not a screen of its own."""

    cli: CliOption
    command: str = "update"


@dataclass(frozen=True)
class UpgradeTarget:
    """The main menu's `Upgrade` entry: replace the running `pegasus`
    binary itself, not any CLI's installation -- unlike every other target
    here, this carries no `CliOption` at all, because `pegasus upgrade`
    takes no `--cli`. Fetching the plan (checking the newest published
    release, and whether the destination is writable) is real engine work,
    so choosing this is only a request for one, the same as `InstallTarget`."""

    command: str = "upgrade"


#: The `CliOption` `UpgradeTarget`'s own preview and result screens carry as
#: their `cli` field -- `InstallPlanScreen` and `InstallResultScreen` are
#: shared across every flow that previews-then-confirms a real engine call,
#: and both need one to render a "<Verb> · <name>" heading and to feed
#: `busy_message_for`. `Upgrade` has no CLI of its own to name, so this
#: stands in for "the program itself" -- its `id` is never read by anything
#: `upgrade` calls (`cli.upgrade` takes no CLI id at all), only its
#: `display_name`, by `view` and by `busy_message_for`.
PEGASUS_PROGRAM = CliOption(id="pegasus", display_name="Pegasus", config_dir="", tier="full")


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
class GenerationSummary:
    """What `session` learned about one generation by actually reading its
    manifest, carried here for `restore_menu` to turn into a label. A bare
    ordinal answers "which folder is this", not "which one do I want" -- a
    person recognises what they did at 4am, not what "Generation 3" means,
    so the fact this screen exists to show is *when* the snapshot was taken.

    `files_restored` and `paths_cleared` split `Manifest.entries` the same
    way `Entry.existed` already splits it: the first is bytes this
    generation would put back, the second is addresses it would empty again
    (see `core.snapshot.Entry`). They mean different things to someone about
    to press enter, so neither is folded into the other.

    There is deliberately no field for a Pegasus release: `Manifest` never
    records one (see `core.snapshot.Manifest`), and inventing one here would
    put a fact on screen that nothing on disk actually backs.
    """

    generation: int
    taken_at: str
    files_restored: int
    paths_cleared: int


def readable_timestamp(taken_at: str) -> str:
    """`taken_at` rendered the way a person reads a clock, or itself
    unchanged when it will not parse.

    Public because two screens in the restore flow show the same fact: this
    menu's rows and, one `CHOOSE` later, the confirm screen `session` builds.
    They have to agree, and they only agree by construction if both spell the
    moment with the same function.

    A manifest's `taken_at` is a string written to a file on disk, by
    whichever version wrote it -- this screen must not assume that string
    always parses just because every version so far has produced one that
    does. The restore screen is the recovery path; a corrupt timestamp
    turning it unreachable would be strictly worse than showing the raw
    value and letting the rest of the row still say what it can.
    """
    try:
        parsed = datetime.fromisoformat(taken_at)
    except (TypeError, ValueError):
        return taken_at
    return f"{parsed.day} {parsed.strftime('%b %Y, %H:%M')}"


def _touch_summary(files_restored: int, paths_cleared: int) -> str:
    """`files_restored` and `paths_cleared` as the phrase a label ends with,
    in the future tense on purpose.

    This phrase sits on a row nobody has confirmed yet, one `CHOOSE` away
    from a preview screen and two from any write at all. A past participle
    there would read as a receipt -- "101 files restored" against a
    generation a person is still deciding about claims the restore already
    happened, which is the one thing this screen must never imply. Same line
    `core.planner` already draws for its own reporting: naming a completed
    action is a claim, and a claim has to be true when it is made.
    """
    parts = []
    if files_restored:
        parts.append(f"{files_restored} file{'' if files_restored == 1 else 's'} to put back")
    if paths_cleared:
        parts.append(f"{paths_cleared} to remove")
    return ", ".join(parts) if parts else "nothing captured"


def _generation_label(summary: GenerationSummary, *, most_recent: bool) -> str:
    when = readable_timestamp(summary.taken_at)
    marker = " (most recent)" if most_recent else ""
    touched = _touch_summary(summary.files_restored, summary.paths_cleared)
    return f"Generation {summary.generation} — {when}{marker} · {touched}"


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


def _toggled(screen: McpSelectionScreen, index: int) -> McpSelectionScreen:
    """`screen` with the server at `index` moved in or out of `chosen`."""
    server_id = screen.options[index].id
    chosen = (
        tuple(name for name in screen.chosen if name != server_id)
        if server_id in screen.chosen
        else screen.chosen + (server_id,)
    )
    return replace(screen, chosen=chosen)


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
        UpdateTarget,
        UpgradeTarget,
    ]


@dataclass(frozen=True)
class Menu:
    """A vertical list of entries with one of them selected. `preface` is
    read-only context shown above the entries — never itself selectable —
    empty by default, so a menu that predates it renders exactly as before.

    `installed` and `version` exist for exactly one screen, the main menu:
    whether Pegasus is recorded as installed in at least one CLI is already
    known at the boundary that builds this (`session.detect_installed`), and
    handing it over as data here is what lets `view` choose the wordmark
    over the plain title without ever probing the filesystem itself to find
    that fact out. `False` and `""` by default, so a menu that predates
    either field keeps rendering exactly as it always did.
    """

    title: str
    entries: tuple[Entry, ...]
    preface: tuple[str, ...] = ()
    installed: bool = False
    version: str = ""


Screen = Union[
    Menu,
    Placeholder,
    McpSelectionScreen,
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
    UpdateTarget, UpgradeTarget,
)

#: What to say before probing every adapter, the one engine call `run` makes
#: before the first frame exists to draw anything else. Named here, next to
#: every other sentence this module hands out for the same reason, rather
#: than left for `app` to invent on its own.
STARTUP_MESSAGE = "Detecting installed CLIs…"


def busy_message_for(screen: Screen, cursor: int, action: Action) -> str | None:
    """What to show before `action`, taken on `screen` at `cursor`, runs a
    real engine call — or `None` when it is ordinary navigation that costs
    nothing to show nothing extra for.

    This mirrors, screen by screen, exactly which choice `Navigator` itself
    leaves a no-op for `session.step` to catch: `_ENGINE_TARGETS` for a menu
    entry, and the same three screens whose own docstrings already explain
    why one particular row or step on them is real work rather than a pure
    narrowing — `McpSelectionScreen`'s Continue row, `ModelsScreen`'s three
    writes, and `InstallPlanScreen`'s only action. Keeping the two lists in
    lockstep is a matter of discipline, not the type system: a target that
    became real work in one without the other would either lie about being
    idle or freeze without a word, which is the defect this exists to close.
    """
    if isinstance(screen, Menu):
        return _busy_message_for_menu(screen, cursor, action)
    if isinstance(screen, McpSelectionScreen):
        return _busy_message_for_mcp_selection(screen, cursor, action)
    if isinstance(screen, InstallPlanScreen):
        if action is not Action.CHOOSE:
            return None
        if screen.command == "update":
            verb = "Updating"
        elif screen.command == "upgrade":
            verb = "Downloading and verifying"
        else:
            verb = "Installing into"
        return f"{verb} {screen.cli.display_name}…"
    if isinstance(screen, StatusScreen):
        return "Reading snapshot generations…" if action is Action.CHOOSE else None
    if isinstance(screen, ModelsScreen):
        return _busy_message_for_models(screen, cursor, action)
    return None


def _busy_message_for_menu(screen: Menu, cursor: int, action: Action) -> str | None:
    if action is not Action.CHOOSE:
        return None
    target = screen.entries[cursor].target
    if isinstance(target, InstallTarget):
        return f"Fetching install options for {target.cli.display_name}…"
    if isinstance(target, StatusRequest):
        return "Running diagnostics…"
    if isinstance(target, UninstallTarget):
        return f"Reading what {target.cli.display_name} has installed…"
    if isinstance(target, UninstallConfirm):
        return f"Removing Pegasus from {target.cli.display_name}…"
    if isinstance(target, RestoreTarget):
        return f"Reading generation {target.generation}…"
    if isinstance(target, RestoreConfirm):
        return f"Restoring generation {target.generation}…"
    if isinstance(target, ModelsTarget):
        return f"Reading the model catalog for {target.cli.display_name}…"
    if isinstance(target, UpdateTarget):
        return f"Checking the update plan for {target.cli.display_name}…"
    if isinstance(target, UpgradeTarget):
        return "Checking for a newer release…"
    return None


def _busy_message_for_mcp_selection(screen: McpSelectionScreen, cursor: int, action: Action) -> str | None:
    if action is Action.CHOOSE and cursor == len(screen.options):
        return f"Fetching the install plan for {screen.cli.display_name}…"
    return None


def _busy_message_for_models(screen: ModelsScreen, cursor: int, action: Action) -> str | None:
    if action is Action.REMOVE and screen.agent is None and screen.rows:
        return f"Removing the model assigned to {screen.rows[cursor].agent}…"
    if action is not Action.CHOOSE:
        return None
    if screen.model_id is not None:
        return f"Assigning a model to {screen.agent}…"
    if screen.provider_id is not None:
        provider = _models_provider(screen)
        if provider.models and not provider.models[cursor].reasoning:
            return f"Assigning a model to {screen.agent}…"
    return None


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


#: The restore screen's own explanation of what it is choosing between --
#: shown above every menu it builds, since the screen exists precisely
#: because a bare "Generation 4" answers "which folder" and not "which one do
#: I want" (see `GenerationSummary`).
_RESTORE_PREFACE = (
    "A generation is the state of the files Pegasus owns, saved just before "
    "a write overwrote them. Restoring puts that state back.",
)


def _skipped_note(skipped: tuple[int, ...]) -> str:
    """The generations this screen had to leave out, named by number.

    Named rather than counted, because a count cannot be put into a sentence
    without implying something about *which* ones they were. The count this
    replaced said "N older generations could not be read", and "older" was
    false in the one case that matters most: when the folder that will not
    parse is the newest one, a person told an ancient snapshot broke stops
    looking, while what actually broke is the generation they came here for.
    The number is a fact already in hand, so it goes on screen unadorned.
    """
    numbers = [str(generation) for generation in skipped]
    if len(numbers) == 1:
        return f"Generation {numbers[0]} could not be read and is left off this list."
    listed = ", ".join(numbers[:-1]) + f" and {numbers[-1]}"
    return f"Generations {listed} could not be read and are left off this list."


def restore_menu(summaries: tuple[GenerationSummary, ...], *, skipped: tuple[int, ...] = ()) -> Union[Menu, Placeholder]:
    """One entry per generation `restore` could still read, most recent
    first, labelled with when it was taken and what it would touch rather
    than the bare ordinal `RestoreTarget` still carries underneath --
    nothing captured yet is the same placeholder shape as elsewhere.

    `summaries` must already be ordered most-recent-first, the same order
    `session` has always supplied. `skipped` names the generations `session`
    could not read at all -- `readable_generations` only checks that a
    manifest file exists, not that it parses (see `ports.snapshot_store`'s
    module docstring), so `session.read`-ing every one of them for this
    screen can now find one that is present but broken. Such a generation is
    left out of `summaries` entirely rather than offered as a choice that
    would only fail the moment it was picked, and `_skipped_note` is how the
    screen still accounts for it instead of just being silently shorter.

    The "(most recent)" marker is withheld when anything in `skipped` is
    newer than `summaries[0]`. The marker exists to point at the last thing
    that happened, and when the last thing that happened is precisely the
    generation this screen cannot open, moving the marker down to the
    runner-up would answer the question a person came with -- "where is the
    state from just before I broke it?" -- with the wrong snapshot.
    """
    if not summaries:
        return Placeholder("Restore", "There is no snapshot generation to restore.")
    preface = _RESTORE_PREFACE + ((_skipped_note(skipped),) if skipped else ())
    newest_is_readable = not any(generation > summaries[0].generation for generation in skipped)
    return Menu(
        title="Restore which generation?",
        preface=preface,
        entries=tuple(
            Entry(
                _generation_label(summary, most_recent=index == 0 and newest_is_readable),
                RestoreTarget(summary.generation),
            )
            for index, summary in enumerate(summaries)
        ),
    )


def update_menu(installed: tuple[CliOption, ...]) -> Union[Menu, Placeholder]:
    """One entry per CLI Pegasus is recorded as installed into -- the same
    set `uninstall_menu` offers, for the same reason: `update` refuses a CLI
    with nothing installed exactly the way `uninstall` does, and offering a
    choice that can only fail is worse than not offering it."""
    if not installed:
        return Placeholder("Update", "Pegasus is not recorded as installed in any CLI on this machine.")
    return Menu(
        title="Reapply Pegasus's recorded selection into which CLI?",
        entries=tuple(
            Entry(f"{option.display_name:<18} {option.config_dir:<32} {option.tier}", UpdateTarget(option))
            for option in installed
        ),
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


def _parse_version(text: str | None) -> tuple[int, ...] | None:
    """`text` split on `.` into plain ints, or `None` for anything that does
    not look exactly like that -- comparing versions must never guess an
    ordering from a string that failed to parse."""
    if not text:
        return None
    parts = text.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _is_older(candidate: str | None, than: str | None) -> bool:
    """Whether `candidate` sorts strictly before `than`, numerically.

    `False` whenever either side does not parse -- never an exception, and
    never a guess. This is the one place both halves of `UpdateNotice`
    (local and remote) decide "is this actually behind", so the same
    defensiveness protects both.
    """
    left = _parse_version(candidate)
    right = _parse_version(than)
    if left is None or right is None:
        return False
    return left < right


@dataclass(frozen=True)
class BehindInstall:
    """One installed CLI's own recorded version, already fetched from its
    journal entry by `session` -- not yet known to actually be behind
    `UpdateNotice.running`; `update_notice_lines` still checks that itself,
    the same defensive way it always has, so a missing, malformed, equal, or
    newer `recorded` produces silence about that CLI rather than a wrong
    claim.

    `remedy_command` is engine knowledge decided outside this pure layer:
    whether `cli.update` would actually reapply this installation, or refuse
    it over a bound mcp server key it was never given. `None` means `Update`
    works; otherwise it is the exact one-time command to run instead, so the
    notice can never recommend an action the engine itself will refuse --
    `navigator` never probes an installation to find this out, it only
    renders what `session` already decided.
    """

    display_name: str
    recorded: str | None
    remedy_command: str | None = None


#: The remedy line for a newer *published* release -- the remote half of
#: `UpdateNotice`. `Update` only ever reapplies an installation's own
#: recorded selection; it cannot fetch a new binary, so its remedy can never
#: name `Update` the way the local half's does. It names `Upgrade` instead --
#: the menu entry that downloads, verifies, and replaces the running binary.
REMOTE_UPDATE_REMEDY = "choose Upgrade"


@dataclass(frozen=True)
class UpdateNotice:
    """Two independent, already-decided facts about how current this
    installation is -- plain version strings, so this stays provable without
    a clock, a socket, or the filesystem anywhere near it.

    `running` is `pegasus.__version__`, the binary actually executing right
    now. `local_behind` is every installed CLI's own recorded version, one
    :class:`BehindInstall` each, in the order `session` found them -- empty
    when nothing is installed. Naming each one, rather than collapsing them
    to a single oldest version the way an earlier version of this notice
    did, is what lets more than one installed CLI each get its own accurate
    line instead of one arbitrary CLI speaking for all of them. `remote_latest`
    is the newest published release a caller already looked up -- or `None`
    for every one of "the check is disabled", "it has not answered yet", and
    "it failed", which collapse to the same thing here on purpose: none of
    them is worth saying anything about.
    """

    running: str
    local_behind: tuple[BehindInstall, ...] = ()
    remote_latest: str | None = None


def update_notice_lines(notice: UpdateNotice) -> tuple[str, ...]:
    """The main menu's preface: one line per installed CLI actually behind
    the running binary, plus up to one more for a newer published release --
    each naming its own remedy and never the other's.

    A local install behind the running binary names `Update` as the remedy,
    unless its own `BehindInstall.remedy_command` says `Update` would refuse
    it -- reapplying its own recorded selection is exactly what brings it
    current, when that reapplication is actually possible; when it is not,
    naming `Update` anyway would send someone straight into a refusal, so
    the one-time remedy command is named instead. A newer published release
    never names `Update`: it cannot fetch a new binary, so its own line
    points at :data:`REMOTE_UPDATE_REMEDY` instead. Any number of these can
    be true at once, and all of them then appear, each on its own line so
    none reads as the answer to another's problem.
    """
    lines: list[str] = []
    for behind in notice.local_behind:
        if not _is_older(behind.recorded, notice.running):
            continue
        if behind.remedy_command is not None:
            lines.append(
                f"{behind.display_name} was installed with Pegasus {behind.recorded}; the running binary is "
                f"{notice.running}, but Update cannot reapply its bound mcp server key(s) without guessing -- "
                f"run this once instead: {behind.remedy_command}"
            )
        else:
            lines.append(
                f"{behind.display_name} was installed with Pegasus {behind.recorded}; the running binary is "
                f"{notice.running} -- choose Update to bring it current."
            )
    if _is_older(notice.running, notice.remote_latest):
        lines.append(
            f"A newer release, {notice.remote_latest}, has been published (this binary is {notice.running}) -- "
            f"{REMOTE_UPDATE_REMEDY}."
        )
    return tuple(lines)


def main_menu(
    detections: tuple[CliOption, ...] = (),
    installed: tuple[CliOption, ...] = (),
    notice: UpdateNotice | None = None,
) -> Menu:
    """Grouped by intent rather than by when each entry was added: get
    working and keep current (`Install`, `Update`, `Upgrade`), then configure
    (`Configure models`), then inspect (`Status and diagnostics`), then
    remove -- `Uninstall` last before `Exit` so it does not sit where
    arrow-key navigation, moving one step at a time, can land on the
    destructive entry by accident.

    `restore` has no entry of its own here on purpose: a seventh entry for a
    command the doc never lists would break that parity for no reason
    `restore` itself needs — it is reached from the status screen instead,
    see :class:`StatusScreen`. `Update` and `Upgrade` break that same parity
    anyway, because unlike `restore` they are exactly the flows this and an
    earlier change added.

    `notice`, when given, becomes the menu's `preface` -- two independent
    facts about how current this installation is, already decided by
    whoever built it (`session` for the local half, `app` for the remote
    half once its background check resolves); `None` here means "nothing
    decided yet", not "checked and found nothing to say".
    """
    return Menu(
        title=f"Pegasus Harness {pegasus.__version__}",
        entries=(
            Entry("Install", install_menu(detections)),
            Entry("Update", update_menu(installed)),
            Entry("Upgrade", UpgradeTarget()),
            Entry("Configure models", models_menu(detections)),
            Entry("Status and diagnostics", StatusRequest()),
            Entry("Uninstall", uninstall_menu(installed)),
            Entry("Exit", QUIT),
        ),
        preface=update_notice_lines(notice) if notice is not None else (),
        installed=bool(installed),
        version=pegasus.__version__,
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
    def starting(
        detections: tuple[CliOption, ...] = (),
        installed: tuple[CliOption, ...] = (),
        notice: UpdateNotice | None = None,
    ) -> "Navigator":
        return Navigator(_stack=(main_menu(detections, installed, notice),), _cursors=(0,))

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
        if isinstance(screen, McpSelectionScreen):
            return self._handle_on_mcp_selection(screen, action)
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

    def _handle_on_mcp_selection(self, screen: McpSelectionScreen, action: Action) -> "Navigator":
        count = len(screen.options) + 1  # the row after the last server is Continue.
        if action is Action.MOVE_DOWN:
            return self._with_cursor((self.cursor + 1) % count)
        if action is Action.MOVE_UP:
            return self._with_cursor((self.cursor - 1) % count)
        if action is Action.BACK:
            return self._pop()
        if action is Action.CHOOSE:
            if self.cursor == len(screen.options):
                # Continue: fetching the plan for this selection is real
                # engine work, left to `session` — see the screen's own
                # docstring.
                return self
            return self._swapped(_toggled(screen, self.cursor))
        if action is Action.TOGGLE:
            # A second spelling of the same toggle `CHOOSE` already does on a
            # server row — but Continue is not a togglable thing, so unlike
            # `CHOOSE` there is nothing for it to do there.
            if self.cursor == len(screen.options):
                return self
            return self._swapped(_toggled(screen, self.cursor))
        return self

    def _swapped(self, screen: Screen) -> "Navigator":
        """Like `replaced`, but keeps the cursor exactly where it is —
        toggling one row of a checklist must not throw the cursor back to
        the top the way narrowing a step of the models wizard does."""
        return replace(self, _stack=self._stack[:-1] + (screen,))

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

    def with_notice(self, notice: UpdateNotice) -> "Navigator":
        """Attach `notice` to the main menu at the bottom of the stack --
        even if navigation has already moved on since it was drawn.

        The remote half of a notice starts a background check before the
        first frame even exists, and can resolve at any point after --
        including well after a person has walked several screens deep. The
        main menu they will eventually return to is still `_stack[0]`
        regardless of where they are now, so this rewrites exactly that
        entry, cursor and everything else on the stack left untouched.
        """
        main = replace(self._stack[0], preface=update_notice_lines(notice))
        return replace(self, _stack=(main,) + self._stack[1:])

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
