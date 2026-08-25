# tests/test_mouse.py

from specterm1d.term.input import parse_keys, parse_sgr_mouse
from tests.test_session import make_session


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


def test_disabling_mouse_writes_the_disable_sequence():
    session, out = make_session()
    session.set_mouse(True)
    out.truncate(0)
    out.seek(0)
    session.set_mouse(False)
    assert "\x1b[?1000;1002;1006l" in out.getvalue()


def test_teardown_disables_mouse():
    session, out = make_session()
    session.set_mouse(True)
    out.truncate(0)
    out.seek(0)
    session.teardown()
    assert "\x1b[?1000;1002;1006l" in out.getvalue()


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
