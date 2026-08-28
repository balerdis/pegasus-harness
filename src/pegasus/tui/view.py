"""A screen, turned into the exact lines a person would read.

`render` is the whole of what stands between :class:`~pegasus.tui.navigator.Screen`
and a terminal: it decides wording and layout, and nothing past this point
does. The drawing layer copies :class:`Line` onto a window one row at a time
and reads no meaning out of them beyond ``highlighted``.
"""
from __future__ import annotations

from dataclasses import dataclass

from pegasus import cli
from pegasus.tui.navigator import InstallPlanScreen, InstallResultScreen, Menu, Placeholder, Screen

SELECTED = "  ▸ "
UNSELECTED = "    "

# What tells a person which side of the point of no return they are on. The
# plan screen is a preview of `install --dry-run`'s own report and never
# writes anything by itself; only confirming it does. The two banners are
# deliberately unalike so this is never left to be inferred from wording that
# could look the same by accident.
PREVIEW_BANNER = "PREVIEW — nothing has been written yet."
INSTALLED_BANNER = "INSTALLED."
FAILED_BANNER = "INSTALL FAILED."


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
    raise TypeError(f"no rendering defined for screen: {screen!r}")


def _render_menu(screen: Menu, cursor: int) -> tuple[Line, ...]:
    lines = [Line(screen.title), Line("")]
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
