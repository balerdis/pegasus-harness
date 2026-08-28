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
from pegasus.tui.navigator import (
    Action,
    CliOption,
    InstallPlanScreen,
    InstallResultScreen,
    InstallTarget,
    Menu,
    Navigator,
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


def step(navigator: Navigator, runtime: cli.Runtime, action: Action) -> Navigator:
    """One key's worth of navigation, running whichever engine call it needs.

    Two moments call for one: choosing a detected CLI needs its plan before
    there is anything to show, and confirming that plan is the point of no
    return the doc's screen describes — the moment this actually writes.
    Everything else is ordinary navigation, handled exactly as it already
    was.
    """
    screen = navigator.current
    if isinstance(screen, Menu) and action is Action.CHOOSE:
        target = screen.entries[navigator.cursor].target
        if isinstance(target, InstallTarget):
            _, report = cli.safe_report(
                target.command, lambda: cli.install(target.cli.id, runtime, dry_run=True)
            )
            return navigator.opened(InstallPlanScreen(cli=target.cli, report=report))
    if isinstance(screen, InstallPlanScreen) and action is Action.CHOOSE:
        _, report = cli.safe_report("install", lambda: cli.install(screen.cli.id, runtime))
        return navigator.opened(InstallResultScreen(cli=screen.cli, report=report))
    return navigator.handle(action)
