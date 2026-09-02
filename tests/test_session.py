# tests/test_session.py
import io

import numpy as np
import pytest

from specterm1d.plot import SpectrumPlot
from specterm1d.session import Session
from specterm1d.spec import SpecCollection, SpecEntry, build_spec
from specterm1d.term.caps import TerminalCaps
from specterm1d.term.input import Key
from specterm1d.term.text import TextRenderer


def make_session(n_entries=3):
    entries = []
    for i in range(n_entries):
        spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, i + 1.0))
        entries.append(SpecEntry(f"OBJ{i:03d}", {"OPT/COUNTS": spec}, "OPT/COUNTS"))
    coll = SpecCollection(entries=entries, path="/tmp/test.fits")
    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=24, cols=80, pixel_width=None, pixel_height=None,
                        is_tty=True)
    out = io.StringIO()
    renderer = TextRenderer(out=out, truecolor=True)
    return Session(coll, renderer, SpectrumPlot(80, 44), out, caps), out


def test_render_writes_to_the_output_stream():
    session, out = make_session()
    session.render()
    assert len(out.getvalue()) > 0


def test_outer_rect_leaves_two_rows_for_status_and_message():
    session, _ = make_session()
    rect = session.outer_rect()
    assert rect.rows == session.caps.rows - 2
    assert rect.cols == session.caps.cols


def test_plot_rect_yields_a_gutter_when_the_terminal_draws_the_chrome():
    session, _ = make_session()
    outer, rect = session.outer_rect(), session.plot_rect()
    if session.text_chrome:
        assert rect.col > outer.col and rect.row > outer.row
        assert rect.rows < outer.rows and rect.cols < outer.cols
    else:
        assert rect == outer


def test_q_requests_exit():
    session, _ = make_session()
    assert session.handle(Key("char", "q")) is False


def test_unknown_key_is_reported_and_does_not_exit():
    session, _ = make_session()
    assert session.handle(Key("char", "Z")) is True
    assert "Z" in session.last_message


def test_resize_updates_caps_and_plot_size():
    session, _ = make_session()
    session.on_resize(rows=40, cols=120)
    assert session.caps.rows == 40 and session.caps.cols == 120
    assert session.outer_rect().rows == 38


def test_arrow_keys_move_the_cursor():
    session, _ = make_session()
    session.view.reset_limits()
    start = session.view.cursor_x
    session.handle(Key("right"))
    assert session.view.cursor_x > start


def test_shift_arrow_moves_further_than_plain_arrow():
    session, _ = make_session()
    session.view.reset_limits()
    origin = session.view.cursor_x
    session.handle(Key("right"))
    small = session.view.cursor_x - origin
    session.view.cursor_x = origin
    session.handle(Key("shift-right"))
    assert session.view.cursor_x - origin > small


def test_up_down_arrows_move_the_cursor_in_y():
    # splot's cursor is a 2D crosshair; 'e' and 'k' read the continuum off it.
    session, _ = make_session()
    session.view.reset_limits()
    start = session.view.cursor_y
    session.handle(Key("up"))
    assert session.view.cursor_y > start
    session.handle(Key("down"))
    assert session.view.cursor_y == pytest.approx(start)


def test_cursor_y_is_clamped_to_the_view():
    session, _ = make_session()
    session.view.reset_limits()
    for _ in range(500):
        session.handle(Key("shift-up"))
    assert session.view.cursor_y <= session.view.ylim[1]


def test_cursor_is_clamped_to_the_view():
    session, _ = make_session()
    session.view.reset_limits()
    for _ in range(500):
        session.handle(Key("shift-right"))
    assert session.view.cursor_x <= session.view.xlim[1]


def test_status_line_reports_position_and_entry():
    session, _ = make_session()
    session.view.reset_limits()
    line = session.status_line()
    assert "1/3" in line
    assert "OPT/COUNTS" in line


def test_status_line_fits_the_terminal_width():
    session, _ = make_session()
    session.view.reset_limits()
    assert len(session.status_line()) <= session.caps.cols


def test_teardown_restores_the_screen():
    session, out = make_session()
    session.teardown()
    text = out.getvalue()
    assert "\x1b[?25h" in text      # cursor shown again


def test_teardown_is_idempotent():
    session, _ = make_session()
    session.teardown()
    session.teardown()


def _session_with(caps, renderer=None):
    spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 1.0))
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x")
    out = io.StringIO()
    renderer = renderer or TextRenderer(out=out, truecolor=True)
    width, height = renderer.target_pixels(caps.rows - 2, caps.cols)
    return Session(coll, renderer, SpectrumPlot(width, height), out, caps)


def test_render_sizes_the_chrome_to_the_terminal_cell():
    # kitty/iTerm2 hand back the window's pixel budget - on a HiDPI display,
    # physical pixels - so a fixed 8 pt label came out a fraction of the
    # height of the terminal's own text.
    from specterm1d.term.kitty import KittyRenderer

    caps = TerminalCaps(kitty=True, iterm2=False, sixel=False, truecolor=True,
                        rows=40, cols=120, pixel_width=2400, pixel_height=1600,
                        is_tty=True)
    session = _session_with(caps, KittyRenderer(io.StringIO(), caps))
    session.render()
    assert session.plot.cell_px == pytest.approx(1600 / 40)
    assert session.plot.dpi > 100


