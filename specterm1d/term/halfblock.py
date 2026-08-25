"""Halfblock backend: works on any terminal, including those with no
inline-graphics protocol at all.

Each cell is U+2580 UPPER HALF BLOCK with the top source pixel as foreground
and the bottom as background, so one cell carries two pixels and the figure is
rendered at ``cols x 2*rows``. Truecolor where available; Terminal.app never
gained 24-bit colour, so there is an xterm-256 path.

Frames are diffed against the previous one. A 200x50 grid is roughly 200 KB of
ANSI when written in full, which is far too much per keystroke.
"""
from __future__ import annotations

import sys

import numpy as np

from specterm1d.term.base import CellRect

UPPER_HALF = "▀"

# xterm-256: indices 16..231 are a 6x6x6 cube on these levels,
# 232..255 are a 24-step grey ramp.
_CUBE_LEVELS = np.array([0, 95, 135, 175, 215, 255], dtype=np.int16)
_GREY_LEVELS = np.arange(24, dtype=np.int16) * 10 + 8


def cells_from_rgba(rgba: np.ndarray) -> np.ndarray:
    """(H, W, 4) pixels -> (H//2, W, 6) cells of [fgRGB, bgRGB]."""
    usable = (rgba.shape[0] // 2) * 2
    rgb = rgba[:usable, :, :3]
    return np.concatenate([rgb[0::2], rgb[1::2]], axis=-1)


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


def render_cells(cells: np.ndarray, prev: np.ndarray | None = None, *,
                 truecolor: bool = True, origin: tuple[int, int] = (1, 1)) -> str:
    """Turn a cell grid into escape sequences, emitting only changed runs.

    ``origin`` is the 1-based (row, col) of the grid's top-left cell, matching
    the CSI cursor-position convention.
    """
    rows, cols, _ = cells.shape
    if prev is not None and prev.shape != cells.shape:
        prev = None   # a resize invalidates the whole previous frame

    codes = None
    if not truecolor:
        codes = quantize_256(cells.reshape(rows, cols, 2, 3))

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
                out.append(UPPER_HALF)

    out.append("\x1b[0m")
    return "".join(out)


class HalfblockRenderer:
    name = "halfblock"
    text_chrome = True

    def __init__(self, out=None, truecolor: bool = True):
        self.out = out if out is not None else sys.stdout
        self.truecolor = truecolor
        self._prev: np.ndarray | None = None

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        return (cols, rows * 2)

    def draw(self, rgba: np.ndarray, rect: CellRect) -> None:
        cells = cells_from_rgba(rgba)[: rect.rows, : rect.cols]
        text = render_cells(cells, self._prev, truecolor=self.truecolor,
                            origin=(rect.row + 1, rect.col + 1))
        self.out.write(text)
        self.out.flush()
        self._prev = cells.copy()

    def teardown(self) -> None:
        self._prev = None
