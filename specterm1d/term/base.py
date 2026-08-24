"""The renderer boundary.

Every backend consumes the same RGBA buffer produced by ``plot.SpectrumPlot``
and differs only in how it gets those pixels onto the screen. This is what
keeps the fallback cheap: there is one plot model, so axes, ticks, labels,
error bands and fit overlays reach every backend identically.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class CellRect:
    """A rectangle in terminal cells. Row and column are 0-based."""

    row: int
    col: int
    rows: int
    cols: int


class Renderer(Protocol):
    name: str

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        """Pixel (width, height) the figure should be rendered at."""
        ...

    def draw(self, rgba: np.ndarray, rect: CellRect) -> None:
        ...

    def teardown(self) -> None:
        ...
