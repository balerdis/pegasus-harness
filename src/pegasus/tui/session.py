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

from pegasus import cli
from pegasus.adapters import available
from pegasus.core import content as content_module
from pegasus.core import journal as journal_module
from pegasus.core import model_assignments as model_assignments_module
from pegasus.tui.navigator import (
    CANCEL,
    EFFORT_OPTIONS,
    Action,
    AgentRow,
    CliOption,
    Entry,
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


def _restore_preview(generation: int, runtime: cli.Runtime) -> Menu:
    """What confirming `RestoreConfirm(generation)` would touch, read from
    that generation's own manifest without writing anything. Cancel sits
    first, for the same reason it does in :func:`_uninstall_preview`."""
    manifest = cli.snapshot_store(runtime).read(generation)
    lines = tuple(f"{'restore' if entry.existed else 'remove'}: {entry.path}" for entry in manifest.entries)
    preface = _summarised(
        f"Taken {manifest.taken_at}. Going back to it will touch",
        lines,
        f"Taken {manifest.taken_at}. Nothing was captured.",
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
    if isinstance(screen, ModelsScreen):
        stepped = _models_write(screen, navigator, runtime, action)
        if stepped is not None:
            return stepped
    if isinstance(screen, McpSelectionScreen):
        stepped = _mcp_write(screen, navigator, runtime, action)
        if stepped is not None:
            return stepped
    if isinstance(screen, InstallPlanScreen) and action is Action.CHOOSE:
        _, report = cli.safe_report(
            "install", lambda: cli.install(screen.cli.id, runtime, mcp=list(screen.mcp))
        )
        return navigator.opened(InstallResultScreen(cli=screen.cli, report=report))
    if isinstance(screen, StatusScreen) and action is Action.CHOOSE:
        generations = tuple(reversed(cli.snapshot_store(runtime).readable_generations()))
        return navigator.opened(restore_menu(generations))
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
