"""The persistent matplotlib figure and the geometry helpers around it.

One Figure is created and mutated in place; rebuilding it per keystroke is
what makes naive terminal plotters feel sluggish. Everything here is a pure
function of its inputs, so it is testable without a terminal.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from specterm1d import theme
from specterm1d.spec import Spec


@dataclass(frozen=True)
class Chrome:
    """Axis decoration scaled to the pixel budget."""

    fontsize: float
    ticks: int | None          # None leaves matplotlib's own locator alone
    tick_len: float
    pad: float
    margins: tuple[float, float, float, float]   # left, right, top, bottom
    title: bool
    xlabel: bool
    ylabel: bool
    minor_ticks: bool
    frame: bool = True         # False strips ticks and spines entirely

    def with_text_room(self, fontsize_px: float,
                       width_px: float, height_px: float) -> "Chrome":
        """The same decoration, with margins guaranteed to hold the labels.

        fontsize, tick_len and pad are in points, so raising the figure's dpi
        scales them - and the line widths, and everything else matplotlib
        measures in points - in pixels for free. The margins are the one thing
        that cannot follow, because they are fractions of the figure.

        They rarely need to. A fraction of a large figure is already far more
        room than the text asks for, so this is a floor rather than a scale:
        it binds only where the figure is small enough that the type would
        otherwise run off the edge, and leaves the tuned values alone
        everywhere else.
        """
        left, right, top, bottom = self.margins
        left = min(max(left, LEFT_EMS * fontsize_px / width_px), MARGIN_CAP)
        bottom = min(max(bottom, BOTTOM_EMS * fontsize_px / height_px), MARGIN_CAP)
        right = max(min(right, 1.0 - RIGHT_EMS * fontsize_px / width_px),
                    1.0 - MARGIN_CAP)
        top = max(min(top, 1.0 - TOP_EMS * fontsize_px / height_px),
                  1.0 - MARGIN_CAP)
        return replace(self, margins=(left, right, top, bottom))


# The text backend renders two pixels per terminal column and two per row, so
# an 80x24 terminal asks for a 160x48 figure. Default 9pt labels are 12.5 px
# tall there - over a quarter of the figure - and collide into unreadable mush.
# Below roughly 500 px the whole chrome has to shrink with the figure, and the
# y label goes first because horizontal pixels are the scarcest.
#
# CHROME_FULL's right margin is 0.975 rather than 0.99 because the latter
# clipped the final x tick label, rendering 9000 as 900.
CHROME_FULL = Chrome(9, None, 3.5, 3.5, (0.09, 0.975, 0.93, 0.12),
                     True, True, True, True)
CHROME_SMALL = Chrome(5, 4, 1.5, 1.0, (0.13, 0.995, 0.90, 0.26),
                      True, True, False, False)
# top=0.99 clipped the highest y tick label in half and right=0.995 clipped
# the last x label, so TINY reserves a little of both edges for them.
CHROME_TINY = Chrome(4, 3, 1.0, 0.8, (0.17, 0.96, 0.93, 0.17),
                     False, False, False, False)

# Nothing but data. Used when the terminal draws the axis decoration itself,
# where matplotlib's own labels would be a 5.6 px smear across three cells.
CHROME_BARE = Chrome(4, 3, 0.0, 0.0, (0.0, 1.0, 1.0, 0.0),
                     False, False, False, False, frame=False)


# How tall a plot label should be next to the terminal's own text. A glyph
# occupies roughly three quarters of a cell - the rest is line spacing - so
# matching the two exactly would mean 0.75. The labels sit a notch above
# that: a rendered digit is antialiased into a handful of pixels where the
# terminal's own is hinted, and reads smaller at the same nominal height.
#
# This and CHROME_FULL.fontsize move together. The dpi chosen below is
# ``fraction * cell * 72 / fontsize``, so raising both by the same factor
# leaves the dpi - and with it every tick length, pad and line width in
# pixels - where it was, and grows only the type.
LABEL_CELL_FRACTION = 0.84

# The room each margin needs, in multiples of the label height: the y side
# holds a few digits plus the axis label, the x side two stacked lines, and
# the far edges half of whatever tick label overhangs them.
LEFT_EMS, BOTTOM_EMS, RIGHT_EMS, TOP_EMS = 4.5, 3.0, 1.2, 1.8

# No single margin may take more than this share of the figure, so a wildly
# wrong cell size cannot leave the axes with nothing to draw in.
MARGIN_CAP = 0.33

# The dpi a fixed 9 pt label was tuned against, and the range outside which a
# reported cell size is not worth believing.
BASE_DPI = 100
MIN_DPI, MAX_DPI = 72, 600


def chrome_for(width_px: float, height_px: float) -> Chrome:
    """Pick the decoration that fits a figure of this size."""
    if width_px >= 500 and height_px >= 240:
        return CHROME_FULL
    if width_px >= 150 and height_px >= 70:
        return CHROME_SMALL
    return CHROME_TINY


def tick_values(lo: float, hi: float, n: int) -> tuple[list[float], list[str]]:
    """Round tick positions inside ``[lo, hi]``, with formatted labels.

    A pure function of the limits - no figure and no axis - because the
    terminal chrome needs the same numbers matplotlib would have drawn, but
    has to place them in cells rather than pixels.
    """
    if not np.isfinite([lo, hi]).all() or hi <= lo:
        return [lo], [_format_tick(lo, 0)]

    values = MaxNLocator(max(n, 2)).tick_values(lo, hi)
    values = [float(v) for v in values if lo <= v <= hi]
    if not values:
        values = [lo, hi]

    span = hi - lo
    if all(v == round(v) for v in values) and max(abs(v) for v in values) < 1e7:
        decimals = 0
    else:
        step = span / max(len(values), 1)
        decimals = int(np.clip(-np.floor(np.log10(step)) + 1, 0, 6))

    labels = [_format_tick(v, decimals) for v in values]
    if max(len(text) for text in labels) > 8:
        labels = [f"{v:.3g}" for v in values]
    return values, labels


def _format_tick(value: float, decimals: int) -> str:
    text = f"{value:.{decimals}f}"
    # "-0" and "-0.00" are arithmetic noise, not a measurement.
    return text[1:] if text.lstrip("-0.") == "" and text.startswith("-") else text


def masked_flux(spec: Spec) -> np.ndarray:
    """Flux with masked pixels set to nan so the drawn line breaks there.

    Without this a chip gap is bridged by a straight segment that reads as a
    real feature.
    """
    y = spec.flux.astype(float, copy=True)
    bad = ~spec.good
    if bad.any():
        y[bad] = np.nan
    return y


def decimate(x, y, xmin: float, xmax: float, ncols: int, threshold: int = 4):
    """Reduce an over-sampled curve to per-column min/max pairs.

    Above ``threshold * ncols`` points in view, each output column contributes
    two vertices - the bin minimum and maximum - which is visually identical to
    drawing every point but costs a fixed ``2 * ncols`` vertices.

    Uses ``np.fmin``/``np.fmax`` rather than ``np.minimum``/``np.maximum``:
    the fmin family skips nans inside a bin and yields nan only for an all-nan
    bin, so one bad pixel does not blank its whole column while a fully masked
    region still breaks the line.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    if x.size == 0 or xmax < x[0] or xmin > x[-1]:
        return x[:0], y[:0]

    # One pixel of padding each side so the curve reaches the axes edges.
    i0 = max(int(np.searchsorted(x, xmin, side="left")) - 1, 0)
    i1 = min(int(np.searchsorted(x, xmax, side="right")) + 1, x.size)
    xs, ys = x[i0:i1], y[i0:i1]

    if xs.size == 0:
        return xs, ys
    if ncols <= 0 or xs.size <= threshold * ncols:
        return xs, ys

    edges = np.unique(np.linspace(0, xs.size, ncols + 1).astype(int))
    starts = edges[:-1]
    lo = np.fmin.reduceat(ys, starts)
    hi = np.fmax.reduceat(ys, starts)

    xd = np.repeat(xs[starts], 2)
    yd = np.empty(2 * lo.size, dtype=float)
    yd[0::2] = lo
    yd[1::2] = hi
    return xd, yd


