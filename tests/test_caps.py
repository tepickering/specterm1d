# tests/test_caps.py
import pytest

from specterm1d.term import caps as caps_mod
from specterm1d.term.caps import TerminalCaps, choose_renderer, detect


def fake_query(responses):
    """query_fn stub: returns a canned response per request prefix."""
    def _q(request, timeout=0.1):
        for prefix, reply in responses.items():
            if request.startswith(prefix):
                return reply
        return None
    return _q


def fake_size(rows=50, cols=200, xp=1600, yp=850):
    return lambda: (rows, cols, xp, yp)


def test_non_tty_reports_no_capabilities():
    c = detect(env={}, is_tty=False)
    assert c.is_tty is False
    assert not (c.kitty or c.iterm2 or c.sixel)


def test_kitty_detected_from_query_response():
    c = detect(env={}, is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({"\x1b_G": "\x1b_Gi=31;OK\x1b\\"}))
    assert c.kitty is True


def test_kitty_detected_from_env_when_query_is_silent():
    c = detect(env={"TERM": "xterm-kitty"}, is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({}))
    assert c.kitty is True


def test_ghostty_is_recognised():
    c = detect(env={"TERM_PROGRAM": "ghostty"}, is_tty=True,
               size_fn=fake_size(), query_fn=fake_query({}))
    assert c.kitty is True


def test_kitty_is_not_probed_under_tmux():
    # kitty graphics passthrough through tmux is unreliable.
    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0", "TERM": "xterm-kitty"},
               is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({"\x1b_G": "\x1b_Gi=31;OK\x1b\\"}))
    assert c.kitty is False


def test_iterm2_detected_from_term_program():
    c = detect(env={"TERM_PROGRAM": "iTerm.app"}, is_tty=True,
               size_fn=fake_size(), query_fn=fake_query({}))
    assert c.iterm2 is True


def test_iterm2_detected_from_lc_terminal_over_ssh():
    c = detect(env={"LC_TERMINAL": "iTerm2"}, is_tty=True,
               size_fn=fake_size(), query_fn=fake_query({}))
    assert c.iterm2 is True


def test_sixel_detected_from_device_attributes():
    # Windows Terminal 1.22+, foot, xterm >= #359, Konsole, mlterm, contour.
    c = detect(env={}, is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({"\x1b[c": "\x1b[?62;1;4;6;9;15;22;29c"}))
    assert c.sixel is True


def test_sixel_absent_when_attribute_4_is_missing():
    c = detect(env={}, is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({"\x1b[c": "\x1b[?62;1;6;9;15c"}))
    assert c.sixel is False


def test_attribute_14_is_not_mistaken_for_attribute_4():
    c = detect(env={}, is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({"\x1b[c": "\x1b[?62;14;22c"}))
    assert c.sixel is False


def test_truecolor_from_colorterm():
    assert detect(env={"COLORTERM": "truecolor"}, is_tty=True,
                  size_fn=fake_size(), query_fn=fake_query({})).truecolor is True
    assert detect(env={"COLORTERM": "24bit"}, is_tty=True,
                  size_fn=fake_size(), query_fn=fake_query({})).truecolor is True


def test_apple_terminal_is_not_truecolor():
    # Terminal.app never gained 24-bit colour.
    c = detect(env={"TERM_PROGRAM": "Apple_Terminal", "TERM": "xterm-256color"},
               is_tty=True, size_fn=fake_size(), query_fn=fake_query({}))
    assert c.truecolor is False
    assert not (c.kitty or c.iterm2 or c.sixel)


def test_window_pixel_size_is_recorded():
    c = detect(env={}, is_tty=True, size_fn=fake_size(rows=40, cols=160,
                                                      xp=1280, yp=680),
               query_fn=fake_query({}))
    assert (c.rows, c.cols) == (40, 160)
    assert (c.pixel_width, c.pixel_height) == (1280, 680)


def test_zero_pixel_size_is_reported_as_unknown():
    # Terminal.app reports 0 for ws_xpixel/ws_ypixel.
    c = detect(env={}, is_tty=True, size_fn=fake_size(xp=0, yp=0),
               query_fn=fake_query({}))
    assert c.pixel_width is None and c.pixel_height is None


def test_choose_renderer_falls_back_to_halfblock():
    import io
    c = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                     rows=50, cols=200, pixel_width=None, pixel_height=None,
                     is_tty=True)
    assert choose_renderer(c, out=io.StringIO()).name == "halfblock"


def test_choose_renderer_honours_an_explicit_override():
    import io
    c = TerminalCaps(kitty=True, iterm2=False, sixel=False, truecolor=True,
                     rows=50, cols=200, pixel_width=1600, pixel_height=850,
                     is_tty=True)
    assert choose_renderer(c, override="halfblock",
                           out=io.StringIO()).name == "halfblock"


def test_unknown_override_name_is_rejected():
    import io
    c = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                     rows=50, cols=200, pixel_width=None, pixel_height=None,
                     is_tty=True)
    with pytest.raises(ValueError, match="nosuch"):
        choose_renderer(c, override="nosuch", out=io.StringIO())


def test_halfblock_gets_truecolor_flag_from_caps():
    import io
    c = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=False,
                     rows=50, cols=200, pixel_width=None, pixel_height=None,
                     is_tty=True)
    assert choose_renderer(c, out=io.StringIO()).truecolor is False
