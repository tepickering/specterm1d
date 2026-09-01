"""The text backend: a figure drawn as coloured block glyphs.

This is what runs wherever neither an inline-graphics protocol nor a window is
available - ssh with no display, tmux over ssh - and it works on any terminal
that can print Unicode and set a colour.

Each cell becomes one of eight glyphs from Block Elements that split it on a
2x2 grid, one group of subpixels painted in the foreground colour and the rest
in the background, so the figure is rendered at ``2*cols x 2*rows``. Four
subpixels sharing two colours is an approximation, and a cheap one for this
plot: measured against a full-resolution render of a UVES order, the coarse
grid accounts for essentially all of the error and the colour for almost none,
because a curve over a flat background is two colours already.

The split is chosen by exhaustive search. Four subpixels admit eight distinct
two-way partitions, so the best one is found rather than approximated, and it
costs eight passes over a grid of a few thousand cells.

Truecolor where available; Terminal.app never gained 24-bit colour, so there
is an xterm-256 path.

Frames are diffed against the previous one. A 200x50 grid is roughly 200 KB of
ANSI when written in full, which is far too much per keystroke.
"""
from __future__ import annotations

import sys
from collections.abc import Sequence

import numpy as np

from specterm1d.term.base import CellRect

# Subpixel bit order: 1 = top-left, 2 = top-right, 4 = bottom-left. The
# bottom-right subpixel is always background, which is exactly what makes
# these eight masks the eight distinct partitions rather than sixteen
# colour-swapped duplicates.
GLYPHS = (
    " ",   # 0: nothing in the foreground
    "▘",   # 1: upper left
    "▝",   # 2: upper right
    "▀",   # 3: upper half
    "▖",   # 4: lower left
    "▌",   # 5: left half
    "▞",   # 6: upper right and lower left
    "▛",   # 7: everything but the lower right
)

# (foreground subpixels, background subpixels) for each glyph above.
_PARTITIONS = tuple(
    ([i for i in range(4) if mask >> i & 1],
     [i for i in range(4) if not mask >> i & 1])
    for mask in range(len(GLYPHS))
)

# xterm-256: indices 16..231 are a 6x6x6 cube on these levels,
# 232..255 are a 24-step grey ramp.
_CUBE_LEVELS = np.array([0, 95, 135, 175, 215, 255], dtype=np.int16)
_GREY_LEVELS = np.arange(24, dtype=np.int16) * 10 + 8


def quantize_256(rgb: np.ndarray) -> np.ndarray:
    """Map RGB triples to xterm-256 indices, preserving leading shape."""
    rgb16 = np.asarray(rgb, dtype=np.int16)

    cube_idx = np.abs(rgb16[..., None] - _CUBE_LEVELS).argmin(axis=-1)
    cube_err = np.abs(_CUBE_LEVELS[cube_idx] - rgb16).sum(axis=-1)
    cube_code = 16 + 36 * cube_idx[..., 0] + 6 * cube_idx[..., 1] + cube_idx[..., 2]

    mean = rgb16.mean(axis=-1)
    grey_idx = np.abs(mean[..., None] - _GREY_LEVELS).argmin(axis=-1)
    grey_err = np.abs(_GREY_LEVELS[grey_idx][..., None] - rgb16).sum(axis=-1)
    grey_code = 232 + grey_idx

    return np.where(grey_err < cube_err, grey_code, cube_code).astype(np.uint8)


