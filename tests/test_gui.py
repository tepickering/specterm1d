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


# ---- GuiRenderer against a fake toolkit ----------------------------

class FakeCanvas:
    def __init__(self, size=(640, 480)):
        self.callbacks = {}
        self.flushed = 0
        self._size = size

    def mpl_connect(self, name, func):
        self.callbacks[name] = func
        return len(self.callbacks)

    def flush_events(self):
        self.flushed += 1

    def get_width_height(self):
        return self._size


class FakeManager:
    def __init__(self, canvas):
        self.canvas = canvas
        self.title = None
        self.destroyed = False

    def set_window_title(self, text):
        self.title = text

    def destroy(self):
        self.destroyed = True


class FakeEvent:
    def __init__(self, key=None, inaxes=None, xdata=None, ydata=None):
        self.key = key
        self.inaxes = inaxes
        self.xdata = xdata
        self.ydata = ydata


def fake_open(fig, size, backends=None):
    canvas = FakeCanvas()
    return canvas, FakeManager(canvas), "fake"


def attached_renderer(size=(400, 300)):
    from specterm1d.plot import SpectrumPlot

    plot = SpectrumPlot(*size)
    renderer = gui.GuiRenderer(size=size, open_fn=fake_open)
    renderer.attach(plot)
    return renderer, plot


def test_gui_renderer_advertises_itself_as_interactive():
    renderer = gui.GuiRenderer(open_fn=fake_open)
    assert renderer.name == "gui"
    assert renderer.interactive is True
    assert renderer.text_chrome is False
    assert renderer.closed is False


def test_target_pixels_is_the_configured_size_before_the_window_exists():
    # cli.py builds the plot before attaching, so this has to answer early.
    renderer = gui.GuiRenderer(size=(1200, 800), open_fn=fake_open)
    assert renderer.target_pixels(40, 100) == (1200, 800)


def test_target_pixels_follows_the_live_canvas_once_attached():
    renderer, _ = attached_renderer()
    assert renderer.target_pixels(40, 100) == (640, 480)


def test_attach_adopts_the_existing_figure():
    renderer, plot = attached_renderer()
    assert renderer.plot is plot


def test_attach_subscribes_to_every_event_the_session_needs():
    renderer, _ = attached_renderer()
    assert set(renderer.canvas.callbacks) == {
        "key_press_event", "motion_notify_event", "button_press_event",
        "close_event", "resize_event",
    }


def test_key_presses_queue_as_terminal_keys():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["key_press_event"](FakeEvent(key="k"))
    assert renderer.poll() == [Key("char", "k")]


def test_unmapped_key_presses_are_dropped_rather_than_queued():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["key_press_event"](FakeEvent(key="ctrl+c"))
    assert renderer.poll() == []


def test_poll_drains_the_queue():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["key_press_event"](FakeEvent(key="a"))
    assert len(renderer.poll()) == 1
    assert renderer.poll() == []


def test_motion_inside_the_axes_queues_data_coordinates():
    renderer, plot = attached_renderer()
    renderer.canvas.callbacks["motion_notify_event"](
        FakeEvent(inaxes=plot.ax, xdata=5000.5, ydata=1.25))
    assert renderer.poll() == [Motion(5000.5, 1.25)]


def test_motion_outside_the_axes_is_ignored():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["motion_notify_event"](
        FakeEvent(inaxes=None, xdata=None, ydata=None))
    assert renderer.poll() == []


def test_a_click_places_the_cursor_the_same_way_motion_does():
    renderer, plot = attached_renderer()
    renderer.canvas.callbacks["button_press_event"](
        FakeEvent(inaxes=plot.ax, xdata=5100.0, ydata=2.0))
    assert renderer.poll() == [Motion(5100.0, 2.0)]


def test_closing_the_window_sets_closed():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["close_event"](FakeEvent())
    assert renderer.closed is True


def test_a_resize_is_reported_once_and_then_cleared():
    renderer, _ = attached_renderer()
    assert renderer.take_resized() is False
    renderer.canvas.callbacks["resize_event"](FakeEvent())
    assert renderer.take_resized() is True
    assert renderer.take_resized() is False


def test_pump_runs_the_toolkits_event_loop():
    renderer, _ = attached_renderer()
    renderer.pump()
    renderer.pump()
    assert renderer.canvas.flushed == 2


def test_set_title_carries_the_readout_to_the_window():
    renderer, _ = attached_renderer()
    renderer.set_title("x=5000  y=1.2")
    assert renderer.manager.title == "x=5000  y=1.2"


def test_draw_is_a_no_op_because_the_canvas_is_already_on_screen():
    import numpy as np

    from specterm1d.term.base import CellRect

    renderer, _ = attached_renderer()
    assert renderer.draw(np.zeros((4, 4, 4), dtype=np.uint8),
                         CellRect(0, 0, 2, 4)) is None


