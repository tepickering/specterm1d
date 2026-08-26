"""The GUI backend: a real matplotlib window for terminals with no inline
graphics protocol.

This is the ``xgterm`` model. The window owns interaction; the terminal is a
scrolling transcript. Nothing here imports a toolkit at module import time -
``open_window`` does that lazily, because importing a backend on a headless
box is exactly the case this module has to survive.
"""
from __future__ import annotations

from specterm1d.term.input import Key

_DIRECTIONS = ("left", "right", "up", "down")

# matplotlib's names on the left, the terminal's on the right. 'return' and
# 'enter' both arrive depending on the toolkit.
_NAMED = {
    "escape": "escape",
    "enter": "enter",
    "return": "enter",
    "backspace": "backspace",
    "pageup": "pageup",
    "pagedown": "pagedown",
}


def key_from_mpl(event_key: str | None) -> Key | None:
    """Map ``event.key`` onto the terminal's Key vocabulary.

    Pure, so the whole table is testable without a window. Returns None for
    anything the keymap has no meaning for - modified keys, function keys, and
    the None matplotlib reports when a keypress carries no character.
    """
    if not event_key:
        return None
    if event_key in _DIRECTIONS:
        return Key(event_key)
    if event_key.startswith("shift+"):
        rest = event_key[len("shift+"):]
        return Key(f"shift-{rest}") if rest in _DIRECTIONS else None
    if event_key in _NAMED:
        return Key(_NAMED[event_key])
    if len(event_key) == 1:
        return Key("char", event_key)
    return None
