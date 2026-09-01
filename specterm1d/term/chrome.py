"""Axis decoration painted as terminal text.

The text backend renders two pixels per column and two per row, so a 116x43
terminal gives the figure 232x86 pixels. A 4pt tick label is 5.6 px tall
there - smeared across three cells and unreadable at any font size, because
the smear is a property of the pixel budget, not the typeface.

The terminal draws the same digits as native glyphs at the user's own font
size. So in this mode the figure carries only data, full bleed, and
everything around it - spines, tick marks, labels, title, legend - is text
placed here. The curve ends up with *more* pixels than it had when
matplotlib was spending margins on illegible labels.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from specterm1d.plot import COLOR_BG, COLOR_FG
from specterm1d.term.base import CellRect

V_SPINE = "│"
H_SPINE = "─"
CORNER = "└"
Y_TICK = "┤"
X_TICK = "┬"

# Rows the chrome takes from the top and bottom of its rectangle: one title
# row, one row of bottom spine, one row of x tick labels.
TITLE_ROWS = 1
AXIS_ROWS = 2

Ticks = tuple[Sequence[float], Sequence[str]]


@dataclass(frozen=True)
class ChromeLayout:
    """Where the image goes and what is left over for the decoration."""

    outer: CellRect       # everything the plot and its chrome may use
    plot: CellRect        # where the RGBA image is drawn
    title_row: int | None  # 0-based row for the title, None if there is none
    axis_row: int         # 0-based row carrying the bottom spine
    label_row: int        # 0-based row carrying the x tick labels


def layout_for(outer: CellRect, ylabels: Sequence[str],
               title: bool = True) -> ChromeLayout:
    """Reserve a gutter and axis rows around ``outer`` for the decoration.

    The gutter is sized to the widest y label plus one column for the spine,
    so it grows and shrinks with the numbers actually being displayed rather
    than being a fixed guess.
    """
    label_width = max((len(text) for text in ylabels), default=1)
    gutter = min(label_width + 1, max(outer.cols - 1, 1))

    top = TITLE_ROWS if title else 0
    # Give up the decoration rather than the plot when the window is tiny:
    # a rect with zero rows draws nothing at all.
    while top + AXIS_ROWS >= outer.rows and top > 0:
        top -= 1
    bottom = AXIS_ROWS if top + AXIS_ROWS < outer.rows else 0

    plot = CellRect(row=outer.row + top, col=outer.col + gutter,
                    rows=max(outer.rows - top - bottom, 1),
                    cols=max(outer.cols - gutter, 1))
    return ChromeLayout(
        outer=outer,
        plot=plot,
        title_row=outer.row if top else None,
        axis_row=plot.row + plot.rows,
        label_row=plot.row + plot.rows + 1,
    )


def _cell_for(value: float, lo: float, hi: float, start: int, size: int,
              invert: bool = False) -> int:
    """Map a data value onto a cell index inside ``[start, start + size)``."""
    if hi <= lo or size <= 1:
        return start
    frac = (value - lo) / (hi - lo)
    if invert:
        frac = 1.0 - frac
    return start + round(frac * (size - 1))


def _rgb(hex_color: str) -> tuple[int, int, int]:
    text = hex_color.lstrip("#")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _paint(fg: str, truecolor: bool) -> str:
    """SGR for ``fg`` on the plot background, so the panel reads as one piece.

    Without an explicit background the decoration sits on whatever the user's
    theme provides and the figure looks like a dark rectangle pasted onto it.
    """
    if not truecolor:
        import numpy as np

        from specterm1d.term.text import quantize_256

        codes = quantize_256(np.array([[_rgb(fg), _rgb(COLOR_BG)]]))
        return f"\x1b[38;5;{int(codes[0][0])}m\x1b[48;5;{int(codes[0][1])}m"
    fr, fg_, fb = _rgb(fg)
    br, bg_, bb = _rgb(COLOR_BG)
    return f"\x1b[38;2;{fr};{fg_};{fb}m\x1b[48;2;{br};{bg_};{bb}m"


def _elide(text: str, width: int) -> str:
    """Drop the middle, favouring the tail so a trailing object label lives."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= 1:
        return text[:width]
    head = max(int((width - 1) * 0.4), 1)
    tail = max(width - 1 - head, 1)
    return f"{text[:head]}…{text[-tail:]}"


