"""A screen, turned into the exact lines a person would read.

`render` is the whole of what stands between :class:`~pegasus.tui.navigator.Screen`
and a terminal: it decides wording and layout, and nothing past this point
does. The drawing layer copies :class:`Line` onto a window one row at a time
and reads no meaning out of them beyond ``highlighted`` and ``style``.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

from pegasus import cli
from pegasus.tui import wordmark
from pegasus.tui.navigator import (
    EFFORT_OPTIONS,
    InstallPlanScreen,
    InstallResultScreen,
    McpSelectionScreen,
    Menu,
    ModelsScreen,
    Placeholder,
    RestoreResultScreen,
    Screen,
    StatusScreen,
    UninstallResultScreen,
)

#: A generous default for callers that render without knowing a real
#: terminal's width -- every test that does not care about wrapping, and any
#: future caller that genuinely has all the room a screen could ask for.
#: `app.py` never relies on this: it always passes the window's real width.
_AMPLE_WIDTH = 9999

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


class Style(Enum):
    """An emphasis a renderer applies to a span of text. `DIM` is the
    wordmark's own styling and `ACCENT` is the installer's own colour, used
    by the progress bar -- kept as an enum rather than bare bools so a later
    emphasis has somewhere to go without reshaping this again."""

    NORMAL = auto()
    DIM = auto()
    ACCENT = auto()


@dataclass(frozen=True)
class Span:
    """A run of text carrying one emphasis. A `Line` is a tuple of these
    rather than one style for the whole row, because some rows -- the
    wordmark's bicolor split, the progress bar's filled cells beside its
    percentage -- mix emphases on a single physical line."""

    text: str
    style: Style = Style.NORMAL


@dataclass(frozen=True)
class Line:
    """One row of a screen: the spans that make it up, left to right, and
    ``highlighted`` -- whether this row is the one under the cursor. A bare
    `str` is accepted in place of `spans` and normalized into a single
    `NORMAL` span, so every construction written before spans existed still
    works unchanged."""

    spans: tuple[Span, ...] | str
    highlighted: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.spans, str):
            object.__setattr__(self, "spans", (Span(self.spans),))

    @property
    def text(self) -> str:
        """The row's text with no styling -- what every caller that predates
        spans, and every test that only cares about wording, still reads."""
        return "".join(span.text for span in self.spans)


#: The installer's own visual language, reproduced exactly: a fifty-cell bar
#: of filled and empty glyphs, and a rotating spinner frame proving the
#: process is alive while a single long-running unit -- a network fetch --
#: leaves the bar itself sitting still for a long time.
BAR_WIDTH = 50
FILLED_CELL = "■"
EMPTY_CELL = "･"
_SPINNER_FRAMES = "|/-\\"


def _progress_fraction(progress: "cli.Progress") -> float:
    """`done / total`, clamped to `[0.0, 1.0]` and safe against a zero total.

    Both numbers come from arithmetic this layer did not perform -- `cli`'s
    own bookkeeping, read off a worker thread this module knows nothing
    about -- so a miscount here must never draw past a full bar or divide by
    zero rather than simply refusing to draw at all.
    """
    if progress.total <= 0:
        return 0.0
    return min(1.0, max(0.0, progress.done / progress.total))


def _bar_line(fraction: float, width: int) -> Line:
    percent = round(fraction * 100)
    suffix = f" {percent:3d}%"
    bar_width = max(0, min(BAR_WIDTH, width - len(suffix)))
    filled = round(bar_width * fraction)
    bar = FILLED_CELL * filled + EMPTY_CELL * (bar_width - filled)
    return Line((Span(f"{bar}{suffix}", Style.ACCENT),))


def render_progress(message: str, progress: "cli.Progress", frame: int, *, width: int = _AMPLE_WIDTH) -> tuple[Line, ...]:
    """The busy frame shown while a real install runs: `message` (what
    `navigator.busy_message_for` already says) beside a spinner glyph driven
    by `frame` -- proof of life while the bar itself sits still through a
    single slow unit -- then the bar, then the unit currently in progress.
    Neither the clock nor the engine call are this function's concern: `app`
    samples `time.monotonic()` into a frame count, and `session` reads the
    engine's own `Progress`; this only lays out what it is handed.
    """
    spinner = _SPINNER_FRAMES[frame % len(_SPINNER_FRAMES)]
    lines = [Line(f"{message} {spinner}"), _bar_line(_progress_fraction(progress), width)]
    if progress.unit:
        lines.append(Line((Span(progress.unit, Style.DIM),)))
    return tuple(lines)


def render_busy(message: str) -> tuple[Line, ...]:
    """The one frame shown between choosing an action that needs a real
    engine call and that call returning. `message` names the work in
    progress — what `navigator.busy_message_for` decided it is — so this
    exists only to turn that sentence into the same kind of `Line` tuple
    every other screen renders into, not to add anything of its own.
    """
    return (Line(message),)


def render(screen: Screen, cursor: int, *, width: int = _AMPLE_WIDTH) -> tuple[Line, ...]:
    if isinstance(screen, Menu):
        return _render_menu(screen, cursor, width)
    if isinstance(screen, Placeholder):
        return _render_placeholder(screen)
    if isinstance(screen, McpSelectionScreen):
        return _render_mcp_selection(screen, cursor)
    if isinstance(screen, InstallPlanScreen):
        return _render_install_plan(screen)
    if isinstance(screen, InstallResultScreen):
        return _render_install_result(screen, width)
    if isinstance(screen, StatusScreen):
        return _render_status(screen)
    if isinstance(screen, UninstallResultScreen):
        return _render_uninstall_result(screen)
    if isinstance(screen, RestoreResultScreen):
        return _render_restore_result(screen)
    if isinstance(screen, ModelsScreen):
        return _render_models(screen, cursor)
    raise TypeError(f"no rendering defined for screen: {screen!r}")


def _wordmark_variant(width: int) -> str | None:
    """Which shape of the wordmark fits in `width` columns -- `"full"`, the
    narrower `"solo"`, or `None` when even that does not fit and the plain
    text stays the honest thing to draw. A plain function of a plain int, so
    every boundary this decides is a call away from a test, no terminal
    needed to probe it."""
    if width >= wordmark.WORDMARK_WIDTH:
        return "full"
    if width >= wordmark.PEGASUS_WIDTH:
        return "solo"
    return None


def _wordmark_lines(variant: str) -> tuple[Line, ...]:
    """The art itself. The reference wordmark this reproduces dims only its
    first word and leaves the second plain beside it, on the very same row --
    exactly what a two-span `Line` exists to draw. The solo variant is the
    brand mark alone; with no second word to contrast against, it stays
    entirely dim, the same emphasis the full mark already gives that half."""
    if variant == "solo":
        return tuple(Line((Span(row, Style.DIM),)) for row in wordmark.pegasus_rows())
    pegasus_rows = wordmark.word_rows(wordmark.PEGASUS)
    harness_rows = wordmark.word_rows(wordmark.HARNESS)
    return tuple(
        Line((Span(f"{pegasus}  ", Style.DIM), Span(harness, Style.NORMAL)))
        for pegasus, harness in zip(pegasus_rows, harness_rows)
    )


def _wordmark_width(variant: str) -> int:
    return wordmark.WORDMARK_WIDTH if variant == "full" else wordmark.PEGASUS_WIDTH


def _render_menu(screen: Menu, cursor: int, width: int) -> tuple[Line, ...]:
    variant = _wordmark_variant(width) if screen.installed else None
    if variant is not None:
        lines = list(_wordmark_lines(variant))
        lines.append(Line(screen.version.rjust(_wordmark_width(variant))))
        lines.append(Line(""))
    else:
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


def _render_install_result(screen: InstallResultScreen, width: int) -> tuple[Line, ...]:
    failed = screen.report.get("status") == "failed"
    banner = FAILED_BANNER if failed else INSTALLED_BANNER
    lines = [Line(f"Install · {screen.cli.display_name}"), Line("")]
    if not failed:
        variant = _wordmark_variant(width)
        if variant is not None:
            lines.extend(_wordmark_lines(variant))
            lines.append(Line(""))
    lines += [Line(banner), Line("")]
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


#: The label the row after the last server carries — chosen so it reads as
#: what it is, an action rather than one more server, without borrowing a
#: word ("Confirm") the destructive confirmations already own for something
#: that writes nothing by itself.
CONTINUE_LABEL = "Continue"


def _render_mcp_selection(screen: McpSelectionScreen, cursor: int) -> tuple[Line, ...]:
    """The step between choosing a CLI and seeing its plan: a checklist of
    every server this release ships, and a Continue row after the last one
    that fetches the plan for whatever ended up checked."""
    heading = f"Install · {screen.cli.display_name} · choose which mcp servers to install"
    rows = tuple(
        f"[{'x' if option.id in screen.chosen else ' '}] {option.id:<12} {option.description}"
        for option in screen.options
    )
    items = rows + (CONTINUE_LABEL,)
    return _render_choices(heading, items, cursor, "enter/space: toggle a server, or continue · esc: back")


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
