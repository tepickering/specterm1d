# tests/test_session.py
import io

import numpy as np
import pytest

from specterm1d.plot import SpectrumPlot
from specterm1d.session import Session
from specterm1d.spec import SpecCollection, SpecEntry, build_spec
from specterm1d.term.caps import TerminalCaps
from specterm1d.term.halfblock import HalfblockRenderer
from specterm1d.term.input import Key


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
    renderer = HalfblockRenderer(out=out, truecolor=True)
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
    renderer = renderer or HalfblockRenderer(out=out, truecolor=True)
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