def _group_error(sub: np.ndarray, idx: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Mean colour of a subpixel group and its squared error, per cell."""
    group = sub[:, :, idx, :]
    mean = group.mean(axis=2)
    error = np.square(group - mean[:, :, None, :]).sum(axis=(2, 3))
    return mean, error


def cells_from_rgba(rgba: np.ndarray) -> np.ndarray:
    """(H, W, 4) pixels -> (H//2, W//2, 7) cells of [fgRGB, bgRGB, glyph].

    The seventh channel indexes :data:`GLYPHS`, which is what
    :func:`render_cells` reads to draw a cell's shape.
    """
    height = (rgba.shape[0] // 2) * 2
    width = (rgba.shape[1] // 2) * 2
    rgb = rgba[:height, :width, :3].astype(np.float64)
    sub = np.stack([rgb[0::2, 0::2], rgb[0::2, 1::2],
                    rgb[1::2, 0::2], rgb[1::2, 1::2]], axis=2)

    means, errors = [], []
    for fg_idx, bg_idx in _PARTITIONS:
        bg, error = _group_error(sub, bg_idx)
        # An empty foreground is the blank cell: give it the background colour
        # so a run of blanks does not churn the foreground escape sequence.
        fg = bg
        if fg_idx:
            fg, fg_error = _group_error(sub, fg_idx)
            error = error + fg_error
        means.append(np.concatenate([fg, bg], axis=-1))
        errors.append(error)

    # Ties go to the lowest mask, so a cell of one flat colour comes out as a
    # blank rather than as an arbitrary split of identical halves.
    best = np.stack(errors).argmin(axis=0)
    colour = np.take_along_axis(np.stack(means), best[None, ..., None], axis=0)[0]

    cells = np.empty((*colour.shape[:2], 7), dtype=np.uint8)
    cells[..., :6] = np.rint(colour).clip(0, 255).astype(np.uint8)
    cells[..., 6] = best
    return cells


def render_cells(cells: np.ndarray, prev: np.ndarray | None = None, *,
                 truecolor: bool = True, origin: tuple[int, int] = (1, 1),
                 glyphs: Sequence[str] = GLYPHS) -> str:
    """Turn a cell grid into escape sequences, emitting only changed runs.

    ``cells`` is (rows, cols, 7): foreground RGB, background RGB, then an
    index into ``glyphs``. Carrying the shape as a channel rather than a
    second array is what keeps the diff one comparison - a cell that keeps its
    colours but changes shape simply differs.

    ``origin`` is the 1-based (row, col) of the grid's top-left cell, matching
    the CSI cursor-position convention.
    """
    rows, cols, _ = cells.shape
    if prev is not None and prev.shape != cells.shape:
        prev = None   # a resize invalidates the whole previous frame

    codes = None
    if not truecolor:
        codes = quantize_256(cells[..., :6].reshape(rows, cols, 2, 3))

    row0, col0 = origin
    out: list[str] = []

    for r in range(rows):
        if prev is None:
            changed = np.ones(cols, dtype=bool)
        else:
            changed = np.any(cells[r] != prev[r], axis=-1)
        if not changed.any():
            continue

        idx = np.flatnonzero(changed)
        breaks = np.flatnonzero(np.diff(idx) > 1) + 1
        for run in np.split(idx, breaks):
            out.append(f"\x1b[{row0 + r};{col0 + int(run[0])}H")
            last_fg = last_bg = None
            for c in run:
                if truecolor:
                    fg = tuple(int(v) for v in cells[r, c, 0:3])
                    bg = tuple(int(v) for v in cells[r, c, 3:6])
                    if fg != last_fg:
                        out.append("\x1b[38;2;%d;%d;%dm" % fg)
                        last_fg = fg
                    if bg != last_bg:
                        out.append("\x1b[48;2;%d;%d;%dm" % bg)
                        last_bg = bg
                else:
                    fg = int(codes[r, c, 0])
                    bg = int(codes[r, c, 1])
                    if fg != last_fg:
                        out.append(f"\x1b[38;5;{fg}m")
                        last_fg = fg
                    if bg != last_bg:
                        out.append(f"\x1b[48;5;{bg}m")
                        last_bg = bg
                out.append(glyphs[int(cells[r, c, 6])])

    out.append("\x1b[0m")
    return "".join(out)


class TextRenderer:
    name = "text"
    text_chrome = True

    def __init__(self, out=None, truecolor: bool = True):
        self.out = out if out is not None else sys.stdout
        self.truecolor = truecolor
        self._prev: np.ndarray | None = None

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        return (cols * 2, rows * 2)

    def draw(self, rgba: np.ndarray, rect: CellRect) -> None:
        cells = cells_from_rgba(rgba)[: rect.rows, : rect.cols]
        text = render_cells(cells, self._prev, truecolor=self.truecolor,
                            origin=(rect.row + 1, rect.col + 1))
        self.out.write(text)
        self.out.flush()
        self._prev = cells.copy()

    def teardown(self) -> None:
        self._prev = None
