# tests/test_gui.py
import dataclasses

import pytest

from specterm1d.term import gui
from specterm1d.term.base import Motion
from specterm1d.term.input import Key

# ---- key_from_mpl --------------------------------------------------

@pytest.mark.parametrize("event_key,expected", [
    ("left", Key("left")),
    ("right", Key("right")),
    ("up", Key("up")),
    ("down", Key("down")),
    ("shift+left", Key("shift-left")),
    ("shift+right", Key("shift-right")),
    ("shift+up", Key("shift-up")),
    ("shift+down", Key("shift-down")),
    ("escape", Key("escape")),
    ("enter", Key("enter")),
    ("return", Key("enter")),
    ("backspace", Key("backspace")),
    ("pageup", Key("pageup")),
    ("pagedown", Key("pagedown")),
    (" ", Key("char", " ")),
    ("k", Key("char", "k")),
    ("Z", Key("char", "Z")),
    (":", Key("char", ":")),
])
def test_key_from_mpl_maps_onto_the_existing_key_vocabulary(event_key, expected):
    assert gui.key_from_mpl(event_key) == expected


@pytest.mark.parametrize("event_key", [
    None, "", "ctrl+c", "f1", "alt+x", "shift+f1", "super",
])
def test_key_from_mpl_drops_what_the_keymap_has_no_meaning_for(event_key):
    assert gui.key_from_mpl(event_key) is None


def test_key_from_mpl_returns_a_real_key_so_dispatch_needs_no_translation():
    key = gui.key_from_mpl("k")
    assert isinstance(key, Key)
    assert str(key) == "k"


# ---- Motion --------------------------------------------------------

def test_motion_carries_data_coordinates_and_is_frozen():
    motion = Motion(5000.5, 1.25)
    assert (motion.x, motion.y) == (5000.5, 1.25)
    with pytest.raises(dataclasses.FrozenInstanceError):
        motion.x = 1.0
