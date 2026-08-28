"""A screen, turned into the exact lines a person would read.

`render` is the whole of what stands between :class:`~pegasus.tui.navigator.Screen`
and a terminal: it decides wording and layout, and nothing past this point
does. The drawing layer copies :class:`Line` onto a window one row at a time
and reads no meaning out of them beyond ``highlighted``.
"""
from __future__ import annotations

from dataclasses import dataclass

from pegasus.tui.navigator import Menu, Placeholder, Screen

SELECTED = "  ▸ "
UNSELECTED = "    "


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