def test_teardown_destroys_the_window_and_is_idempotent():
    renderer, _ = attached_renderer()
    manager = renderer.manager
    renderer.teardown()
    renderer.teardown()
    assert manager.destroyed is True


def test_teardown_before_attach_does_not_raise():
    gui.GuiRenderer(open_fn=fake_open).teardown()


def test_pump_and_set_title_before_attach_do_not_raise():
    renderer = gui.GuiRenderer(open_fn=fake_open)
    renderer.pump()
    renderer.set_title("x")


def test_attach_propagates_gui_unavailable_so_cli_can_fall_back():
    from specterm1d.plot import SpectrumPlot

    def refuse(fig, size, backends=None):
        raise gui.GuiUnavailable("tkagg: no display name and no $DISPLAY")

    renderer = gui.GuiRenderer(open_fn=refuse)
    with pytest.raises(gui.GuiUnavailable):
        renderer.attach(SpectrumPlot(100, 100))


# ---- one real window, skipped where there is no display ------------

@pytest.mark.skipif(not gui.available(), reason="no GUI display available")
def test_a_real_window_opens_draws_a_frame_and_closes(clean_rcparams):
    import numpy as np

    from specterm1d.plot import SpectrumPlot
    from specterm1d.spec import SpecCollection, SpecEntry, build_spec
    from specterm1d.view import ViewState

    plot = SpectrumPlot(400, 300)
    renderer = gui.GuiRenderer(size=(400, 300))
    try:
        renderer.attach(plot)
    except gui.GuiUnavailable as exc:
        pytest.skip(str(exc))
    try:
        spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 3.0))
        coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")],
                              path="x.fits")
        view = ViewState(coll)
        view.reset_limits()
        plot.draw(view.to_request(title="smoke"))
        renderer.pump()
        renderer.set_title("x=5000")
        assert renderer.target_pixels(40, 100)[0] > 0
        assert renderer.closed is False
    finally:
        renderer.teardown()


# ---- crosshair -----------------------------------------------------

class BlitCanvas(FakeCanvas):
    def __init__(self, size=(640, 480)):
        super().__init__(size)
        self.copies = 0
        self.restores = 0
        self.blits = 0

    def copy_from_bbox(self, bbox):
        self.copies += 1
        return object()

    def restore_region(self, background):
        self.restores += 1

    def blit(self, bbox):
        self.blits += 1


def blit_open(fig, size, backends=None):
    canvas = BlitCanvas()
    return canvas, FakeManager(canvas), "fake"


def blitting_renderer():
    from specterm1d.plot import SpectrumPlot

    plot = SpectrumPlot(400, 300)
    renderer = gui.GuiRenderer(size=(400, 300), open_fn=blit_open)
    renderer.attach(plot)
    return renderer, plot


def test_the_first_crosshair_captures_the_background_and_blits():
    renderer, _ = blitting_renderer()
    renderer.crosshair(5500.0, 1.0)
    assert renderer.canvas.copies == 1
    assert renderer.canvas.restores == 1
    assert renderer.canvas.blits == 1


def test_later_crosshairs_reuse_the_captured_background():
    # The whole point: a few milliseconds per motion event, not 182.
    renderer, _ = blitting_renderer()
    for x in (5100.0, 5200.0, 5300.0):
        renderer.crosshair(x, 1.0)
    assert renderer.canvas.copies == 1
    assert renderer.canvas.blits == 3


def test_the_crosshair_follows_the_pointer():
    renderer, _ = blitting_renderer()
    renderer.crosshair(5100.0, 1.0)
    renderer.crosshair(5900.0, 2.0)
    assert renderer._vline.get_xdata()[0] == pytest.approx(5900.0)
    assert renderer._hline.get_ydata()[0] == pytest.approx(2.0)


def test_invalidate_drops_the_background_and_the_artists():
    # plot.draw() calls ax.clear(), which destroys them; a stale background
    # would blit the previous frame back over the new one.
    renderer, _ = blitting_renderer()
    renderer.crosshair(5100.0, 1.0)
    renderer.invalidate()
    assert renderer._vline is None and renderer._hline is None
    renderer.crosshair(5200.0, 1.0)
    assert renderer.canvas.copies == 2


def test_a_resize_invalidates_the_background():
    renderer, _ = blitting_renderer()
    renderer.crosshair(5100.0, 1.0)
    renderer.canvas.callbacks["resize_event"](FakeEvent())
    renderer.crosshair(5200.0, 1.0)
    assert renderer.canvas.copies == 2


def test_the_crosshair_is_a_no_op_before_attach():
    gui.GuiRenderer(open_fn=blit_open).crosshair(1.0, 2.0)
