# tests/test_gui_session.py
import io

import numpy as np
import pytest

import specterm1d.commands  # noqa: F401  - registers the handlers
from specterm1d.plot import SpectrumPlot
from specterm1d.session import Session
from specterm1d.spec import SpecCollection, SpecEntry, build_spec
from specterm1d.term.base import Motion
from specterm1d.term.caps import TerminalCaps
from specterm1d.term.input import Key

# The sequences that would mean a TUI is being painted. Erase-to-EOL is not
# among them: Transcript.prompt() writes it to redraw a prompt in place.
TUI_SEQUENCES = ("\x1b[?25l", "\x1b[2J", "\x1b[7m", "\x1b[?1000")


class FakeGui:
    """An interactive renderer with a scripted event stream and no window."""

    name = "gui"
    text_chrome = False
    interactive = True

    def __init__(self, script=()):
        self.script = [list(batch) for batch in script]
        self.closed = False
        self.titles = []
        self.draws = 0
        self.pumps = 0
        self.plot = None
        self.torn_down = False

    def target_pixels(self, rows, cols):
        return (400, 300)

    def attach(self, plot):
        self.plot = plot

    def pump(self):
        self.pumps += 1

    def poll(self):
        if not self.script:
            self.closed = True
            return []
        return self.script.pop(0)

    def take_resized(self):
        return False

    def set_title(self, text):
        self.titles.append(text)

    def draw(self, rgba, rect):
        self.draws += 1

    def teardown(self):
        self.torn_down = True


def make_gui_session(script=(), n_entries=3):
    entries = []
    for i in range(n_entries):
        spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, i + 1.0))
        entries.append(SpecEntry(f"OBJ{i:03d}", {"OPT/COUNTS": spec}, "OPT/COUNTS"))
    coll = SpecCollection(entries=entries, path="/tmp/test.fits")
    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=24, cols=80, pixel_width=None, pixel_height=None,
                        is_tty=True)
    out = io.StringIO()
    renderer = FakeGui(script)
    plot = SpectrumPlot(400, 300)
    renderer.attach(plot)
    session = Session(coll, renderer, plot, out, caps)
    session.view.reset_limits()
    return session, renderer, out


@pytest.fixture(autouse=True)
def instant_poll(monkeypatch):
    """The loop sleeps POLL_INTERVAL per turn; tests should not."""
    monkeypatch.setattr("specterm1d.session.POLL_INTERVAL", 0.0)


# ---- mode detection ------------------------------------------------

def test_session_notices_an_interactive_renderer():
    session, _, _ = make_gui_session()
    assert session.interactive is True


def test_session_stays_non_interactive_for_terminal_renderers():
    from specterm1d.term.halfblock import HalfblockRenderer

    out = io.StringIO()
    spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 1.0))
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x")
    caps = TerminalCaps(False, False, False, True, 24, 80, None, None, True)
    session = Session(coll, HalfblockRenderer(out=out), SpectrumPlot(80, 44),
                      out, caps)
    assert session.interactive is False


# ---- pointer -------------------------------------------------------

def test_on_motion_sets_the_cursor_from_data_coordinates():
    session, _, _ = make_gui_session()
    session.on_motion(5432.1, 2.5)
    assert session.view.cursor_x == pytest.approx(5432.1)
    assert session.view.cursor_y == pytest.approx(2.5)


def test_motion_does_not_redraw(monkeypatch):
    # 182 ms a frame at 1200x800; tracking the pointer through a full render
    # is not possible. Motion must never reach plot.draw().
    session, _, _ = make_gui_session()
    calls = []
    monkeypatch.setattr(session.plot, "draw", lambda req: calls.append(req))
    session.on_motion(5100.0, 1.0)
    session.on_motion(5200.0, 1.5)
    assert calls == []


# ---- output --------------------------------------------------------

def test_messages_scroll_past_in_the_transcript():
    session, _, out = make_gui_session()
    session.message("center = 5001.2")
    assert "center = 5001.2\n" in out.getvalue()


