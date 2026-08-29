"""A screen, turned into the exact lines a person would read.

`render` is the whole of what stands between :class:`~pegasus.tui.navigator.Screen`
and a terminal: it decides wording and layout, and nothing past this point
does. The drawing layer copies :class:`Line` onto a window one row at a time
and reads no meaning out of them beyond ``highlighted``.
"""
from __future__ import annotations

from dataclasses import dataclass

from pegasus import cli
from pegasus.tui.navigator import (
    EFFORT_OPTIONS,
    InstallPlanScreen,
    InstallResultScreen,
    Menu,
    ModelsScreen,
    Placeholder,
    RestoreResultScreen,
    Screen,
    StatusScreen,
    UninstallResultScreen,
)

SELECTED = "  ▸ "
UNSELECTED = "    "

# What tells a person which side of the point of no return they are on. The
# plan screen is a preview of `install --dry-run`'s own report and never
# writes anything by itself; only confirming it does. Every banner below is
# deliberately unalike the others so this is never left to be inferred from
# wording that could look the same by accident.
PREVIEW_BANNER = "PREVIEW — nothing has been written yet."
INSTALLED_BANNER = "INSTALLED."
FAILED_BANNER = "INSTALL FAILED."
UNINSTALLED_BANNER = "UNINSTALLED."
UNINSTALL_FAILED_BANNER = "UNINSTALL FAILED."
RESTORED_BANNER = "RESTORED."
RESTORE_FAILED_BANNER = "RESTORE FAILED."


@dataclass(frozen=True)
class Line:
    """One row of a screen. ``highlighted`` is the only thing a renderer of
    this needs to know beyond the text itself."""

    text: str
    highlighted: bool = False


def render(screen: Screen, cursor: int) -> tuple[Line, ...]:
    if isinstance(screen, Menu):
        return _render_menu(screen, cursor)
    if isinstance(screen, Placeholder):
        return _render_placeholder(screen)
    if isinstance(screen, InstallPlanScreen):
        return _render_install_plan(screen)
    if isinstance(screen, InstallResultScreen):
        return _render_install_result(screen)
    if isinstance(screen, StatusScreen):
        return _render_status(screen)
    if isinstance(screen, UninstallResultScreen):
        return _render_uninstall_result(screen)
    if isinstance(screen, RestoreResultScreen):
        return _render_restore_result(screen)
    if isinstance(screen, ModelsScreen):
        return _render_models(screen, cursor)
    raise TypeError(f"no rendering defined for screen: {screen!r}")


def _render_menu(screen: Menu, cursor: int) -> tuple[Line, ...]:
    lines = [Line(screen.title), Line("")]
    if screen.preface:
        lines.extend(Line(text) for text in screen.preface)
        lines.append(Line(""))
    for index, entry in enumerate(screen.entries):
        selected = index == cursor
        prefix = SELECTED if selected else UNSELECTED
        lines.append(Line(f"{prefix}{entry.label}", highlighted=selected))
    return tuple(lines)


def _render_placeholder(screen: Placeholder) -> tuple[Line, ...]:
    return (
        Line(screen.title),
        Line(""),
        Line(screen.note),
        Line(""),
        Line("enter/esc: back"),
    )


def _render_install_plan(screen: InstallPlanScreen) -> tuple[Line, ...]:
    lines = [Line(f"Install · {screen.cli.display_name}"), Line(""), Line(PREVIEW_BANNER), Line("")]
    lines.extend(Line(text) for text in cli.prose_for(screen.report).splitlines())
    lines += [Line(""), Line("enter: install now · esc: back, nothing written")]
    return tuple(lines)


def _render_install_result(screen: InstallResultScreen) -> tuple[Line, ...]:
    failed = screen.report.get("status") == "failed"
    banner = FAILED_BANNER if failed else INSTALLED_BANNER
    lines = [Line(f"Install · {screen.cli.display_name}"), Line(""), Line(banner), Line("")]
    lines.extend(Line(text) for text in cli.prose_for(screen.report).splitlines())
    lines += [Line(""), Line("enter/esc: back")]
    return tuple(lines)


