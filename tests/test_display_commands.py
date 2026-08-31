# tests/test_display_commands.py
import numpy as np
import pytest

import specterm1d.commands  # noqa: F401  - registers the handlers
from specterm1d.term.input import Key
from tests.test_session import make_session


def press(session, *chars):
    for ch in chars:
        session.handle(Key("char", ch))


def test_space_reports_position_and_value():
    session, _ = make_session()
    session.view.cursor_x = 5500.0
    press(session, " ")
    assert "5500" in session.last_message
    assert "pix" in session.last_message.lower()


def test_a_with_two_distinct_points_windows_between_them():
    session, _ = make_session()
    press(session, "a")
    session.view.cursor_x = 5200.0
    press(session, " ")
    session.view.cursor_x = 5400.0
    press(session, " ")
    assert session.view.xlim == pytest.approx((5200.0, 5400.0))


def test_a_with_the_same_point_twice_autoscales_everything():
    session, _ = make_session()
    session.view.xlim = (5400.0, 5500.0)
    press(session, "a")
    session.view.cursor_x = 5450.0
    press(session, " ")
    press(session, " ")
    assert session.view.xlim[0] == pytest.approx(5000.0)
    assert session.view.xlim[1] == pytest.approx(6000.0)


def test_a_accepts_the_two_points_in_either_order():
    session, _ = make_session()
    press(session, "a")
    session.view.cursor_x = 5400.0
    press(session, " ")
    session.view.cursor_x = 5200.0
    press(session, " ")
    assert session.view.xlim == pytest.approx((5200.0, 5400.0))


def test_b_toggles_the_zero_base():
    session, _ = make_session()
    press(session, "b")
    assert session.view.zero_base is True
    assert session.view.ylim[0] == 0.0
    press(session, "b")
    assert session.view.zero_base is False


def test_c_clears_windowing_markers_and_fits():
    session, _ = make_session()
    session.view.xlim = (5400.0, 5500.0)
    session.view.markers = [5450.0]
    session.view.fits = [(np.array([1.0]), np.array([1.0]))]
    press(session, "c")
    assert session.view.xlim[0] == pytest.approx(5000.0)
    assert session.view.markers == []
    assert session.view.fits == []


def test_z_halves_the_x_range_about_the_cursor():
    session, _ = make_session()
    session.view.xlim = (5000.0, 6000.0)
    session.view.cursor_x = 5500.0
    press(session, "z")
    lo, hi = session.view.xlim
    assert hi - lo == pytest.approx(500.0)
    assert (lo + hi) / 2 == pytest.approx(5500.0)


def test_comma_and_period_shift_the_window_opposite_ways():
    session, _ = make_session()
    session.view.xlim = (5400.0, 5600.0)
    press(session, ".")
    shifted = session.view.xlim[0]
    assert shifted > 5400.0
    press(session, ",")
    assert session.view.xlim[0] == pytest.approx(5400.0)


def test_shifting_preserves_the_window_width():
    session, _ = make_session()
    session.view.xlim = (5400.0, 5600.0)
    press(session, ".")
    lo, hi = session.view.xlim
    assert hi - lo == pytest.approx(200.0)


def test_paren_keys_step_between_entries():
    session, _ = make_session(n_entries=3)
    press(session, ")")
    assert session.view.index == 1
    press(session, ")")
    assert session.view.index == 2
    press(session, "(")
    assert session.view.index == 1


def test_stepping_past_the_end_is_reported_not_wrapped():
    session, _ = make_session(n_entries=2)
    press(session, ")", ")", ")")
    assert session.view.index == 1
    assert "last" in session.last_message.lower()


def test_hash_prompts_and_jumps_by_index():
    session, _ = make_session(n_entries=3)
    press(session, "#")
    for ch in "3":
        session.handle(Key("char", ch))
    session.handle(Key("enter"))
    assert session.view.index == 2


def test_hash_jumps_by_label():
    session, _ = make_session(n_entries=3)
    press(session, "#")
    for ch in "OBJ001":
        session.handle(Key("char", ch))
    session.handle(Key("enter"))
    assert session.view.index == 1


def test_hash_reports_an_unknown_target():
    session, _ = make_session(n_entries=3)
    press(session, "#")
    for ch in "nope":
        session.handle(Key("char", ch))
    session.handle(Key("enter"))
    assert "nope" in session.last_message