def autoscale(spec: Spec, xlim: tuple[float, float], zero_base: bool = False,
              pad: float = 0.05) -> tuple[float, float]:
    """Flux limits over the good pixels inside ``xlim``.

    Masked pixels are excluded deliberately: bad columns and chip gaps
    otherwise dominate the scaling and flatten the real spectrum.
    """
    lo_x, hi_x = xlim
    sel = spec.good & (spec.wave >= lo_x) & (spec.wave <= hi_x)
    values = spec.flux[sel]
    values = values[np.isfinite(values)]

    if values.size == 0:
        return (0.0, 1.0)

    lo = 0.0 if zero_base else float(values.min())
    hi = float(values.max())
    if hi <= lo:
        hi = lo + 1.0
    margin = (hi - lo) * pad
    return (lo if zero_base else lo - margin, hi + margin)


@dataclass
class PlotRequest:
    """Everything the figure needs for one frame."""

    spec: Spec
    xlim: tuple[float, float]
    ylim: tuple[float, float]
    show_sigma: bool = False
    show_mask: bool = False
    overlays: tuple[str, ...] = ()
    histogram: bool = False
    title: str = ""
    xlabel: str = ""
    ylabel: str = ""
    markers: tuple[float, ...] = ()
    cursor: tuple[float, float | None] | None = None
    cursor_crosshair: bool = False
    fits: tuple[tuple[np.ndarray, np.ndarray], ...] = field(default_factory=tuple)