def _render_status(screen: StatusScreen) -> tuple[Line, ...]:
    lines = [Line("Status and diagnostics"), Line("")]
    lines.extend(Line(text) for text in cli.prose_for(screen.report).splitlines())
    lines += [Line(""), Line("enter: view snapshot generations to restore · esc: back")]
    return tuple(lines)


def _render_uninstall_result(screen: UninstallResultScreen) -> tuple[Line, ...]:
    failed = screen.report.get("status") == "failed"
    banner = UNINSTALL_FAILED_BANNER if failed else UNINSTALLED_BANNER
    lines = [Line(f"Uninstall · {screen.cli.display_name}"), Line(""), Line(banner), Line("")]
    lines.extend(Line(text) for text in cli.prose_for(screen.report).splitlines())
    lines += [Line(""), Line("enter/esc: back")]
    return tuple(lines)


def _render_restore_result(screen: RestoreResultScreen) -> tuple[Line, ...]:
    failed = screen.report.get("status") == "failed"
    banner = RESTORE_FAILED_BANNER if failed else RESTORED_BANNER
    lines = [Line("Restore"), Line(""), Line(banner), Line("")]
    lines.extend(Line(text) for text in cli.prose_for(screen.report).splitlines())
    lines += [Line(""), Line("enter/esc: back")]
    return tuple(lines)


#: How many choices a step of the models wizard shows before the rest slide
#: out of view. Unlike `_summarised`'s preface, these are choices rather than
#: a report: hiding the ones that do not fit would make them unreachable, so
#: the window follows the cursor instead of ever dropping an item for good.
VISIBLE_CHOICES = 12


def _visible_window(count: int, cursor: int) -> tuple[int, int]:
    """The slice of a choice list to show so the cursor always sits inside
    it, without claiming a modest terminal has more room than it does."""
    if count <= VISIBLE_CHOICES:
        return 0, count
    start = min(max(cursor - VISIBLE_CHOICES // 2, 0), count - VISIBLE_CHOICES)
    return start, start + VISIBLE_CHOICES


def _render_choices(
    title: str, items: tuple[str, ...], cursor: int, footer: str, *, header: str | None = None, empty: str | None = None
) -> tuple[Line, ...]:
    lines = [Line(title), Line("")]
    if not items:
        lines += [Line(empty or "Nothing to choose from."), Line(""), Line(footer)]
        return tuple(lines)
    if header:
        lines.append(Line(header))
    start, end = _visible_window(len(items), cursor)
    if start > 0:
        lines.append(Line(f"  ... {start} more above"))
    for index in range(start, end):
        prefix = SELECTED if index == cursor else UNSELECTED
        lines.append(Line(f"{prefix}{items[index]}", highlighted=index == cursor))
    if end < len(items):
        lines.append(Line(f"  ... {len(items) - end} more below"))
    lines += [Line(""), Line(footer)]
    return tuple(lines)


def _render_models(screen: ModelsScreen, cursor: int) -> tuple[Line, ...]:
    """The doc's four-step walk, one step's worth of choices at a time --
    which step depends only on how much of `screen` is already filled in,
    matching `navigator._models_step_count`'s own reading of the same state.
    """
    heading = f"Models · {screen.cli.display_name}"
    if screen.agent is None:
        items = tuple(f"{row.agent:<24} {row.current or '(no model)'}" for row in screen.rows)
        return _render_choices(
            heading,
            items,
            cursor,
            "enter: configure · d: remove current model · esc: back",
            header=f"{'Agent':<24} Current model",
            empty="This release ships no agent that accepts a model assignment.",
        )
    heading = f"{heading} · {screen.agent}"
    if screen.provider_id is None:
        items = tuple(provider.id for provider in screen.providers)
        return _render_choices(f"{heading} · choose a provider", items, cursor, "enter: choose · esc: back")
    heading = f"{heading} · {screen.provider_id}"
    provider = next(provider for provider in screen.providers if provider.id == screen.provider_id)
    if screen.model_id is None:
        items = tuple(model.id for model in provider.models)
        return _render_choices(f"{heading} · choose a model", items, cursor, "enter: choose · esc: back")
    heading = f"{heading}/{screen.model_id}"
    return _render_choices(f"{heading} · choose an effort", EFFORT_OPTIONS, cursor, "enter: assign · esc: back")