def test_dollar_toggles_pixel_coordinates():
    session, _ = make_session()
    press(session, "$")
    assert session.view.axis.mode == "pixel"
    press(session, "$")
    assert session.view.axis.mode == "wave"


def test_v_sets_the_velocity_origin_at_the_cursor():
    session, _ = make_session()
    session.view.cursor_x = 5500.0
    press(session, "v")
    assert session.view.axis.mode == "velocity"
    assert session.view.axis.velocity_origin == pytest.approx(5500.0)
    press(session, "v")
    assert session.view.axis.mode == "wave"


def test_o_arms_the_overplot_flag():
    session, _ = make_session()
    press(session, "o")
    assert session.view.overplot_next is True


def test_percent_cycles_the_variant():
    session, _ = make_session()
    session.collection[0].variants["BOX/COUNTS"] = session.collection[0].spec()
    press(session, "%")
    assert session.view.variant == "BOX/COUNTS"
    press(session, "%")
    assert session.view.variant == "OPT/COUNTS"


def test_percent_on_a_single_variant_says_so():
    session, _ = make_session()
    press(session, "%")
    assert "only" in session.last_message.lower()


def test_q_exits_when_there_are_no_more_files():
    session, _ = make_session()
    assert session.handle(Key("char", "q")) is False


def test_capital_i_exits_immediately():
    session, _ = make_session()
    assert session.handle(Key("char", "I")) is False


def test_question_mark_shows_the_help_page():
    session, _ = make_session()
    press(session, "?")
    assert session.showing_help is True
    press(session, "?")
    assert session.showing_help is False


def test_slash_cycles_the_status_hints():
    session, _ = make_session()
    first = session.last_message
    press(session, "/")
    second = session.last_message
    press(session, "/")
    assert second != first
    assert session.last_message != second


def test_window_keys_match_the_iraf_gtools_table():
    # Transcribed from IRAF lib/scr/gtools.key. A splot user's fingers already
    # know these, so none of them may be repurposed.
    from specterm1d.keymap import WINDOW_KEYS
    assert set(WINDOW_KEYS) == set("abcdefgjklmnprtuxyz")


def test_window_a_autoscales_both_axes():
    session, _ = make_session()
    session.view.xlim = (5400.0, 5500.0)
    press(session, "w", "a")
    assert session.view.xlim[0] == pytest.approx(5000.0)
    assert session.view.xlim[1] == pytest.approx(6000.0)


def test_window_x_zooms_x_by_two_about_the_cursor():
    session, _ = make_session()
    session.view.xlim = (5000.0, 6000.0)
    session.view.cursor_x = 5500.0
    press(session, "w", "x")
    lo, hi = session.view.xlim
    assert hi - lo == pytest.approx(500.0)
    assert (lo + hi) / 2 == pytest.approx(5500.0)


def test_window_y_zooms_y_and_leaves_x_alone():
    session, _ = make_session()
    session.view.xlim = (5000.0, 6000.0)
    session.view.ylim = (0.0, 4.0)
    session.view.cursor_y = 2.0
    press(session, "w", "y")
    assert session.view.ylim == pytest.approx((1.0, 3.0))
    assert session.view.xlim == pytest.approx((5000.0, 6000.0))


def test_window_j_and_k_set_the_left_and_right_edges():
    session, _ = make_session()
    session.view.xlim = (5000.0, 6000.0)
    session.view.cursor_x = 5200.0
    press(session, "w", "j")
    assert session.view.xlim == pytest.approx((5200.0, 6000.0))
    session.view.cursor_x = 5800.0
    press(session, "w", "k")
    assert session.view.xlim == pytest.approx((5200.0, 5800.0))


def test_window_b_and_t_set_the_bottom_and_top_edges():
    session, _ = make_session()
    session.view.ylim = (0.0, 4.0)
    session.view.cursor_y = 1.0
    press(session, "w", "b")
    assert session.view.ylim == pytest.approx((1.0, 4.0))
    session.view.cursor_y = 3.0
    press(session, "w", "t")
    assert session.view.ylim == pytest.approx((1.0, 3.0))


