"""Terminal backends. Importing this registers every available renderer."""
from specterm1d.term.base import CellRect, Renderer
from specterm1d.term.caps import (
    TerminalCaps,
    choose_renderer,
    detect,
    register_renderer,
)
from specterm1d.term.gui import GuiRenderer
from specterm1d.term.iterm2 import ITerm2Renderer
from specterm1d.term.kitty import KittyRenderer
from specterm1d.term.sixel import SixelRenderer
from specterm1d.term.text import TextRenderer

register_renderer(
    "text",
    lambda caps, out: TextRenderer(out=out, truecolor=caps.truecolor),
)
register_renderer("kitty", lambda caps, out: KittyRenderer(out, caps))
register_renderer("iterm2", lambda caps, out: ITerm2Renderer(out, caps))
register_renderer("sixel", lambda caps, out: SixelRenderer(out, caps))
register_renderer("gui", lambda caps, out: GuiRenderer())

__all__ = [
    "CellRect",
    "GuiRenderer",
    "ITerm2Renderer",
    "KittyRenderer",
    "Renderer",
    "SixelRenderer",
    "TerminalCaps",
    "TextRenderer",
    "choose_renderer",
    "detect",
    "register_renderer",
]
