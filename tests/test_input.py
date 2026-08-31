# tests/test_input.py
from specterm1d.term.input import parse_keys


def names(buf):
    keys, _ = parse_keys(buf)
    return [k.name for k in keys]


def test_printable_characters_become_char_keys():
    keys, rest = parse_keys(b"abc")
    assert [k.char for k in keys] == ["a", "b", "c"]
    assert all(k.name == "char" for k in keys)
    assert rest == b""


def test_arrow_keys():
    assert names(b"\x1b[A\x1b[B\x1b[C\x1b[D") == ["up", "down", "right", "left"]


def test_application_mode_arrows():
    assert names(b"\x1bOA\x1bOD") == ["up", "left"]


def test_shift_modified_arrows():
    assert names(b"\x1b[1;2A\x1b[1;2C") == ["shift-up", "shift-right"]


def test_ctrl_modified_arrows():
    assert names(b"\x1b[1;5D") == ["ctrl-left"]


def test_home_end_and_tilde_keys():
    assert names(b"\x1b[H\x1b[F\x1b[3~\x1b[5~\x1b[6~") == [
        "home", "end", "delete", "pageup", "pagedown"
    ]


def test_enter_backspace_and_tab():
    assert names(b"\r\x7f\t") == ["enter", "backspace", "tab"]


def test_control_characters():
    assert names(b"\x03") == ["ctrl-c"]
    assert names(b"\x01") == ["ctrl-a"]


def test_incomplete_escape_is_held_for_more_input():
    keys, rest = parse_keys(b"\x1b[")
    assert keys == []
    assert rest == b"\x1b["


def test_incomplete_escape_completes_on_the_next_chunk():
    _, rest = parse_keys(b"\x1b[")
    keys2, rest2 = parse_keys(rest + b"A")
    assert [k.name for k in keys2] == ["up"]
    assert rest2 == b""


def test_lone_escape_followed_by_a_letter_is_two_keys():
    # splot has no alt-bindings, so ESC then 'q' is escape then q.
    assert names(b"\x1bq") == ["escape", "char"]


def test_sgr_mouse_report_is_parsed_as_a_mouse_key():
    keys, _ = parse_keys(b"\x1b[<0;40;12M")
    assert keys[0].name == "mouse"
    assert "40;12" in keys[0].char


def test_utf8_multibyte_character():
    keys, rest = parse_keys("é".encode())
    assert [k.char for k in keys] == ["é"]
    assert rest == b""


def test_incomplete_utf8_is_held():
    raw = "é".encode()
    keys, rest = parse_keys(raw[:1])
    assert keys == []
    assert rest == raw[:1]


def test_splot_two_stage_sequence_parses_as_two_char_keys():
    # 'k' then 'g' - fit a Gaussian.
    keys, _ = parse_keys(b"kg")
    assert [k.char for k in keys] == ["k", "g"]


def test_colon_command_text_parses_as_chars():
    keys, _ = parse_keys(b":log\r")
    assert [k.char for k in keys[:4]] == [":", "l", "o", "g"]
    assert keys[4].name == "enter"
