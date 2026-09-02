# tests/test_mouse.py

from dataclasses import replace

import pytest

from specterm1d import cli
from specterm1d.session import Session
from specterm1d.term.caps import TerminalCaps
from specterm1d.term.input import Key, parse_keys, parse_sgr_mouse
from specterm1d.term.kitty import KittyRenderer
from specterm1d.term.sixel import SixelRenderer
from tests.test_session import StubReader, make_session


def _run_cli(monkeypatch, tabular_fits, renderer, *flags):
    caps = TerminalCaps(
        kitty=True, iterm2=True, sixel=True, truecolor=True,
        rows=24, cols=80, pixel_width=800, pixel_height=480, is_tty=True,
    )
    sessions = []
    monkeypatch.setattr(cli.caps_mod, "detect", lambda **kwargs: caps)
    monkeypatch.setattr(Session, "run", lambda session: sessions.append(session))
    assert cli.main(["--renderer", renderer, *flags, str(tabular_fits)]) == 0
    return sessions[0]


def _pixel_mouse_session():
    return _inline_pixel_session(KittyRenderer)


def _inline_pixel_session(renderer_cls):
    """An inline backend on a terminal that reports pixel mouse positions."""
    session, out = make_session()
    caps = replace(
        session.caps, kitty=True, pixel_width=800, pixel_height=480,
        pixel_mouse=True,
    )
    session.caps = caps
    session.renderer = renderer_cls(out, caps)
    session.text_chrome = False
    session.plot.bare = False
    return session, out


def test_sgr_press_is_parsed():
    assert parse_sgr_mouse("\x1b[<0;40;12M") == (0, 40, 12)


def test_sgr_release_is_parsed():
    assert parse_sgr_mouse("\x1b[<0;40;12m") == (0, 40, 12)


def test_non_mouse_sequence_returns_none():
    assert parse_sgr_mouse("\x1b[A") is None


def test_mouse_key_reaches_the_parser():
    keys, _ = parse_keys(b"\x1b[<0;40;12M")
    assert keys[0].name == "mouse"
    assert parse_sgr_mouse(keys[0].char) == (0, 40, 12)


def test_enabling_mouse_writes_the_enable_sequence():
    session, out = make_session()
    session.set_mouse(True)
    assert "\x1b[?1000;1002;1006h" in out.getvalue()


def test_enabling_mouse_uses_pixel_coordinates_in_native_kitty():
    session, out = _pixel_mouse_session()
    session.set_mouse(True)
    assert "\x1b[?1000;1002;1016h" in out.getvalue()


def test_disabling_mouse_writes_the_disable_sequence():
    session, out = make_session()
    session.set_mouse(True)
    out.truncate(0)
    out.seek(0)
    session.set_mouse(False)
    assert "\x1b[?1000;1002;1006l" in out.getvalue()


def test_disabling_mouse_restores_kitty_pixel_mode():
    session, out = _pixel_mouse_session()
    session.set_mouse(True)
    out.truncate(0)
    out.seek(0)
    session.set_mouse(False)
    assert "\x1b[?1000;1002;1016l" in out.getvalue()


def test_teardown_disables_mouse():
    session, out = make_session()
    session.set_mouse(True)
    out.truncate(0)
    out.seek(0)
    session.teardown()
    assert "\x1b[?1000;1002;1006l" in out.getvalue()


def test_teardown_disables_kitty_pixel_mouse_mode():
    session, out = _pixel_mouse_session()
    session.set_mouse(True)
    out.truncate(0)
    out.seek(0)
    session.teardown()
    assert "\x1b[?1000;1002;1016l" in out.getvalue()