def test_an_empty_message_does_not_print_a_blank_line():
    session, _, out = make_gui_session()
    session.message("")
    assert out.getvalue() == ""


def test_prompt_echo_is_redrawn_in_place_not_appended():
    session, _, out = make_gui_session()
    session.echo(": s")
    session.echo(": sh")
    assert out.getvalue().count("\n") == 0


def test_await_line_echoes_over_itself_rather_than_scrolling():
    session, _, out = make_gui_session()
    session.await_line(": ", lambda s, text: None)
    for char in "show":
        session.handle(Key("char", char))
    assert out.getvalue().count("\n") == 0
    assert out.getvalue().endswith(": show\x1b[K")


def test_help_scrolls_past_instead_of_paging():
    session, _, out = make_gui_session()
    session.showing_help = True
    session.render()
    assert session.showing_help is False
    assert out.getvalue().count("\n") > 5


def test_the_measurement_log_scrolls_past_instead_of_paging():
    session, _, out = make_gui_session()
    session.showing_log = True
    session.render()
    assert session.showing_log is False
    assert "no measurements recorded yet" in out.getvalue()


# ---- the loop ------------------------------------------------------

def test_run_dispatches_window_keys_and_exits_when_the_window_closes():
    session, renderer, _ = make_gui_session(
        script=[[Key("char", ")")], [Key("right")]])
    start_index = session.view.index
    session.run()
    assert session.view.index != start_index
    assert renderer.closed is True
    assert session.finished is True


def test_run_puts_the_readout_in_the_window_title():
    session, renderer, _ = make_gui_session(script=[[Key("right")]])
    session.run()
    assert any("pix=" in title for title in renderer.titles)


def test_run_routes_motion_to_the_cursor_and_keys_to_dispatch():
    # The key comes first: ')' re-autoscales and recentres the cursor when
    # :wreset is on, which it is by default, so a motion before it would be
    # overwritten and the assertion would prove nothing.
    session, _, _ = make_gui_session(
        script=[[Key("char", ")")], [Motion(5300.0, 3.0)]])
    start_index = session.view.index
    session.run()
    assert session.view.cursor_x == pytest.approx(5300.0)
    assert session.view.index != start_index


def test_run_exits_on_q_as_well_as_on_a_closed_window():
    session, _, _ = make_gui_session(script=[[Key("char", "q")]] + [[]] * 5)
    session.run()
    assert session.finished is True


def test_run_never_paints_a_tui():
    # The regression that matters: in two-window mode the terminal is a plain
    # scrolling transcript, so none of the screen-control sequences appear.
    session, _, out = make_gui_session(
        script=[[Key("char", ")")], [Motion(5500.0, 3.0)]])
    session.run()
    text = out.getvalue()
    for sequence in TUI_SEQUENCES:
        assert sequence not in text


def test_teardown_writes_no_terminal_restoration_in_gui_mode():
    session, renderer, out = make_gui_session()
    session.teardown()
    assert renderer.torn_down is True
    for sequence in TUI_SEQUENCES:
        assert sequence not in out.getvalue()


# ---- cli wiring ----------------------------------------------------

def test_gui_is_offered_as_a_renderer_choice():
    from specterm1d.cli import RENDERERS, build_parser

    assert RENDERERS == ("kitty", "iterm2", "sixel", "gui", "halfblock")
    assert build_parser().parse_args(["--renderer", "gui", "x.fits"]).renderer == "gui"


def test_the_gui_shortcut_selects_the_gui_renderer():
    from specterm1d.cli import build_parser, resolve_renderer_choice

    args = build_parser().parse_args(["--gui", "x.fits"])
    assert resolve_renderer_choice(args) == "gui"


def test_an_explicit_renderer_wins_over_the_gui_shortcut():
    from specterm1d.cli import build_parser, resolve_renderer_choice

    args = build_parser().parse_args(["--gui", "--renderer", "halfblock", "x.fits"])
    assert resolve_renderer_choice(args) == "halfblock"


