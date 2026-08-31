"""iTerm2 inline-image backend.

Note: under tmux this sequence needs DCS passthrough wrapping. We do not
attempt that - detection prefers sixel under tmux, which tmux forwards
natively when built with --enable-sixel.
"""
from __future__ import annotations

import base64

import numpy as np

from specterm1d.term.kitty import NOMINAL_CELL, png_bytes


class ITerm2Renderer:
    name = "iterm2"
    inline_graphics = True

    def __init__(self, out, caps):
        self.out = out
        self.caps = caps

    def _cell_size(self) -> tuple[float, float]:
        if self.caps.pixel_width and self.caps.pixel_height and self.caps.cols \
                and self.caps.rows:
            return (self.caps.pixel_width / self.caps.cols,
                    self.caps.pixel_height / self.caps.rows)
        return NOMINAL_CELL

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        cell_w, cell_h = self._cell_size()
        return (max(int(cols * cell_w), 1), max(int(rows * cell_h), 1))

    def draw(self, rgba: np.ndarray, rect) -> None:
        payload = base64.b64encode(png_bytes(rgba)).decode("ascii")
        self.out.write(f"\x1b[{rect.row + 1};{rect.col + 1}H")
        self.out.write(
            f"\x1b]1337;File=inline=1;width={rect.cols};height={rect.rows};"
            f"preserveAspectRatio=0:{payload}\x07"
        )
        self.out.flush()

    def teardown(self) -> None:
        pass