def test_window_shifts_move_three_quarters_of_the_window():
    session, _ = make_session()
    session.view.xlim = (5000.0, 6000.0)
    press(session, "w", "r")
    assert session.view.xlim == pytest.approx((5750.0, 6750.0))
    press(session, "w", "l")
    assert session.view.xlim == pytest.approx((5000.0, 6000.0))


def test_window_p_pans_to_double_the_window_about_the_cursor():
    # gt_window1 sets cursor +/- d, not +/- d/2, so 'p' doubles the span.
    session, _ = make_session()
    session.view.xlim = (5000.0, 6000.0)
    session.view.cursor_x = 5500.0
    press(session, "w", "p")
    assert session.view.xlim == pytest.approx((4500.0, 6500.0))


def test_window_c_centres_without_changing_the_span():
    session, _ = make_session()
    session.view.xlim = (5000.0, 6000.0)
    session.view.cursor_x = 5200.0
    press(session, "w", "c")
    assert session.view.xlim == pytest.approx((4700.0, 5700.0))


def test_window_f_and_g_flip_the_axes():
    session, _ = make_session()
    press(session, "w", "f")
    assert session.view.flip is True
    press(session, "w", "g")
    assert session.view.flip_y is True
    assert session.view.to_request().ylim[0] > session.view.to_request().ylim[1]


def test_window_e_expands_between_two_marked_corners():
    session, _ = make_session()
    session.view.reset_limits()
    press(session, "w", "e")
    session.view.cursor_x, session.view.cursor_y = 5200.0, 0.5
    press(session, " ")
    session.view.cursor_x, session.view.cursor_y = 5400.0, 2.5
    press(session, " ")
    assert session.view.xlim == pytest.approx((5200.0, 5400.0))
    assert session.view.ylim == pytest.approx((0.5, 2.5))


def test_window_e_leaves_an_axis_alone_when_the_marks_coincide():
    # gt_window2 applies each axis only if the marks differ by more than
    # 0.001 of that axis's span.
    session, _ = make_session()
    session.view.reset_limits()
    before_y = session.view.ylim
    press(session, "w", "e")
    session.view.cursor_x, session.view.cursor_y = 5200.0, 1.0
    press(session, " ")
    session.view.cursor_x = 5400.0
    press(session, " ")
    assert session.view.xlim == pytest.approx((5200.0, 5400.0))
    assert session.view.ylim == pytest.approx(before_y)


def test_window_submode_unknown_key_is_reported():
    session, _ = make_session()
    press(session, "w", "Q")
    assert "Q" in session.last_message


def test_question_mark_actually_renders_the_help_text():
    session, out = make_session()
    press(session, "?")
    session.render()
    text = out.getvalue()
    assert "splot keybindings" in text
    assert "equivalent width" in text
    assert "page 1/" in text


def test_help_page_advances_with_space_and_closes_on_another_key():
    session, _ = make_session()
    press(session, "?")
    session.render()
    assert session.page_index == 0
    press(session, " ")
    assert session.page_index == 1
    press(session, "b")
    assert session.page_index == 0
    press(session, "x")                 # any other key closes
    assert session.showing_help is False


def test_help_paging_stops_at_the_last_page_and_closes():
    session, _ = make_session()
    press(session, "?")
    for _ in range(200):
        session.handle(Key("char", " "))
        if not session.showing_help:
            break
    assert session.showing_help is False


def test_help_keys_do_not_reach_the_normal_dispatch():
    # 'q' must page-close, not quit the session.
    session, _ = make_session()
    press(session, "?")
    assert session.handle(Key("char", "q")) is True
    assert session.showing_help is False


def test_show_renders_the_measurement_log():
    session, out = make_session()
    session.log.record("e", center=5183.6, cont=1.0, flux=-0.5, eqw=0.5)
    press(session, ":")
    for ch in "show":
        session.handle(Key("char", ch))
    session.handle(Key("enter"))
    session.render()
    assert "5183.6" in out.getvalue()
    assert "log page 1/" in out.getvalue()


def test_show_on_an_empty_log_says_so():
    session, out = make_session()
    press(session, ":")
    for ch in "show":
        session.handle(Key("char", ch))
    session.handle(Key("enter"))
    session.render()
    assert "no measurements recorded yet" in out.getvalue()
