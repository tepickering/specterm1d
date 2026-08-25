"""The persistent matplotlib figure and the geometry helpers around it.

One Figure is created and mutated in place; rebuilding it per keystroke is
what makes naive terminal plotters feel sluggish. Everything here is a pure
function of its inputs, so it is testable without a terminal.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from specterm1d.spec import Spec

# A restrained palette: few enough colours that the sixel backend can quantize
# to a fixed 16-entry table without visible loss.
COLOR_BG = "#101418"
COLOR_FG = "#c8d2dc"
COLOR_LINE = "#4aa3ff"
COLOR_SIGMA = "#2f5d8a"
COLOR_MASK = "#c8503c"
COLOR_OVERLAY = ("#e0a030", "#50b070", "#a070d0")


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


# The halfblock backend renders one pixel per terminal column and two per row,
# so an 80x24 terminal asks for an 80x44 figure. Default 9pt labels are 12.5 px
# tall there - over a quarter of the figure - and collide into unreadable mush.
# Below roughly 500 px the whole chrome has to shrink with the figure, and the
# y label goes first because horizontal pixels are the scarcest.
#
# CHROME_FULL's right margin is 0.975 rather than 0.99 because the latter
# clipped the final x tick label, rendering 9000 as 900.
CHROME_FULL = Chrome(8, None, 3.5, 3.5, (0.09, 0.975, 0.93, 0.12),
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
    fits: tuple[tuple[np.ndarray, np.ndarray], ...] = field(default_factory=tuple)


class SpectrumPlot:
    """A persistent Agg figure rendered to an RGBA buffer."""

    def __init__(self, width_px: int, height_px: int, dpi: int = 100,
                 bare: bool = False):
        self.dpi = dpi
        self._bare = bare
        self.fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi,
                          facecolor=COLOR_BG)
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
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
        return chrome_for(width_px, height_px)

    def _style_axes(self, chrome: Chrome) -> None:
        ax = self.ax
        ax.set_facecolor(COLOR_BG)
        for spine in ax.spines.values():
            spine.set_visible(chrome.frame)
            spine.set_color(COLOR_FG)
            spine.set_linewidth(0.8 if chrome.minor_ticks else 0.5)
        if not chrome.frame:
            ax.tick_params(which="both", left=False, right=False, top=False,
                           bottom=False, labelleft=False, labelbottom=False)
            # Full bleed: the axes are the figure, which also makes
            # ``ax.get_position()`` the identity box so the existing cell ->
            # data cursor mapping keeps working unchanged.
            self.fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
            return
        ax.tick_params(colors=COLOR_FG, labelsize=chrome.fontsize, which="both",
                       length=chrome.tick_len, width=0.5, pad=chrome.pad)
        ax.xaxis.label.set_color(COLOR_FG)
        ax.yaxis.label.set_color(COLOR_FG)
        ax.title.set_color(COLOR_FG)
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

    def render(self, req: PlotRequest) -> np.ndarray:
        ax = self.ax
        ax.clear()
        chrome = self.chrome()
        self._style_axes(chrome)

        spec = req.spec
        ncols = int(self.fig.get_size_inches()[0] * self.dpi)
        y = masked_flux(spec)
        xd, yd = decimate(spec.wave, y, req.xlim[0], req.xlim[1], ncols)

        drawstyle = "steps-mid" if req.histogram else "default"
        ax.plot(xd, yd, lw=0.8, color=COLOR_LINE, drawstyle=drawstyle)

        if req.show_sigma and spec.sigma is not None:
            sig = spec.sigma.astype(float, copy=True)
            sig[~np.isfinite(sig)] = np.nan
            _, lo = decimate(spec.wave, y - sig, req.xlim[0], req.xlim[1], ncols)
            _, hi = decimate(spec.wave, y + sig, req.xlim[0], req.xlim[1], ncols)
            ax.fill_between(xd, lo, hi, color=COLOR_SIGMA, alpha=0.45,
                            linewidth=0)

        if req.show_mask:
            bad = ~spec.good
            if bad.any():
                ax.vlines(spec.wave[bad], req.ylim[0], req.ylim[1],
                          color=COLOR_MASK, alpha=0.25, linewidth=0.5)

        for i, name in enumerate(req.overlays):
            arr = spec.overlays.get(name)
            if arr is None:
                continue
            _, od = decimate(spec.wave, arr, req.xlim[0], req.xlim[1], ncols)
            ax.plot(xd, od, lw=0.7, color=COLOR_OVERLAY[i % len(COLOR_OVERLAY)],
                    label=name)
        # In bare mode the legend would be the same unreadable smear as the
        # tick labels; the terminal chrome paints it on the title row instead.
        if chrome.frame and req.overlays and ax.get_legend_handles_labels()[0]:
            legend = ax.legend(loc="upper right", fontsize=chrome.fontsize,
                                framealpha=0.3)
            for text in legend.get_texts():
                text.set_color(COLOR_FG)

        for fx, fy in req.fits:
            ax.plot(fx, fy, lw=1.0, color=COLOR_MASK)

        for xm in req.markers:
            ax.axvline(xm, color=COLOR_FG, lw=0.7, alpha=0.6)

        ax.set_xlim(*req.xlim)
        ax.set_ylim(*req.ylim)
        ax.set_xlabel(req.xlabel if chrome.xlabel else "",
                      fontsize=chrome.fontsize)
        ax.set_ylabel(req.ylabel if chrome.ylabel else "",
                      fontsize=chrome.fontsize)
        # Explicit pad: matplotlib's default 6pt title pad is 8 px, which at
        # halfblock scale pushes the title off the top of the figure.
        ax.set_title(self.fit_title(req.title) if chrome.title else "",
                     fontsize=chrome.fontsize + 1, pad=chrome.pad + 1.0)

        self.fig.canvas.draw()
        # A copy, not a view: buffer_rgba() aliases the renderer's own memory,
        # so any frame a caller is still holding would mutate on the next
        # render. The halfblock backend diffs against the previous frame.
        return np.array(self.fig.canvas.buffer_rgba(), dtype=np.uint8)
