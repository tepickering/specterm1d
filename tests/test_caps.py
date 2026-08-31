# tests/test_caps.py
import pytest

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


def test_term_only_kitty_detection_keeps_cell_mouse():
    c = detect(env={"TERM": "xterm-kitty"}, is_tty=True,
               size_fn=fake_size(), query_fn=fake_query({}))
    assert c.pixel_mouse is False


def test_native_kitty_with_pixel_geometry_enables_pixel_mouse():
    c = detect(env={"KITTY_WINDOW_ID": "1"},
               is_tty=True, size_fn=fake_size(), query_fn=fake_query({}))
    assert getattr(c, "pixel_mouse", False) is True


def test_native_kitty_without_pixel_geometry_keeps_cell_mouse():
    c = detect(env={"TERM": "xterm-kitty", "KITTY_WINDOW_ID": "1"},
               is_tty=True, size_fn=fake_size(xp=0, yp=0),
               query_fn=fake_query({}))
    assert c.pixel_mouse is False


def test_ghostty_is_recognised():
    c = detect(env={"TERM_PROGRAM": "ghostty"}, is_tty=True,
               size_fn=fake_size(), query_fn=fake_query({}))
    assert c.kitty is True


def test_kitty_compatible_terminals_keep_cell_mouse():
    c = detect(env={"TERM_PROGRAM": "ghostty", "KITTY_WINDOW_ID": "1"},
               is_tty=True,
               size_fn=fake_size(), query_fn=fake_query({}))
    assert c.pixel_mouse is False


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


def test_preference_puts_the_window_above_halfblock_and_below_inline():
    from specterm1d.term.caps import PREFERENCE
    assert PREFERENCE == ("kitty", "iterm2", "sixel", "gui", "halfblock")


def test_a_terminal_with_no_inline_protocol_gets_a_window():
    import specterm1d.term  # noqa: F401  - registers the factories
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, out=None).name == "gui"


def test_no_display_falls_all_the_way_through_to_halfblock():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=False)
    assert choose_renderer(caps, out=None).name == "halfblock"


def test_inline_graphics_still_beat_the_window():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=True, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, out=None).name == "kitty"


def test_detect_records_whether_a_window_is_worth_trying():
    from specterm1d.term.caps import detect

    caps = detect(env={"DISPLAY": ":0"}, query_fn=lambda q: None,
                  size_fn=lambda: (43, 116, None, None))
    assert caps.gui is True


def test_gui_can_be_forced_by_name():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=True, iterm2=True, sixel=True, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=False)
    assert choose_renderer(caps, override="gui", out=None).name == "gui"


# iTerm2 retains every distinct inline image for the life of the session, so
# panning a spectrum grows the terminal process by roughly a decoded bitmap a
# keystroke. Measured against iTerm2 3.6.11: 1.67 MB per cursor move over 100
# moves, against 0.05 MB/frame for the same loop drawing text. Both of its
# inline paths are affected - sixel measured 4 MB/frame there - so where a
# graphics window is available it is the only comfortable option.
def test_iterm2_yields_to_a_window_because_it_leaks_inline_images():
    import specterm1d.term  # noqa: F401  - registers the factories
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=True, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, out=None).name == "gui"


def test_iterm2_sixel_yields_to_a_window_too():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=True, sixel=True, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, out=None).name == "gui"


def test_iterm2_still_draws_inline_when_there_is_no_window():
    # A leaking plot beats no plot: without a display we stay inline.
    import io

    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=True, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=False)
    assert choose_renderer(caps, out=io.StringIO()).name == "iterm2"


def test_sixel_elsewhere_is_untouched_by_the_iterm2_workaround():
    # foot, xterm and Windows Terminal do not leak; they keep inline graphics.
    import io

    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=True, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, out=io.StringIO()).name == "sixel"


def test_an_explicit_iterm2_override_still_wins():
    import io

    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=True, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, override="iterm2",
                           out=io.StringIO()).name == "iterm2"