def test_render_leaves_the_dpi_alone_when_the_terminal_reports_no_pixels():
    caps = TerminalCaps(False, False, False, True, 24, 80, None, None, True)
    session = _session_with(caps)
    session.render()
    assert session.plot.cell_px is None
    assert session.plot.dpi == 100


def test_a_resize_refreshes_the_reported_pixel_size():
    # The cell height now drives the label size, so carrying the old pixel
    # dimensions across a resize would leave the chrome sized for the window
    # the terminal used to be.
    caps = TerminalCaps(kitty=True, iterm2=False, sixel=False, truecolor=True,
                        rows=40, cols=120, pixel_width=2400, pixel_height=1600,
                        is_tty=True)
    session = _session_with(caps)
    session.on_resize(20, 60, pixel_width=1200, pixel_height=800)
    assert session.caps.pixel_width == 1200
    assert session.caps.pixel_height == 800
    assert session.cell_px() == pytest.approx(40.0)


def test_a_resize_that_reports_no_pixels_keeps_what_it_had():
    caps = TerminalCaps(kitty=True, iterm2=False, sixel=False, truecolor=True,
                        rows=40, cols=120, pixel_width=2400, pixel_height=1600,
                        is_tty=True)
    session = _session_with(caps)
    session.on_resize(20, 60)
    assert session.caps.pixel_width == 2400
    assert session.caps.pixel_height == 1600


def test_a_resize_preserves_pixel_mouse_capability():
    caps = TerminalCaps(
        kitty=True, iterm2=False, sixel=False, truecolor=True,
        rows=40, cols=120, pixel_width=2400, pixel_height=1600,
        is_tty=True, pixel_mouse=True,
    )
    session = _session_with(caps)

    session.on_resize(20, 60, pixel_width=1200, pixel_height=800)

    assert session.caps.pixel_mouse is True


def _line_session():
    """A 2500:1 spectrum, where mid-window is a hopeless continuum guess.

    The line sits off centre so that the cursor's default x lands on the
    continuum rather than on the peak.
    """
    wave = np.linspace(4995.0, 5025.0, 400)
    flux = 6000.0 + 4.3e6 * np.exp(-0.5 * ((wave - 5002.0) / 1.7) ** 2)
    coll = SpecCollection(entries=[SpecEntry("A", {"F": build_spec(wave, flux)}, "F")],
                          path="x")
    caps = TerminalCaps(False, False, False, True, 24, 80, None, None, True)
    out = io.StringIO()
    return Session(coll, TextRenderer(out=out), SpectrumPlot(80, 44),
                   out, caps)


def test_the_cursor_starts_on_the_spectrum_not_mid_window():
    session = _line_session()
    lo, hi = session.view.ylim
    assert session.view.cursor_y < 0.5 * (lo + hi)
    assert session.view.cursor_y == pytest.approx(6000.0, rel=0.2)


def test_moving_left_or_right_keeps_the_cursor_on_the_spectrum():
    session = _line_session()
    session.view.cursor_x = 5002.0
    session.handle(Key("right"))
    assert session.view.cursor_y == pytest.approx(4.3e6, rel=0.1)


def test_moving_the_cursor_up_stops_it_following():
    session = _line_session()
    session.handle(Key("up"))
    placed = session.view.cursor_y
    session.handle(Key("right"))
    assert session.view.cursor_y == pytest.approx(placed)


def test_the_pointer_also_stops_it_following():
    session = _line_session()
    session.on_motion(5002.0, 1234.0)
    session.handle(Key("right"))
    assert session.view.cursor_y == pytest.approx(1234.0)


class StubReader:
    """KeyReader stand-in: hands back a canned batch per read() call.

    An empty batch is what a real reader returns when its select() times out
    with nothing typed, which is the case the loop used to redraw through.
    """

    def __init__(self, batches):
        self.batches = list(batches)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, timeout=None):
        self.reads += 1
        return self.batches.pop(0) if self.batches else [Key("char", "q")]


def run_with(monkeypatch, batches):
    """Drive Session.run() over a scripted sequence of read() batches."""
    import specterm1d.commands  # noqa: F401  - registers the handlers
    import specterm1d.session as session_module

    session, out = make_session()
    reader = StubReader(batches)
    monkeypatch.setattr(session_module, "KeyReader", lambda: reader)

    renders = []
    real_render = session.render
    session.render = lambda: (renders.append(1), real_render())[1]
    session.run()
    return session, out, renders


def test_an_idle_timeout_does_not_redraw(monkeypatch):
    # Every frame is a full figure render and, on iTerm2, an image the
    # terminal never frees. Nothing changed, so nothing is redrawn.
    _, _, renders = run_with(monkeypatch, [[], [], [], [Key("char", "q")]])
    assert len(renders) == 1          # the opening frame, and nothing since


def test_a_keypress_still_redraws(monkeypatch):
    _, _, renders = run_with(monkeypatch,
                             [[Key("right")], [Key("right")],
                              [Key("char", "q")]])
    assert len(renders) == 3          # opening frame plus one per keypress


def test_an_idle_timeout_between_keypresses_redraws_only_for_the_keys(
        monkeypatch):
    _, _, renders = run_with(monkeypatch,
                             [[], [Key("right")], [], [], [Key("right")],
                              [Key("char", "q")]])
    assert len(renders) == 3


def test_the_status_line_flags_a_logarithmic_axis():
    session, _ = make_session()
    assert "Ly" not in session.status_line()
    session.view.yscale = "log"
    session.view.xscale = "log"
    line = session.status_line()
    assert "Lx" in line and "Ly" in line
