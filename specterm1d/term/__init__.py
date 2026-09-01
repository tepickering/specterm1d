"""Terminal backends. Importing this registers every available renderer."""
from specterm1d.term.base import CellRect, Renderer
from specterm1d.term.caps import (
    TerminalCaps,
    choose_renderer,
    detect,
    register_renderer,
)
from specterm1d.term.gui import GuiRenderer
from specterm1d.term.halfblock import HalfblockRenderer
from specterm1d.term.iterm2 import ITerm2Renderer
from specterm1d.term.kitty import KittyRenderer
from specterm1d.term.quadrant import QuadrantRenderer
from specterm1d.term.sixel import SixelRenderer

register_renderer(
    "halfblock",
    lambda caps, out: HalfblockRenderer(out=out, truecolor=caps.truecolor),
)
register_renderer(
    "quadrant",
    lambda caps, out: QuadrantRenderer(out=out, truecolor=caps.truecolor),
)
register_renderer("kitty", lambda caps, out: KittyRenderer(out, caps))
register_renderer("iterm2", lambda caps, out: ITerm2Renderer(out, caps))
register_renderer("sixel", lambda caps, out: SixelRenderer(out, caps))
register_renderer("gui", lambda caps, out: GuiRenderer())

__all__ = [
    "CellRect",
    "GuiRenderer",
    "HalfblockRenderer",
    "ITerm2Renderer",
    "KittyRenderer",
    "QuadrantRenderer",
    "Renderer",
    "SixelRenderer",
    "TerminalCaps",
    "choose_renderer",
    "detect",
    "register_renderer",
]
