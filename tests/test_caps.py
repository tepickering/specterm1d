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


# ---- pixel mouse, asked for rather than inferred --------------------

def decrqm(state):
    """A DECRQM reply for mode 1016 in the given state."""
    return fake_query({"\x1b[?1016$p": f"\x1b[?1016;{state}$y"})


def test_a_terminal_that_reports_1016_reset_gets_pixel_mouse():
    c = detect(env={}, is_tty=True, size_fn=fake_size(), query_fn=decrqm("2"))
    assert c.pixel_mouse is True


def test_a_terminal_that_reports_1016_already_set_gets_pixel_mouse():
    c = detect(env={}, is_tty=True, size_fn=fake_size(), query_fn=decrqm("1"))
    assert c.pixel_mouse is True


def test_a_terminal_that_does_not_recognise_1016_keeps_cell_mouse():
    c = detect(env={}, is_tty=True, size_fn=fake_size(), query_fn=decrqm("0"))
    assert c.pixel_mouse is False


def test_a_permanently_reset_1016_keeps_cell_mouse():
    c = detect(env={}, is_tty=True, size_fn=fake_size(), query_fn=decrqm("4"))
    assert c.pixel_mouse is False


def test_silence_on_the_1016_query_keeps_cell_mouse():
    c = detect(env={"TERM": "xterm-kitty", "KITTY_WINDOW_ID": "1"},
               is_tty=True, size_fn=fake_size(), query_fn=fake_query({}))
    assert c.pixel_mouse is False


def test_ghostty_gets_pixel_mouse_when_it_reports_1016():
    # Measured: ghostty answers DECRQM 1016 with ";2" and reports pixel
    # coordinates. Vendor identity was the wrong thing to gate this on.
    c = detect(env={"TERM_PROGRAM": "ghostty"}, is_tty=True,
               size_fn=fake_size(), query_fn=decrqm("2"))
    assert c.pixel_mouse is True


def test_a_sixel_terminal_gets_pixel_mouse_without_kitty_graphics():
    c = detect(env={}, is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({"\x1b[?1016$p": "\x1b[?1016;2$y",
                                    "\x1b[c": "\x1b[?62;1;4;6;9c"}))
    assert (c.kitty, c.sixel, c.pixel_mouse) == (False, True, True)


def test_pixel_mouse_needs_the_terminal_to_report_pixels():
    c = detect(env={}, is_tty=True, size_fn=fake_size(xp=0, yp=0),
               query_fn=decrqm("2"))
    assert c.pixel_mouse is False


def test_pixel_mouse_stays_off_under_tmux():
    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0"}, is_tty=True,
               size_fn=fake_size(), query_fn=decrqm("2"))
    assert c.pixel_mouse is False


def test_kitty_is_not_probed_under_tmux():
    # kitty graphics passthrough through tmux is unreliable.
    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0", "TERM": "xterm-kitty"},
               is_tty=True, size_fn=fake_size(),
               query_fn=fake_query({"\x1b_G": "\x1b_Gi=31;OK\x1b\\"}))
    assert c.kitty is False


def sixel_da():
    """A Primary Device Attributes reply advertising sixel."""
    return fake_query({"\x1b[c": "\x1b[?1;2;4c"})


def test_sixel_is_trusted_outside_tmux():
    c = detect(env={}, is_tty=True, size_fn=fake_size(), query_fn=sixel_da())
    assert c.sixel is True


def test_tmuxs_own_sixel_attribute_is_not_trusted():
    # tmux answers attribute 4 whenever it was built --enable-sixel, with no
    # client attached at all, so inside tmux the reply says nothing about
    # whether an image would reach the screen. It does not here: tmux draws
    # what it cannot pass on as a placeholder padded out with plus signs.
    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0"}, is_tty=True,
               size_fn=fake_size(), query_fn=sixel_da(),
               features_fn=lambda: "bpaste,ccolour,clipboard,cstyle,focus,RGB,title")
    assert c.sixel is False


def test_sixel_survives_tmux_when_the_client_terminal_has_it():
    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0"}, is_tty=True,
               size_fn=fake_size(), query_fn=sixel_da(),
               features_fn=lambda: "bpaste,focus,RGB,sixel,title")
    assert c.sixel is True


def test_a_tmux_that_cannot_be_asked_gives_up_on_sixel():
    # No tmux binary, a server that has gone away, a tmux too old for the
    # format string: all read as "cannot", which is the safe direction.
    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0"}, is_tty=True,
               size_fn=fake_size(), query_fn=sixel_da(), features_fn=lambda: "")
    assert c.sixel is False


def test_the_feature_list_is_matched_whole():
    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0"}, is_tty=True,
               size_fn=fake_size(), query_fn=sixel_da(),
               features_fn=lambda: "focus,sixel-ish,RGB")
    assert c.sixel is False


def test_tmux_is_not_asked_when_the_terminal_never_claimed_sixel():
    def explode():
        raise AssertionError("no reason to shell out to tmux")

    c = detect(env={"TMUX": "/tmp/tmux-501/default,1,0"}, is_tty=True,
               size_fn=fake_size(), query_fn=fake_query({}), features_fn=explode)
    assert c.sixel is False


def test_client_features_are_empty_without_a_tmux_binary(monkeypatch):
    monkeypatch.setattr(caps_mod.shutil, "which", lambda name: None)
    assert caps_mod.tmux_client_features() == ""


def test_client_features_are_empty_when_tmux_fails(monkeypatch):
    class Failed:
        returncode = 1
        stdout = "no server running"

    monkeypatch.setattr(caps_mod.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(caps_mod.subprocess, "run", lambda *a, **k: Failed())
    assert caps_mod.tmux_client_features() == ""


def test_client_features_survive_a_hung_tmux(monkeypatch):
    def hang(*args, **kwargs):
        raise caps_mod.subprocess.TimeoutExpired(cmd="tmux", timeout=1.0)

    monkeypatch.setattr(caps_mod.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(caps_mod.subprocess, "run", hang)
    assert caps_mod.tmux_client_features() == ""


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


def test_query_returns_as_soon_as_a_decrqm_reply_arrives():
    """DECRQM answers end in "$y", not "c".

    Without that terminator the probe sits out its whole timeout on every
    start-up, for a reply that already arrived.
    """
    import os
    import threading
    import time

    from specterm1d.term.caps import query

    master, slave = os.openpty()

    def responder():
        os.read(master, 64)
        os.write(master, b"\x1b[?1016;2$y")

    threading.Thread(target=responder, daemon=True).start()
    try:
        start = time.monotonic()
        reply = query("\x1b[?1016$p", timeout=5.0, fd_in=slave, fd_out=slave)
        elapsed = time.monotonic() - start
    finally:
        os.close(master)
        os.close(slave)

    assert reply == "\x1b[?1016;2$y"
    assert elapsed < 1.0


def test_detect_probes_the_terminal_when_given_no_query_function(monkeypatch):
    """cli calls detect() without a query_fn.

    If the default is "ask nothing", every queried capability silently reads
    False no matter what the terminal can actually do.
    """
    asked = []

    def spy(request, timeout=0.1):
        asked.append(request)
        return {"\x1b[?1016$p": "\x1b[?1016;2$y",
                "\x1b[c": "\x1b[?62;1;4;6;9c"}.get(request)

    monkeypatch.setattr(caps_mod, "query", spy)
    c = detect(env={}, is_tty=True, size_fn=fake_size())

    assert "\x1b[?1016$p" in asked
    assert (c.pixel_mouse, c.sixel) == (True, True)