def test_click_moves_the_cursor_into_data_coordinates():
    session, _ = make_session()
    session.view.reset_limits()
    session.set_mouse(True)
    lo, hi = session.view.xlim
    session.on_mouse(col=session.caps.cols // 2, row=session.caps.rows // 2)
    assert lo < session.view.cursor_x < hi


def test_click_near_the_left_edge_maps_low():
    session, _ = make_session()
    session.view.reset_limits()
    session.set_mouse(True)
    session.on_mouse(col=2, row=session.caps.rows // 2)
    left = session.view.cursor_x
    session.on_mouse(col=session.caps.cols - 2, row=session.caps.rows // 2)
    assert session.view.cursor_x > left


def test_kitty_pixel_mouse_distinguishes_points_inside_one_cell():
    session, _ = _pixel_mouse_session()
    session.view.reset_limits()

    session.on_mouse(col=400, row=240)
    first = session.view.cursor_x
    session.on_mouse(col=401, row=240)

    step = session.view.cursor_x - first
    xlo, xhi = session.view.xlim
    expected = (xhi - xlo) / (
        session.plot.ax.get_position().width * session.caps.pixel_width
    )
    assert step == pytest.approx(expected)


def test_kitty_pixel_mouse_y_increases_upwards():
    session, _ = _pixel_mouse_session()
    session.view.reset_limits()

    session.on_mouse(col=400, row=200)
    upper = session.view.cursor_y
    session.on_mouse(col=400, row=201)

    assert session.view.cursor_y < upper


def test_kitty_pixel_mouse_ignores_footer():
    session, _ = _pixel_mouse_session()
    session.view.reset_limits()
    before = (session.view.cursor_x, session.view.cursor_y)

    session.on_mouse(col=400, row=479)

    assert (session.view.cursor_x, session.view.cursor_y) == before


def test_click_outside_the_axes_is_ignored():
    session, _ = make_session()
    session.view.reset_limits()
    session.set_mouse(True)
    before = session.view.cursor_x
    session.on_mouse(col=0, row=session.caps.rows)   # in the status line
    assert session.view.cursor_x == before


def test_mouse_events_are_ignored_when_disabled():
    session, _ = make_session()
    session.view.reset_limits()
    before = session.view.cursor_x
    from specterm1d.term.input import Key
    session.handle(Key("mouse", "\x1b[<0;40;12M"))
    assert session.view.cursor_x == before


def test_kitty_pixel_mouse_ignores_window_leave_report():
    session, _ = _pixel_mouse_session()
    session.view.reset_limits()
    session.set_mouse(True)
    before = (session.view.cursor_x, session.view.cursor_y)

    session.handle(Key("mouse", "\x1b[<288;400;240M"))

    assert (session.view.cursor_x, session.view.cursor_y) == before


def test_kitty_pixel_mouse_leave_does_not_redraw(monkeypatch):
    import specterm1d.session as session_module

    session, _ = _pixel_mouse_session()
    session.set_mouse(True)
    reader = StubReader([
        [Key("mouse", "\x1b[<288;400;240M")],
        [Key("char", "q")],
    ])
    monkeypatch.setattr(session_module, "KeyReader", lambda: reader)
    renders = []
    real_render = session.render
    session.render = lambda: (renders.append(1), real_render())[1]

    session.run()

    assert len(renders) == 1


@pytest.mark.parametrize("renderer", ["kitty", "sixel", "iterm2"])
def test_inline_graphics_enable_mouse_by_default(monkeypatch, tabular_fits,
                                                 renderer):
    session = _run_cli(monkeypatch, tabular_fits, renderer)
    assert session.mouse_enabled is True


def test_no_mouse_disables_the_inline_default(monkeypatch, tabular_fits):
    session = _run_cli(monkeypatch, tabular_fits, "kitty", "--no-mouse")
    assert session.mouse_enabled is False


def test_the_text_backend_keeps_mouse_off_by_default(monkeypatch, tabular_fits):
    session = _run_cli(monkeypatch, tabular_fits, "text")
    assert session.mouse_enabled is False


def test_mouse_can_still_be_enabled_for_the_text_backend(monkeypatch, tabular_fits):
    session = _run_cli(monkeypatch, tabular_fits, "text", "--mouse")
    assert session.mouse_enabled is True


# ---- pixel mouse is a terminal capability, not a kitty one ---------

def test_sixel_enables_the_pixel_mouse_sequence():
    session, out = _inline_pixel_session(SixelRenderer)
    session.set_mouse(True)
    assert "\x1b[?1000;1002;1016h" in out.getvalue()


def test_sixel_pixel_mouse_distinguishes_points_inside_one_cell():
    session, _ = _inline_pixel_session(SixelRenderer)
    session.view.reset_limits()

    session.on_mouse(col=400, row=240)
    first = session.view.cursor_x
    session.on_mouse(col=401, row=240)

    step = session.view.cursor_x - first
    xlo, xhi = session.view.xlim
    expected = (xhi - xlo) / (
        session.plot.ax.get_position().width * session.caps.pixel_width
    )
    assert step == pytest.approx(expected)


def test_the_text_backend_keeps_cell_coordinates_even_where_1016_is_offered():
    """The terminal may support pixel reports while the backend cannot use
    them: the text backend paints its own chrome and has no pixel placement."""
    session, out = make_session()
    session.caps = replace(
        session.caps, pixel_width=800, pixel_height=480, pixel_mouse=True,
    )

    session.set_mouse(True)

    assert "\x1b[?1000;1002;1006h" in out.getvalue()


# ---- log axes ----------------------------------------------------------

def test_a_click_on_a_log_axis_lands_where_the_chrome_drew_the_tick():
    """The two ends of the same mapping, checked against each other.

    The chrome puts a tick label in a cell; clicking that cell has to give
    back the value it labels. A linear mapping on one side and a log one on
    the other would look right on screen and silently misplace every
    measurement.
    """
    import numpy as np

    from specterm1d.term.chrome import _cell_for

    session, _ = make_session()
    if not session.text_chrome:
        pytest.skip("renderer draws its own chrome")

    session.view.xscale = "log"
    session.view.xlim = (1.0, 10000.0)
    layout = session.chrome_layout()
    values, _ = session.x_ticks(layout.plot.cols)
    assert len(values) > 1

    decades_per_cell = 4.0 / layout.plot.cols
    for value in values:
        col = _cell_for(value, 1.0, 10000.0, layout.plot.col, layout.plot.cols,
                        log=True)
        session.view.cursor_x = None
        session.on_mouse(col=col + 1, row=layout.plot.row + 2)
        assert session.view.cursor_x is not None
        assert abs(np.log10(session.view.cursor_x) - np.log10(value)) \
            <= decades_per_cell


def test_a_click_on_a_log_y_axis_reads_off_the_decades():
    session, _ = make_session()
    if not session.text_chrome:
        pytest.skip("renderer draws its own chrome")

    session.view.yscale = "log"
    session.view.ylim = (1.0, 100.0)
    rect = session.plot_rect()
    # Halfway up the plot is the geometric middle of the window.
    session.on_mouse(col=rect.col + 2, row=rect.row + rect.rows // 2 + 1)
    assert session.view.cursor_y == pytest.approx(10.0, rel=0.25)
