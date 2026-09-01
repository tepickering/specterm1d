"""Quadrant backend: four subpixels per cell where halfblock gets two.

Each cell becomes one of eight glyphs from Block Elements, splitting the cell
on a 2x2 grid and painting one half of the split in the foreground colour and
the other in the background. The figure is therefore rendered at
``2*cols x 2*rows`` - twice the columns halfblock gets, which is the axis that
matters for a spectrum, where the complaint is always how many pixels are
being binned into one screen column.

The cost is that colour is no longer exact. Halfblock's two subpixels have a
colour each, so its cells reproduce the figure perfectly; a 2x2 cell has four
subpixels and still only two colours, so the four are partitioned into two
groups and each group takes its mean. That is lossless for the case that
dominates a spectrum plot - a curve over a flat background is two colours -
and degrades only where the curve, the sigma band and an overlay all meet
inside one cell.

The partition is chosen by exhaustive search. Four subpixels admit eight
distinct two-way splits, so the optimal one is found by trying all of them
rather than approximated, and it costs eight passes over a grid that is a few
thousand cells.

Glyph support is the reason halfblock stays reachable through
``--renderer halfblock``: U+2596..U+259F are Unicode 1.0 and present in every
terminal font worth the name (SF Mono, Menlo and DejaVu Sans Mono among them),
but Andale Mono, to pick one counter-example on macOS, has the half blocks and
not the quadrants.
"""
from __future__ import annotations

import numpy as np

from specterm1d.term.halfblock import HalfblockRenderer

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


def _group_error(sub: np.ndarray, idx: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """Mean colour of a subpixel group and its squared error, per cell."""
    group = sub[:, :, idx, :]
    mean = group.mean(axis=2)
    error = np.square(group - mean[:, :, None, :]).sum(axis=(2, 3))
    return mean, error


def cells_from_rgba(rgba: np.ndarray) -> np.ndarray:
    """(H, W, 4) pixels -> (H//2, W//2, 7) cells of [fgRGB, bgRGB, glyph].

    The seventh channel indexes :data:`GLYPHS`, which is what
    ``halfblock.render_cells`` reads to draw a cell's shape.
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


class QuadrantRenderer(HalfblockRenderer):
    """Halfblock with a 2x2 cell. Everything but the packing is inherited."""

    name = "quadrant"
    glyphs = GLYPHS
    pack = staticmethod(cells_from_rgba)

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        return (cols * 2, rows * 2)
