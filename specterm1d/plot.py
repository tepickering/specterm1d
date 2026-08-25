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

from specterm1d.spec import Spec

# A restrained palette: few enough colours that the sixel backend can quantize
# to a fixed 16-entry table without visible loss.
COLOR_BG = "#101418"
COLOR_FG = "#c8d2dc"
COLOR_LINE = "#4aa3ff"
COLOR_SIGMA = "#2f5d8a"
COLOR_MASK = "#c8503c"
COLOR_OVERLAY = ("#e0a030", "#50b070", "#a070d0")


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

    def __init__(self, width_px: int, height_px: int, dpi: int = 100):
        self.dpi = dpi
        self.fig = Figure(figsize=(width_px / dpi, height_px / dpi), dpi=dpi,
                          facecolor=COLOR_BG)
        FigureCanvasAgg(self.fig)
        self.ax = self.fig.add_subplot(111)
        self._style_axes()
        # right=0.99 clipped the final x tick label ('9000' rendering as
        # '900'); leave room for half a label at each end.
        self.fig.subplots_adjust(left=0.09, right=0.975, top=0.93, bottom=0.12)

    def _style_axes(self) -> None:
        ax = self.ax
        ax.set_facecolor(COLOR_BG)
        for spine in ax.spines.values():
            spine.set_color(COLOR_FG)
        ax.tick_params(colors=COLOR_FG, labelsize=8, which="both")
        ax.xaxis.label.set_color(COLOR_FG)
        ax.yaxis.label.set_color(COLOR_FG)
        ax.title.set_color(COLOR_FG)
        ax.minorticks_on()

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
        self._style_axes()

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
        if req.overlays and ax.get_legend_handles_labels()[0]:
            legend = ax.legend(loc="upper right", fontsize=7, framealpha=0.3)
            for text in legend.get_texts():
                text.set_color(COLOR_FG)

        for fx, fy in req.fits:
            ax.plot(fx, fy, lw=1.0, color=COLOR_MASK)

        for xm in req.markers:
            ax.axvline(xm, color=COLOR_FG, lw=0.7, alpha=0.6)

        ax.set_xlim(*req.xlim)
        ax.set_ylim(*req.ylim)
        ax.set_xlabel(req.xlabel)
        ax.set_ylabel(req.ylabel)
        ax.set_title(self.fit_title(req.title), fontsize=9)

        self.fig.canvas.draw()
        # A copy, not a view: buffer_rgba() aliases the renderer's own memory,
        # so any frame a caller is still holding would mutate on the next
        # render. The halfblock backend diffs against the previous frame.
        return np.array(self.fig.canvas.buffer_rgba(), dtype=np.uint8)
