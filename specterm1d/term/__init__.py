"""Terminal backends. Importing this registers every available renderer."""
from specterm1d.term.base import CellRect, Renderer  # noqa: F401
from specterm1d.term.caps import (  # noqa: F401
    TerminalCaps, choose_renderer, detect, register_renderer,
)
from specterm1d.term.halfblock import HalfblockRenderer

register_renderer(
    "halfblock",
    lambda caps, out: HalfblockRenderer(out=out, truecolor=caps.truecolor),
)

__all__ = [
    "CellRect", "Renderer", "TerminalCaps",
    "choose_renderer", "detect", "register_renderer", "HalfblockRenderer",
]
