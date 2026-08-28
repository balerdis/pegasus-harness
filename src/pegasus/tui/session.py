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
from pegasus.core import journal as journal_module
from pegasus.tui.navigator import (
    CANCEL,
    Action,
    CliOption,
    Entry,
    InstallPlanScreen,
    InstallResultScreen,
    InstallTarget,
    Menu,
    Navigator,
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
            _, report = cli.safe_report(
                target.command, lambda: cli.install(target.cli.id, runtime, dry_run=True)
            )
            return navigator.opened(InstallPlanScreen(cli=target.cli, report=report))
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
    if isinstance(screen, InstallPlanScreen) and action is Action.CHOOSE:
        _, report = cli.safe_report("install", lambda: cli.install(screen.cli.id, runtime))
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
