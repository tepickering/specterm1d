# tests/test_cursorscript.py
import pytest

from specterm1d.cursorscript import parse_script, run_script
from tests.test_session import make_session


def test_blank_lines_and_comments_are_ignored():
    steps = parse_script("# a comment\n\n   \n5000 1.0 e\n")
    assert len(steps) == 1


def test_position_and_key_are_parsed():
    step = parse_script("5200 1.5 e")[0]
    assert step.x == 5200.0 and step.y == 1.5
    assert step.keys == ["e"]


def test_dash_means_keep_the_current_cursor():
    step = parse_script("- - q")[0]
    assert step.x is None and step.y is None


def test_named_keys_are_recognised():
    assert parse_script("- - <space>")[0].keys == [" "]
    assert parse_script("- - <enter>")[0].keys == ["\n"]
    assert parse_script("- - <escape>")[0].keys == ["\x1b"]


def test_trailing_text_is_typed_then_entered():
    step = parse_script("- - s 5")[0]
    assert step.keys == ["s", "5", "\n"]


def test_colon_line_becomes_a_colon_command():
    step = parse_script(":units nm")[0]
    assert step.keys[0] == ":"
    assert step.keys[-1] == "\n"
    assert "".join(step.keys[1:-1]) == "units nm"


def test_malformed_line_is_reported_with_its_number():
    with pytest.raises(ValueError, match="line 2"):
        parse_script("5000 1.0 e\nnonsense\n")


def test_run_script_moves_the_cursor_and_dispatches():
    session, _ = make_session()
    run_script(session, parse_script("5200 1.0 <space>"))
    assert session.view.cursor_x == 5200.0
    assert "5200" in session.last_message


def test_run_script_performs_a_full_measurement():
    # 'e' arms the measurement; each continuum point is then marked with an
    # explicit <space>, so a two-point measurement takes three keystrokes.
    session, _ = make_session()
    run_script(session, parse_script(
        "5200 1.0 e\n"
        "5200 1.0 <space>\n"
        "5400 1.0 <space>\n"
    ))
    assert len(session.log.lines[-1].split()) == 4      # eqwidth.x row
    assert "eqw" in session.last_message.lower()


def test_run_script_stops_cleanly_on_quit():
    session, _ = make_session()
    run_script(session, parse_script("- - q\n- - <space>"))
    assert session.finished is True
