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


# ---- backend probing -----------------------------------------------

@pytest.fixture
def clean_rcparams():
    """open_window mutates global rcParams on purpose; put them back."""
    from matplotlib import rcParams
    saved = {k: rcParams[k] for k in list(rcParams)
             if k == "toolbar" or k.startswith("keymap.")}
    yield rcParams
    rcParams.update(saved)


def test_available_is_true_on_darwin_with_no_display():
    assert gui.available(env={}, platform="darwin") is True


def test_available_is_false_over_ssh_with_no_display():
    # The case the fallback exists for: X11 forwarding off, tmux over ssh.
    assert gui.available(env={}, platform="linux") is False


def test_available_is_true_with_an_x11_display():
    assert gui.available(env={"DISPLAY": ":0"}, platform="linux") is True


def test_available_is_true_under_wayland():
    assert gui.available(env={"WAYLAND_DISPLAY": "wayland-0"},
                         platform="linux") is True


def test_available_honours_mplbackend_when_it_names_a_gui_backend():
    assert gui.available(env={"MPLBACKEND": "TkAgg"}, platform="linux") is True


def test_available_honours_mplbackend_when_it_names_a_headless_backend():
    assert gui.available(env={"MPLBACKEND": "Agg", "DISPLAY": ":0"},
                         platform="linux") is False


def test_backends_for_tries_every_toolkit_by_default():
    assert gui.backends_for(env={}) == gui.GUI_BACKENDS


def test_backends_for_tries_only_the_one_mplbackend_names():
    assert gui.backends_for(env={"MPLBACKEND": "TkAgg"}) == ("tkagg",)


def test_open_window_raises_gui_unavailable_and_names_the_reason(clean_rcparams):
    from specterm1d.plot import SpectrumPlot

    with pytest.raises(gui.GuiUnavailable) as excinfo:
        gui.open_window(SpectrumPlot(100, 100).fig, (100, 100),
                        backends=("nosuch",))
    assert "nosuch" in str(excinfo.value)


def test_open_window_disables_the_toolbar_and_matplotlibs_own_keymap(clean_rcparams):
    # matplotlib binds s/p/o/q/k/l/g/f. All eight collide with splot, and q
    # would quit the window out from under the session. The toolbar is worse:
    # it drives ax limits behind ViewState's back.
    from specterm1d.plot import SpectrumPlot

    clean_rcparams["toolbar"] = "toolbar2"
    clean_rcparams["keymap.save"] = ["s"]
    clean_rcparams["keymap.quit"] = ["q"]
    with pytest.raises(gui.GuiUnavailable):
        gui.open_window(SpectrumPlot(100, 100).fig, (100, 100),
                        backends=("nosuch",))
    # matplotlib normalizes the value; compare case-insensitively.
    assert str(clean_rcparams["toolbar"]).lower() == "none"
    assert clean_rcparams["keymap.save"] == []
    assert clean_rcparams["keymap.quit"] == []
