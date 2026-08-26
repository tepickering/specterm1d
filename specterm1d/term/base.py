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

from specterm1d.term.input import Key


@dataclass(frozen=True)
class CellRect:
    """A rectangle in terminal cells. Row and column are 0-based."""

    row: int
    col: int
    rows: int
    cols: int


@dataclass(frozen=True)
class Motion:
    """Pointer position in data coordinates.

    A matplotlib motion event carries ``event.xdata`` directly, so an
    interactive backend can report exactly where the pointer is rather than
    which terminal cell it landed in.
    """

    x: float
    y: float


# What an interactive backend's poll() yields. Key is the terminal's own key
# type, unchanged, which is what lets window keys reach Session.handle() with
# no translation layer.
GuiEvent = Key | Motion


class Renderer(Protocol):
    name: str

    # True when the backend's pixels are too coarse for rendered text and the
    # terminal should paint the axis decoration as glyphs instead.
    text_chrome: bool = False

    # True when the backend owns its own window and event loop. The session
    # then takes keys from poll() rather than the terminal, prints text rather
    # than painting a status line, and never enters raw mode.
    interactive: bool = False

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        """Pixel (width, height) the figure should be rendered at."""
        ...

    def draw(self, rgba: np.ndarray, rect: CellRect) -> None:
        ...

    def teardown(self) -> None:
        ...

    # Interactive backends only. Callers reach these with getattr(..., default)
    # so no terminal backend has to grow them.

    closed: bool                                # the user closed the window

    def attach(self, plot) -> None:
        """Adopt the figure and open the window."""
        ...

    def poll(self) -> list[GuiEvent]:
        """Drain the queued window events."""
        ...

    def pump(self) -> None:
        """Let the toolkit run its event loop."""
        ...

    def set_title(self, text: str) -> None:
        ...
