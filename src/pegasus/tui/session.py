"""The one place the TUI touches the install engine.

`navigator` and `view` are pure on purpose, and detecting a CLI, previewing a
plan, and applying one are all real disk work, so none of it belongs there.
This module is the bridge: it has exactly two decisions of its own — which of
the two engine calls a key press requires, and which screen the answer
becomes — and both calls are `pegasus.cli.install`, the same function the
`install` flag reaches, run through the same `cli.safe_report` that gives
`main` its failure handling. Nothing here re-derives what a report means;
`view` still does all of that, from the report this module hands it
untouched.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

import pegasus
from pegasus import cli
from pegasus.adapters import available
from pegasus.core import content as content_module
from pegasus.core import journal as journal_module
from pegasus.core import model_assignments as model_assignments_module
from pegasus.tui.navigator import (
    CANCEL,
    EFFORT_OPTIONS,
    PEGASUS_PROGRAM,
    Action,
    AgentRow,
    CliOption,
    Entry,
    GenerationSummary,
    InstallPlanScreen,
    InstallResultScreen,
    InstallTarget,
    McpOption,
    McpSelectionScreen,
    Menu,
    ModelOption,
    ModelsScreen,
    ModelsTarget,
    Navigator,
    Placeholder,
    ProviderOption,
    RestoreConfirm,
    RestoreResultScreen,
    RestoreTarget,
    StatusRequest,
    StatusScreen,
    UninstallConfirm,
    UninstallResultScreen,
    UninstallTarget,
    UpdateNotice,
    UpdateTarget,
    UpgradeTarget,
    BehindInstall,
    readable_timestamp,
    restore_menu,
)


def detect_clis(runtime: cli.Runtime) -> tuple[CliOption, ...]:
    """Every CLI this release supports that is actually present here.

    The same probe `install --cli` refuses to proceed without
    (`_require_present`), run for every adapter instead of one named on the
    command line — this is what lets the TUI offer a choice at all.
    """
    registry = available()
    environment = runtime.environment
    options = []
    for cli_id in registry.ids():
        adapter = registry.get(cli_id)
        detection = adapter.detect(environment)
        if detection.present:
            options.append(
                CliOption(
                    id=adapter.id,
                    display_name=adapter.display_name,
                    config_dir=str(detection.config_dir or ""),
                    tier=adapter.tier().value,
                )
            )
    return tuple(options)


def detect_installed(runtime: cli.Runtime) -> tuple[CliOption, ...]:
    """Every CLI this release supports that Pegasus is currently recorded as
    installed into — unlike :func:`detect_clis`, never mind whether the CLI
    itself is still detected present, since `uninstall` does not require
    that either."""
    registry = available()
    environment = runtime.environment
    journal = cli.journal_store(runtime).load()
    options = []
    for cli_id in registry.ids():
        if journal_module.install_for(journal, cli_id) is None:
            continue
        adapter = registry.get(cli_id)
        detection = adapter.detect(environment)
        options.append(
            CliOption(
                id=adapter.id,
                display_name=adapter.display_name,
                config_dir=str(detection.config_dir or ""),
                tier=adapter.tier().value,
            )
        )
    return tuple(options)


def local_update_notice(runtime: cli.Runtime, installed: tuple[CliOption, ...]) -> UpdateNotice:
    """The local half of `UpdateNotice`: no network, always available, so
    unlike the remote half this needs no thread and can be built before the
    very first frame.

    Reads each installed CLI's own journal entry -- the same `Install.release`
    `doctor` already reports -- and names every one, not just an arbitrary
    oldest one, since `update_notice_lines` now names each CLI on its own
    line. For each, also decides whether `cli.update` would actually reapply
    it: `cli.update_unresolved_bindings` is the exact same classification
    `update` itself refuses on, so this can never recommend `Update` for an
    installation that would refuse it -- the one thing this fixes. When it
    would refuse, `cli.install_command_for` builds the one-time remedy from
    the same source `update`'s own refusal message already builds it from,
    so the two can never name a different command.
    """
    journal = cli.journal_store(runtime).load()
    behind = []
    for option in installed:
        install = journal_module.install_for(journal, option.id)
        if install is None:
            continue
        unresolved = cli.update_unresolved_bindings(install)
        remedy = cli.install_command_for(option.id, unresolved) if unresolved else None
        behind.append(
            BehindInstall(display_name=option.display_name, recorded=install.release.get("version"), remedy_command=remedy)
        )
    return UpdateNotice(running=pegasus.__version__, local_behind=tuple(behind))


def _uninstall_preview(cli_option: CliOption, runtime: cli.Runtime) -> Menu:
    """What confirming `UninstallTarget(cli_option)` would remove, read from
    the journal the way `cli.uninstall` itself reads it — but only read,
    since `uninstall` has no dry-run flag to preview through. Cancel sits
    first, so a key that only ever meant "move" or "acknowledge" elsewhere
    lands on it by default."""
    journal = cli.journal_store(runtime).load()
    install = journal_module.install_for(journal, cli_option.id)
    entries = tuple(f"{entry.id} → {entry.target}" for entry in (install.entries if install else ()))
    preface = _summarised("About to remove", entries, "Nothing recorded to remove.")
    return Menu(
        title=f"Uninstall · {cli_option.display_name}",
        preface=preface,
        entries=(Entry("Cancel — leave it installed", CANCEL), Entry("Confirm — remove it", UninstallConfirm(cli_option))),
    )


def _local_taken_at(taken_at: str) -> str:
    """A manifest's UTC timestamp moved into the zone the reader lives in.

    A snapshot is recorded in UTC, which is right for a file on disk and
    wrong for a label: found against a real installation, a generation taken
    at 18:50 in Buenos Aires was offered as "21:50". A plausible wrong hour
    is worse than an obviously broken one, because a person believes it --
    and it undoes the only argument for putting a timestamp on that row,
    which was that somebody recognises what they did at 4am.

    The conversion sits here, not in `navigator`, because reading the
    machine's zone is reading the environment: `navigator` stays pure and
    goes on printing the wall clock of whatever offset it is handed.

    Two shapes are passed through untouched. A string that will not parse is
    not this function's to repair -- `navigator.readable_timestamp` already
    shows such a value raw rather than letting the recovery screen fail over
    a bad date. And a timestamp with no offset at all names no instant to
    convert from, so guessing one would invent a shift rather than correct
    one; every version of Pegasus that writes a manifest records the offset.
    """
    try:
        parsed = datetime.fromisoformat(taken_at)
    except (TypeError, ValueError):
        return taken_at
    if parsed.tzinfo is None:
        return taken_at
    return parsed.astimezone().isoformat()


def _generation_summaries(runtime: cli.Runtime) -> tuple[tuple[GenerationSummary, ...], tuple[int, ...]]:
    """Every generation the restore menu can actually open, most recent
    first, plus the numbers of the ones `readable_generations` claimed that
    turned out not to be.

    `readable_generations` only checks that a generation's manifest file is
    *present* -- it says nothing about whether the JSON inside it parses
    (see `ports.snapshot_store`'s module docstring on that asymmetry).
    Building labelled entries needs the manifest's actual contents, so this
    reads every one of them with `SnapshotStore.read`, which is strict and
    raises `SnapshotStoreError` on exactly the folder `readable_generations`
    was lenient about. One such folder is dropped here rather than left to
    raise once the menu is already open: the whole point of this screen is
    to reach a generation that is still good, so a single bad one must never
    blind it to every other, honest generation next to it.
    """
    store = cli.snapshot_store(runtime)
    generations = tuple(reversed(store.readable_generations()))
    summaries: list[GenerationSummary] = []
    skipped: list[int] = []
    for generation in generations:
        try:
            manifest = store.read(generation)
        except cli.SnapshotStoreError:
            skipped.append(generation)
            continue
        summaries.append(
            GenerationSummary(
                generation=generation,
                taken_at=_local_taken_at(manifest.taken_at),
                files_restored=sum(1 for entry in manifest.entries if entry.existed),
                paths_cleared=sum(1 for entry in manifest.entries if not entry.existed),
            )
        )
    return tuple(summaries), tuple(skipped)


def _restore_preview(generation: int, runtime: cli.Runtime) -> Menu:
    """What confirming `RestoreConfirm(generation)` would touch, read from
    that generation's own manifest without writing anything. Cancel sits
    first, for the same reason it does in :func:`_uninstall_preview`."""
    manifest = cli.snapshot_store(runtime).read(generation)
    lines = tuple(f"{'restore' if entry.existed else 'remove'}: {entry.path}" for entry in manifest.entries)
    # The same two steps the menu's own labels take, for the same reason and
    # in the same order: a manifest records UTC, and a person reads a wall
    # clock. Skipping them here quoted the raw ISO-8601 string, so the screen
    # a person confirms on named a different hour than the row they picked.
    when = readable_timestamp(_local_taken_at(manifest.taken_at))
    preface = _summarised(
        f"Taken {when}. Going back to it will touch",
        lines,
        f"Taken {when}. Nothing was captured.",
    )
    return Menu(
        title=f"Restore · generation {generation}",
        preface=preface,
        entries=(Entry("Cancel — leave things as they are", CANCEL), Entry("Confirm — restore it", RestoreConfirm(generation))),
    )


def _currently_chosen_mcp(cli_id: str, runtime: cli.Runtime) -> tuple[str, ...]:
    """Which mcp servers this CLI's own journal already records as
    installed, read the same way `detect_installed` reads a CLI's own
    presence: an entry's `id` names the server it is for as `mcp:<name>`,
    the one convention every adapter's `render_mcp` follows, and the
    convention file that travels alongside it is deliberately not counted
    here since it names no server of its own."""
    journal = cli.journal_store(runtime).load()
    install = journal_module.install_for(journal, cli_id)
    if install is None:
        return ()
    return tuple(sorted(entry.id.split(":", 1)[1] for entry in install.entries if entry.id.startswith("mcp:")))


def _mcp_selection_screen(cli_option: CliOption, runtime: cli.Runtime) -> McpSelectionScreen:
    """The step between choosing a CLI and seeing its plan, built fresh
    every time -- the same reasoning `_models_screen` already follows for
    its own read-only screen. `chosen` opens on what the journal already
    records, so a person who touches nothing and moves straight to Continue
    reproduces the machine's current state instead of retiring it."""
    options = tuple(
        McpOption(id=server.name, description=server.description) for server in content_module.load().mcp
    )
    return McpSelectionScreen(cli=cli_option, options=options, chosen=_currently_chosen_mcp(cli_option.id, runtime))


def _mcp_write(
    screen: McpSelectionScreen, navigator: Navigator, runtime: cli.Runtime, action: Action
) -> Navigator | None:
    """The one moment on this screen that is real engine work rather than a
    pure toggle: reaching Continue, the row after every server, and choosing
    it fetches the same dry-run plan `install --dry-run --mcp ...` would
    report for exactly the servers checked so far. `Navigator` leaves this
    row a no-op on purpose -- see `McpSelectionScreen`'s own docstring -- so
    this is where it actually happens. Returns `None` for every other
    action, which tells `step` to fall through to `navigator.handle`, the
    same as `_models_write` does for its own pure steps.
    """
    if action is not Action.CHOOSE or navigator.cursor != len(screen.options):
        return None
    chosen = screen.chosen
    _, report = cli.safe_report(
        "install", lambda: cli.install(screen.cli.id, runtime, dry_run=True, mcp=list(chosen))
    )
    return navigator.opened(InstallPlanScreen(cli=screen.cli, report=report, mcp=chosen))


def _configurable_agents() -> tuple[str, ...]:
    """Every agent this release lets a person assign a model to, in the order
    the content core ships them. The engine already refuses the rest through
    `_require_configurable_agent`; reading the same fact here is what keeps
    this screen from ever offering what a write to it would refuse."""
    return tuple(agent.name for agent in content_module.load().agents if agent.model_configurable)


def _current_assignment(cli_id: str, agent: str, runtime: cli.Runtime) -> str | None:
    assignment = model_assignments_module.get(cli.model_assignment_store(runtime).load(), cli_id, agent)
    if assignment is None:
        return None
    return assignment.full_id + (f" · {assignment.effort}" if assignment.effort else "")


def _models_screen(cli_option: CliOption, runtime: cli.Runtime) -> Menu | Placeholder | ModelsScreen:
    """The doc's `Modelos · CLI` step, or the explanation for why there is
    nothing to show yet -- read fresh every time this is called, the same
    reasoning `_uninstall_preview` and `_restore_preview` already follow for
    their own read-only screens."""
    catalog = available().get(cli_option.id).model_catalog(runtime.environment)
    if not catalog.providers:
        return Placeholder(
            f"Configure models · {cli_option.display_name}",
            f"{cli_option.display_name} has no model catalog to read yet -- open it at least once so "
            "it can build one, or sign in to a provider, then come back.",
        )
    providers = tuple(
        ProviderOption(
            id=provider.id,
            models=tuple(ModelOption(id=model.id, reasoning=model.reasoning) for model in provider.models),
        )
        for provider in catalog.providers
    )
    rows = tuple(
        AgentRow(agent=agent, current=_current_assignment(cli_option.id, agent, runtime))
        for agent in _configurable_agents()
    )
    return ModelsScreen(cli=cli_option, providers=providers, rows=rows)


def _models_write(screen: ModelsScreen, navigator: Navigator, runtime: cli.Runtime, action: Action) -> Navigator | None:
    """The three moments in the wizard that are a real write rather than a
    pure narrowing: removing an assignment, and committing a plain model or
    an effort. `Navigator` leaves each of these as a no-op on purpose --
    see `ModelsScreen`'s own docstring -- so this is where they actually
    happen. Returns `None` for every other action, which tells `step` to
    fall through to `navigator.handle` as usual.
    """
    if action is Action.REMOVE and screen.agent is None and screen.rows:
        agent = screen.rows[navigator.cursor].agent
        cli.safe_report("models", lambda: cli.models_unset(screen.cli.id, agent, runtime))
        return navigator.replaced(_models_screen(screen.cli, runtime))
    if action is not Action.CHOOSE:
        return None
    if screen.model_id is not None:
        effort = EFFORT_OPTIONS[navigator.cursor]
        cli.safe_report(
            "models",
            lambda: cli.models_set(
                screen.cli.id, screen.agent, f"{screen.provider_id}/{screen.model_id}", runtime, effort=effort
            ),
        )
        return navigator.replaced(_models_screen(screen.cli, runtime))
    if screen.provider_id is not None:
        provider = next(provider for provider in screen.providers if provider.id == screen.provider_id)
        if not provider.models or provider.models[navigator.cursor].reasoning:
            return None  # a reasoning model: `Navigator` narrows to the effort step itself.
        model_id = provider.models[navigator.cursor].id
        cli.safe_report(
            "models",
            lambda: cli.models_set(screen.cli.id, screen.agent, f"{screen.provider_id}/{model_id}", runtime, effort=None),
        )
        return navigator.replaced(_models_screen(screen.cli, runtime))
    return None


def install_task(
    navigator: Navigator, runtime: cli.Runtime, screen: InstallPlanScreen
) -> Callable[[Callable[[cli.Progress], None]], Navigator]:
    """The real install behind `InstallPlanScreen`'s own confirmation,
    packaged as a plain callable rather than run here directly.

    `session` knows everything about the engine call -- the same
    `cli.install`, run through the same `cli.safe_report`, that
    `step`'s own synchronous branch below calls -- but nothing about how or
    where it runs. `app.py` is the one place that owns a worker thread; this
    only hands it something to run on one, and the sink to feed
    `on_progress` into so the thread that owns the window can read it back.
    """

    def run(sink: Callable[[cli.Progress], None]) -> Navigator:
        _, report = cli.safe_report(
            "install", lambda: cli.install(screen.cli.id, runtime, mcp=list(screen.mcp), on_progress=sink)
        )
        return navigator.opened(InstallResultScreen(cli=screen.cli, report=report))

    return run


def update_task(
    navigator: Navigator, runtime: cli.Runtime, screen: InstallPlanScreen
) -> Callable[[Callable[[cli.Progress], None]], Navigator]:
    """`install_task`'s twin for the Update flow: the same worker-thread
    seam, running `cli.update` instead of `cli.install`. Kept apart from
    `install_task` rather than folded into it, since `update` recomputes its
    own `--mcp` selection fresh from the journal at the moment it runs --
    reusing `screen.mcp`, frozen at preview time, would risk a second,
    slightly different implementation of exactly what `update` already
    does.
    """

    def run(sink: Callable[[cli.Progress], None]) -> Navigator:
        _, report = cli.safe_report("update", lambda: cli.update(screen.cli.id, runtime, on_progress=sink))
        return navigator.opened(InstallResultScreen(cli=screen.cli, report=report, command="update"))

    return run


def upgrade_task(
    navigator: Navigator, runtime: cli.Runtime, screen: InstallPlanScreen
) -> Callable[[Callable[[cli.Progress], None]], Navigator]:
    """`install_task`'s twin for the Upgrade flow: the same worker-thread
    seam, running `cli.upgrade` instead of `cli.install`. `screen.cli` is
    `PEGASUS_PROGRAM`, never read by `cli.upgrade` itself (which takes no
    CLI id at all) -- it is carried only so the result screen this returns
    still has something to render a heading from, same as the plan screen
    it confirms.
    """

    def run(sink: Callable[[cli.Progress], None]) -> Navigator:
        _, report = cli.safe_report("upgrade", lambda: cli.upgrade(runtime, on_progress=sink))
        return navigator.opened(InstallResultScreen(cli=screen.cli, report=report, command="upgrade"))

    return run


def plan_task(
    navigator: Navigator, runtime: cli.Runtime, screen: InstallPlanScreen
) -> Callable[[Callable[[cli.Progress], None]], Navigator]:
    """Which real engine call a confirmed `InstallPlanScreen` actually needs
    -- `install_task`, `update_task`, or `upgrade_task` -- decided from
    `screen.command` the same way every other place shared between the
    flows reads it. This is the one seam `app.py`'s worker thread reaches
    through, so it never has to know how many flows exist as anything but
    one screen.
    """
    if screen.command == "update":
        return update_task(navigator, runtime, screen)
    if screen.command == "upgrade":
        return upgrade_task(navigator, runtime, screen)
    return install_task(navigator, runtime, screen)


def _update_preview(cli_option: CliOption, runtime: cli.Runtime) -> InstallPlanScreen | InstallResultScreen:
    """What choosing `UpdateTarget(cli_option)` opens: a preview of what
    `update` would reapply, fetched through the same `cli.update(...,
    dry_run=True)` the flag itself runs. Unlike an install, this can already
    fail here -- an unresolved mcp binding key refuses before `install` is
    ever reached -- and a refusal has nothing left to preview or confirm, so
    it opens straight onto a result screen instead of a plan with nothing
    real to show.
    """
    code, report = cli.safe_report("update", lambda: cli.update(cli_option.id, runtime, dry_run=True))
    if code != cli.OK:
        return InstallResultScreen(cli=cli_option, report=report, command="update")
    return InstallPlanScreen(cli=cli_option, report=report, command="update")


def _upgrade_preview(runtime: cli.Runtime) -> InstallPlanScreen | InstallResultScreen:
    """What choosing `UpgradeTarget()` opens: a preview of what `pegasus
    upgrade` would replace, fetched through `cli.upgrade(..., dry_run=True)`
    -- the same call `--dry-run` itself runs. `PEGASUS_PROGRAM` stands in
    for the `CliOption` every other flow's plan and result screen carry,
    since `upgrade` has none of its own. Like `_update_preview`, this can
    already fail here -- not running from an installed executable, an
    unwritable destination, or no network -- and a refusal has nothing left
    to preview or confirm, so it opens straight onto a result screen instead
    of a plan with nothing real to show. Being already current is not a
    refusal, but it belongs on the same result screen for the same reason:
    there is no plan to preview when there is nothing to do.
    """
    code, report = cli.safe_report("upgrade", lambda: cli.upgrade(runtime, dry_run=True))
    if code != cli.OK or report.get("status") == "already-current":
        return InstallResultScreen(cli=PEGASUS_PROGRAM, report=report, command="upgrade")
    return InstallPlanScreen(cli=PEGASUS_PROGRAM, report=report, command="upgrade")


def step(navigator: Navigator, runtime: cli.Runtime, action: Action) -> Navigator:
    """One key's worth of navigation, running whichever engine call it needs.

    A choice that needs a preview or a real write is handled here, by
    matching the target or screen it landed on; everything else is ordinary
    navigation, handled exactly as it already was.
    """
    screen = navigator.current
    if isinstance(screen, Menu) and action is Action.CHOOSE:
        target = screen.entries[navigator.cursor].target
        if isinstance(target, InstallTarget):
            return navigator.opened(_mcp_selection_screen(target.cli, runtime))
        if isinstance(target, StatusRequest):
            _, report = cli.safe_report(target.command, lambda: cli.doctor(runtime))
            return navigator.opened(StatusScreen(report=report))
        if isinstance(target, UninstallTarget):
            return navigator.opened(_uninstall_preview(target.cli, runtime))
        if isinstance(target, UninstallConfirm):
            _, report = cli.safe_report(target.command, lambda: cli.uninstall(target.cli.id, runtime))
            return navigator.opened(UninstallResultScreen(cli=target.cli, report=report))
        if isinstance(target, RestoreTarget):
            return navigator.opened(_restore_preview(target.generation, runtime))
        if isinstance(target, RestoreConfirm):
            _, report = cli.safe_report(target.command, lambda: cli.restore(runtime, target.generation))
            return navigator.opened(RestoreResultScreen(report=report))
        if isinstance(target, ModelsTarget):
            return navigator.opened(_models_screen(target.cli, runtime))
        if isinstance(target, UpdateTarget):
            return navigator.opened(_update_preview(target.cli, runtime))
        if isinstance(target, UpgradeTarget):
            return navigator.opened(_upgrade_preview(runtime))
    if isinstance(screen, ModelsScreen):
        stepped = _models_write(screen, navigator, runtime, action)
        if stepped is not None:
            return stepped
    if isinstance(screen, McpSelectionScreen):
        stepped = _mcp_write(screen, navigator, runtime, action)
        if stepped is not None:
            return stepped
    if isinstance(screen, InstallPlanScreen) and action is Action.CHOOSE:
        if screen.command == "update":
            _, report = cli.safe_report("update", lambda: cli.update(screen.cli.id, runtime))
        elif screen.command == "upgrade":
            _, report = cli.safe_report("upgrade", lambda: cli.upgrade(runtime))
        else:
            _, report = cli.safe_report(
                "install", lambda: cli.install(screen.cli.id, runtime, mcp=list(screen.mcp))
            )
        return navigator.opened(InstallResultScreen(cli=screen.cli, report=report, command=screen.command))
    if isinstance(screen, StatusScreen) and action is Action.CHOOSE:
        summaries, skipped = _generation_summaries(runtime)
        return navigator.opened(restore_menu(summaries, skipped=skipped))
    return navigator.handle(action)


#: How many of a preface's lines are shown before the rest are counted instead.
SHOWN_AT_MOST = 6


def _summarised(heading: str, lines: tuple[str, ...], nothing: str) -> tuple[str, ...]:
    """A heading, a few examples, and how many more there are.

    Listing everything is what a person asked for on a report; on a screen
    that asks a question it is the opposite of help. A hundred paths push the
    two answers off the bottom of the terminal, and someone confirming
    something destructive ends up unable to see what they are choosing
    between. The count is the fact that matters here, and `doctor` is where
    the full list already lives.
    """
    if not lines:
        return (nothing,)
    shown = lines[:SHOWN_AT_MOST]
    rest = len(lines) - len(shown)
    body = (f"{heading} {len(lines)}:", *(f"  {line}" for line in shown))
    return (*body, f"  ... and {rest} more") if rest else body
