# tests/test_keymap.py
import pytest

from specterm1d.keymap import (
    AwaitCursor, AwaitKey, AwaitLine, DEFERRED, KEYMAP, command,
    get_command, help_text,
)
from specterm1d.term.input import Key
from tests.test_session import make_session


def test_every_splot_key_is_bound_or_deferred():
    splot_keys = set("?/ abcdefghijklmnopqrstuvwxyz()#%$-,.I")
    missing = splot_keys - set(KEYMAP)
    assert missing == set(), f"unbound splot keys: {sorted(missing)}"


def test_deferred_keys_are_the_documented_set():
    assert set(DEFERRED) == set("dtfijxpuy")


def test_deferred_keys_are_marked_in_the_keymap():
    for key in DEFERRED:
        assert KEYMAP[key].deferred is True


def test_no_deferred_key_has_been_rebound_to_something_else():
    for key, reason in DEFERRED.items():
        assert get_command(KEYMAP[key].name) is None


def test_pressing_a_deferred_key_reports_not_implemented():
    session, _ = make_session()
    assert session.handle(Key("char", "d")) is True
    assert "not implemented" in session.last_message
    assert "deblend" in session.last_message


def test_unbound_key_is_reported_distinctly():
    session, _ = make_session()
    session.handle(Key("char", "Q"))
    assert "unbound" in session.last_message


def test_command_decorator_registers_by_name():
    @command("test.temporary")
    def _handler(session):
        return "ran"

    assert get_command("test.temporary") is _handler


def test_await_key_routes_the_next_keystroke():
    session, _ = make_session()
    seen = []
    session.await_key("choose", lambda s, ch: seen.append(ch),
                      {"g": "gaussian"})
    session.handle(Key("char", "g"))
    assert seen == ["g"]
    assert session.pending is None


def test_await_key_shows_its_options_in_the_message():
    session, _ = make_session()
    session.await_key("profile", lambda s, ch: None, {"g": "gaussian",
                                                      "l": "lorentzian"})
    assert "gaussian" in session.last_message


def test_escape_cancels_a_pending_await_key():
    session, _ = make_session()
    session.await_key("choose", lambda s, ch: pytest.fail("should not fire"), {})
    session.handle(Key("escape"))
    assert session.pending is None
    assert "cancel" in session.last_message.lower()


def test_await_cursor_collects_the_requested_number_of_positions():
    session, _ = make_session()
    session.view.reset_limits()
    got = []
    session.await_cursor(2, "mark two points", lambda s, xs: got.append(xs))
    session.view.cursor_x = 5100.0
    session.handle(Key("char", " "))
    assert got == []
    session.view.cursor_x = 5200.0
    session.handle(Key("char", " "))
    assert [x for x, _ in got[0]] == [5100.0, 5200.0]
    assert all(isinstance(y, float) for _, y in got[0])
    assert session.pending is None


def test_await_cursor_lets_arrow_keys_move_between_marks():
    session, _ = make_session()
    session.view.reset_limits()
    session.await_cursor(2, "mark", lambda s, xs: None)
    before = session.view.cursor_x
    session.handle(Key("right"))
    assert session.view.cursor_x > before
    assert session.pending is not None


def test_await_line_accumulates_and_submits_on_enter():
    session, _ = make_session()
    got = []
    session.await_line("name: ", lambda s, text: got.append(text))
    for ch in "abc":
        session.handle(Key("char", ch))
    session.handle(Key("enter"))
    assert got == ["abc"]


def test_await_line_backspace_edits_the_buffer():
    session, _ = make_session()
    got = []
    session.await_line("name: ", lambda s, text: got.append(text))
    for ch in "abc":
        session.handle(Key("char", ch))
    session.handle(Key("backspace"))
    session.handle(Key("enter"))
    assert got == ["ab"]


def test_await_line_escape_delivers_none():
    session, _ = make_session()
    got = []
    session.await_line("name: ", lambda s, text: got.append(text))
    session.handle(Key("escape"))
    assert got == [None]


def test_help_text_wraps_to_the_terminal_width():
    lines = help_text(cols=80)
    assert lines
    assert all(len(line) <= 80 for line in lines)


def test_help_text_mentions_deferred_status():
    joined = "\n".join(help_text(cols=100))
    assert "deblend" in joined
    assert "not implemented" in joined.lower()