def test_no_flags_leaves_the_choice_to_probing():
    from specterm1d.cli import build_parser, resolve_renderer_choice

    assert resolve_renderer_choice(build_parser().parse_args(["x.fits"])) is None


def test_a_window_that_will_not_open_falls_back_with_one_warning(capsys):
    from specterm1d.cli import attach_or_fall_back
    from specterm1d.term import gui as gui_mod

    class Refuses(gui_mod.GuiRenderer):
        def attach(self, plot):
            raise gui_mod.GuiUnavailable("tkagg: no display name and no $DISPLAY")

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=True)
    renderer = attach_or_fall_back(Refuses(), SpectrumPlot(400, 300), caps,
                                   out=io.StringIO())
    assert renderer.name == "halfblock"
    captured = capsys.readouterr()
    assert "graphics window unavailable" in captured.err
    assert captured.err.count("\n") == 1


def test_the_tty_check_still_refuses_a_pipe_in_gui_mode(monkeypatch, capsys,
                                                       tabular_fits):
    # The text half is half the interface: a graphics window with its prompts
    # redirected to a pipe is not a usable tool. --dump and --cursor remain
    # the headless paths. tabular_fits is the conftest fixture, so the loader
    # succeeds and the tty check is what returns 1.
    from specterm1d import cli

    monkeypatch.setattr(
        cli.caps_mod, "detect",
        lambda **kwargs: TerminalCaps(False, False, False, False, 24, 80,
                                      None, None, False),
    )
    assert cli.main(["--gui", str(tabular_fits)]) == 1
    assert "not a tty" in capsys.readouterr().err


def test_a_terminal_renderer_passes_straight_through_attachment():
    from specterm1d.cli import attach_or_fall_back
    from specterm1d.term.halfblock import HalfblockRenderer

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=False)
    renderer = HalfblockRenderer(out=io.StringIO())
    assert attach_or_fall_back(renderer, SpectrumPlot(116, 82), caps,
                               out=io.StringIO()) is renderer


# ---- crosshair wiring ----------------------------------------------

class CrosshairGui(FakeGui):
    def __init__(self, script=()):
        super().__init__(script)
        self.crosshairs = []
        self.invalidations = 0

    def crosshair(self, x, y):
        self.crosshairs.append((x, y))

    def invalidate(self):
        self.invalidations += 1


def test_motion_moves_the_crosshair_without_a_render():
    session, _, _ = make_gui_session()
    session.renderer = CrosshairGui()
    session.renderer.attach(session.plot)
    session.on_motion(5500.0, 3.0)
    assert session.renderer.crosshairs == [(5500.0, 3.0)]


def test_a_full_render_invalidates_the_crosshair_background():
    session, _, _ = make_gui_session()
    session.renderer = CrosshairGui()
    session.renderer.attach(session.plot)
    session.render()
    assert session.renderer.invalidations == 1


def test_the_gui_render_does_not_draw_the_cursor_as_a_marker():
    # The pointer and the blitted crosshair already show it; a marker line
    # would freeze at the last render and read as a second, stale cursor.
    session, _, _ = make_gui_session()
    requests = []
    session.plot.draw = requests.append
    session.view.cursor_x = 5500.0
    session.view.markers.append(5100.0)
    session.render()
    assert requests[-1].markers == (5100.0,)


def test_the_terminal_render_still_draws_the_cursor_as_a_marker():
    from specterm1d.term.halfblock import HalfblockRenderer

    out = io.StringIO()
    spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 1.0))
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x")
    caps = TerminalCaps(False, False, False, True, 24, 80, None, None, True)
    session = Session(coll, HalfblockRenderer(out=out), SpectrumPlot(80, 44),
                      out, caps)
    session.view.reset_limits()
    session.view.cursor_x = 5500.0
    requests = []
    session.plot.render = lambda req: (requests.append(req),
                                       np.zeros((44, 80, 4), dtype=np.uint8))[1]
    session.render()
    assert 5500.0 in requests[-1].markers