class SpectrumPlot:
    """A persistent Agg figure rendered to an RGBA buffer."""

    def __init__(self, width_px: int, height_px: int, dpi: int = BASE_DPI,
                 bare: bool = False):
        self.dpi = dpi
        self._base_dpi = dpi
        self._cell_px: float | None = None
        self._bare = bare
        self.fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi,
                          facecolor=theme.active().figure)
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        self._style_axes(self.chrome())

    @property
    def cell_px(self) -> float | None:
        """Height of one terminal cell, in the same pixels the figure uses.

        The figure is rendered at the terminal's pixel budget and shown at
        1:1, so matching the chrome to this makes plot labels the height of
        the terminal's own text - on a HiDPI display too, where the terminal
        reports twice the pixels for the same visible area. None (unreported,
        or a window with no cells) keeps the original dpi.
        """
        return self._cell_px

    @cell_px.setter
    def cell_px(self, value: float | None) -> None:
        value = float(value) if value else None
        if value == self._cell_px:
            return
        self._cell_px = value
        width_px, height_px = self.fig.get_size_inches() * self.dpi
        if value is None:
            self.dpi = self._base_dpi
        else:
            target = LABEL_CELL_FRACTION * value * 72 / CHROME_FULL.fontsize
            self.dpi = float(min(max(target, MIN_DPI), MAX_DPI))
        self.fig.set_dpi(self.dpi)
        # The renderer asked for a pixel count, not an area: hold it steady.
        self.resize(width_px, height_px)
        self._style_axes(self.chrome())

    @property
    def bare(self) -> bool:
        """True when the terminal paints the axis decoration itself.

        Setting it restyles immediately rather than at the next render: the
        axes position is what the cell -> data cursor mapping reads, so a
        flag that led the styling by a frame would silently misplace clicks.
        """
        return self._bare

    @bare.setter
    def bare(self, value: bool) -> None:
        self._bare = bool(value)
        self._style_axes(self.chrome())

    def chrome(self) -> Chrome:
        if self._bare:
            return CHROME_BARE
        width_px, height_px = self.fig.get_size_inches() * self.dpi
        chrome = chrome_for(width_px, height_px)
        return chrome.with_text_room(chrome.fontsize * self.dpi / 72,
                                     width_px, height_px)

    def _style_axes(self, chrome: Chrome) -> None:
        ax = self.ax
        palette = theme.active()
        # Restated every frame rather than at construction, so switching the
        # theme under a live figure repaints it.
        self.fig.set_facecolor(palette.figure)
        ax.set_facecolor(palette.plot)
        for spine in ax.spines.values():
            spine.set_visible(chrome.frame)
            spine.set_color(palette.spine)
            spine.set_linewidth(0.8 if chrome.minor_ticks else 0.5)
        # The grid goes with the frame. In bare mode the terminal draws the
        # tick marks from its own tick values, which need not be the ones
        # matplotlib's locator picked, and a grid ruled somewhere else than
        # the ticks it belongs to reads as a fault rather than a style.
        if chrome.frame and palette.grid:
            ax.set_axisbelow(palette.grid_below)
            # Kwargs alongside a false first argument turn the grid on with a
            # warning, so the off case has to be a separate call.
            ax.grid(True, color=palette.grid_color, linestyle=palette.grid_style,
                    linewidth=palette.grid_width, alpha=palette.grid_alpha)
        else:
            ax.grid(False)

        if not chrome.frame:
            ax.tick_params(which="both", left=False, right=False, top=False,
                           bottom=False, labelleft=False, labelbottom=False)
            # Full bleed: the axes are the figure, which also makes
            # ``ax.get_position()`` the identity box so the existing cell ->
            # data cursor mapping keeps working unchanged.
            self.fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
            return
        # color and labelcolor split apart: xgterm draws cyan tick marks
        # against yellow numbers, which one ``colors=`` cannot express.
        ax.tick_params(color=palette.spine, labelcolor=palette.tick_label,
                       labelsize=chrome.fontsize, which="both",
                       length=chrome.tick_len, width=0.5, pad=chrome.pad)
        ax.xaxis.label.set_color(palette.text)
        ax.yaxis.label.set_color(palette.text)
        ax.title.set_color(palette.text)
        if chrome.minor_ticks:
            ax.minorticks_on()
        if chrome.ticks is not None:
            ax.xaxis.set_major_locator(MaxNLocator(chrome.ticks))
            ax.yaxis.set_major_locator(MaxNLocator(chrome.ticks))
        left, right, top, bottom = chrome.margins
        self.fig.subplots_adjust(left=left, right=right, top=top, bottom=bottom)

    @staticmethod
    def _elide(text: str, keep: int) -> str:
        """Drop the middle, favouring the tail so a trailing label survives."""
        if len(text) <= keep:
            return text
        head = max(int((keep - 1) * 0.4), 1)
        tail = max(keep - 1 - head, 1)
        return f"{text[:head]}\u2026{text[-tail:]}"

    def _title_width_px(self, text: str) -> float:
        """Rendered width of a title-sized string, in device pixels."""
        artist = self.ax.title
        saved = artist.get_text()
        artist.set_text(text)
        try:
            width = artist.get_window_extent(
                self.fig.canvas.get_renderer()).width
        finally:
            artist.set_text(saved)
        return float(width)

    def fit_title(self, text: str) -> str:
        """Elide the middle of a title too wide for the axes.

        pypeit spec1d basenames run to about ninety characters before the
        object label is appended, which overruns the axes and gets clipped -
        losing the label, the part that says what you are looking at.

        The width is measured with matplotlib rather than estimated from font
        metrics: an estimate put the cut-off within one character of a real
        pypeit title and let it through still clipped.
        """
        if not text:
            return text
        limit_px = (self.fig.get_size_inches()[0] * self.dpi
                    * self.ax.get_position().width)
        width = self._title_width_px(text)
        if width <= limit_px:
            return text

        keep = max(int(len(text) * limit_px / width), 12)
        out = self._elide(text, keep)
        while keep > 13 and self._title_width_px(out) > limit_px:
            keep -= 2
            out = self._elide(text, keep)
        return out

    def resize(self, width_px: int, height_px: int) -> None:
        self.fig.set_size_inches(width_px / self.dpi, height_px / self.dpi,
                                 forward=True)

    def draw(self, req: PlotRequest) -> None:
        """Paint one frame onto the canvas. No buffer copy.

        Split out of render() because a GUI canvas is on screen the moment it
        is drawn, so copying 3.8 MB of RGBA out of it every frame buys nothing.
        """
        ax = self.ax
        ax.clear()
        chrome = self.chrome()
        self._style_axes(chrome)
        palette = theme.active()

        spec = req.spec
        ncols = int(self.fig.get_size_inches()[0] * self.dpi)
        y = masked_flux(spec)
        xd, yd = decimate(spec.wave, y, req.xlim[0], req.xlim[1], ncols)

        drawstyle = "steps-mid" if req.histogram else "default"
        ax.plot(xd, yd, lw=0.8, color=palette.line, drawstyle=drawstyle)

        if req.show_sigma and spec.sigma is not None:
            sig = spec.sigma.astype(float, copy=True)
            sig[~np.isfinite(sig)] = np.nan
            _, lo = decimate(spec.wave, y - sig, req.xlim[0], req.xlim[1], ncols)
            _, hi = decimate(spec.wave, y + sig, req.xlim[0], req.xlim[1], ncols)
            ax.fill_between(xd, lo, hi, color=palette.sigma, alpha=0.45,
                            linewidth=0)

        if req.show_mask:
            bad = ~spec.good
            if bad.any():
                ax.vlines(spec.wave[bad], req.ylim[0], req.ylim[1],
                          color=palette.mask, alpha=0.25, linewidth=0.5)

        for i, name in enumerate(req.overlays):
            arr = spec.overlays.get(name)
            if arr is None:
                continue
            _, od = decimate(spec.wave, arr, req.xlim[0], req.xlim[1], ncols)
            ax.plot(xd, od, lw=0.7,
                    color=palette.overlay[i % len(palette.overlay)], label=name)
        # In bare mode the legend would be the same unreadable smear as the
        # tick labels; the terminal chrome paints it on the title row instead.
        if chrome.frame and req.overlays and ax.get_legend_handles_labels()[0]:
            legend = ax.legend(loc="upper right", fontsize=chrome.fontsize,
                                framealpha=0.3)
            for text in legend.get_texts():
                text.set_color(palette.text)

        for fx, fy in req.fits:
            ax.plot(fx, fy, lw=1.0, color=palette.fit)

        for xm in req.markers:
            ax.axvline(xm, color=palette.cursor, lw=0.7, alpha=0.6)
        if req.cursor is not None:
            ax.axvline(req.cursor[0], color=palette.cursor, lw=0.7, alpha=0.6)
            if req.cursor_crosshair and req.cursor[1] is not None:
                ax.axhline(req.cursor[1], color=palette.cursor, lw=0.7, alpha=0.6)

        ax.set_xlim(*req.xlim)
        ax.set_ylim(*req.ylim)
        ax.set_xlabel(req.xlabel if chrome.xlabel else "",
                      fontsize=chrome.fontsize)
        ax.set_ylabel(req.ylabel if chrome.ylabel else "",
                      fontsize=chrome.fontsize)
        # Explicit pad: matplotlib's default 6pt title pad is 8 px, which at
        # block-glyph scale pushes the title off the top of the figure.
        ax.set_title(self.fit_title(req.title) if chrome.title else "",
                     fontsize=chrome.fontsize + 1, pad=chrome.pad + 1.0)

        self.fig.canvas.draw()

    def render(self, req: PlotRequest) -> np.ndarray:
        """Draw, then hand back an independent copy of the frame.

        A copy, not a view: buffer_rgba() aliases the renderer's own memory,
        so any frame a caller is still holding would mutate on the next
        render. The text backend diffs against the previous frame.
        """
        self.draw(req)
        return np.array(self.fig.canvas.buffer_rgba(), dtype=np.uint8)