def render_chrome(layout: ChromeLayout, xlim: tuple[float, float],
                  ylim: tuple[float, float], xticks: Ticks, yticks: Ticks,
                  title: str = "", legend: Sequence[tuple[str, str]] = (),
                  xlabel: str = "", ylabel: str = "",
                  truecolor: bool = True) -> str:
    """Escape sequences drawing the decoration around ``layout.plot``."""
    plot = layout.plot
    right_edge = layout.outer.col + layout.outer.cols
    body = _paint(COLOR_FG, truecolor)
    out: list[str] = []

    def put(row: int, col: int, text: str, sgr: str = body) -> None:
        """Place text, clipped to the outer rect so nothing escapes it."""
        col = max(col, layout.outer.col)
        text = text[: max(right_edge - col, 0)]
        if text:
            out.append(f"\x1b[{row + 1};{col + 1}H{sgr}{text}")

    # ---- title row, with the legend (or the y label) right-aligned ----
    #
    # Bare mode has no room for matplotlib's axis labels, but --units can
    # change the dispersion axis under you, so the units have to appear
    # somewhere. They go wherever there is space left, and are dropped rather
    # than allowed to collide - a corrupted label is worse than no label.
    if layout.title_row is not None:
        width = layout.outer.cols
        tail = "  ".join(name for name, _ in legend)
        if tail:
            # An overlay is something the user just switched on, so it wins
            # the row and the title gives up characters for it.
            head = _elide(title, max(width - len(tail) - 2, 0))
        else:
            # The y label is standing context, so it yields instead: it
            # appears only in what the untruncated title leaves behind.
            head = _elide(title, width)
            if ylabel and len(title) + 2 + len(ylabel) <= width:
                tail = ylabel

        put(layout.title_row, layout.outer.col, head.ljust(width))
        col = layout.outer.col + width - len(tail)
        if legend:
            for name, color in legend:
                put(layout.title_row, col, name, _paint(color, truecolor))
                col += len(name) + 2
        elif tail:
            put(layout.title_row, col, tail)

    # ---- left spine and y tick labels ----
    spine_col = plot.col - 1
    yvalues, ylabels = yticks
    tick_rows = {
        _cell_for(value, ylim[0], ylim[1], plot.row, plot.rows, invert=True): text
        for value, text in zip(yvalues, ylabels, strict=True)
    }
    for row in range(plot.row, plot.row + plot.rows):
        text = tick_rows.get(row)
        gutter = layout.outer.col
        width = spine_col - gutter
        label = (text or "").rjust(width)[:width] if width > 0 else ""
        put(row, gutter, label + (Y_TICK if text else V_SPINE))

    # ---- bottom spine, with a tick mark under each x tick ----
    if layout.axis_row < layout.outer.row + layout.outer.rows:
        xvalues, xlabels = xticks
        columns = [_cell_for(value, xlim[0], xlim[1], plot.col, plot.cols)
                   for value in xvalues]
        axis = [H_SPINE] * plot.cols
        for col in columns:
            axis[min(max(col - plot.col, 0), plot.cols - 1)] = X_TICK
        put(layout.axis_row, spine_col, CORNER + "".join(axis))

        # ---- x tick labels, centred, dropping any that would collide ----
        row = layout.label_row
        if row < layout.outer.row + layout.outer.rows:
            put(row, layout.outer.col, " " * layout.outer.cols)
            used = spine_col
            for col, text in zip(columns, xlabels, strict=True):
                start = col - len(text) // 2
                start = min(max(start, plot.col), right_edge - len(text))
                if start <= used:
                    continue
                put(row, start, text)
                used = start + len(text)

            # The x label claims the tail of the row only if it is still free.
            if xlabel and used + 2 + len(xlabel) <= right_edge:
                put(row, right_edge - len(xlabel), xlabel)

    out.append("\x1b[0m")
    return "".join(out)
