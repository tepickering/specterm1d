# tests/test_colon.py
import astropy.units as u

import specterm1d.commands  # noqa: F401
from specterm1d.commands.colon import parse_colon
from specterm1d.term.input import Key
from tests.test_session import make_session


def run_colon(session, text):
    session.handle(Key("char", ":"))
    for ch in text:
        session.handle(Key("char", ch))
    session.handle(Key("enter"))


def test_parse_splits_command_and_arguments():
    assert parse_colon("units nm") == ("units", ["nm"])
    assert parse_colon("log") == ("log", [])
    assert parse_colon("  flip  yes  ") == ("flip", ["yes"])


def test_parse_keeps_comment_text_whole():
    assert parse_colon("# night 2 standard") == ("#", ["night 2 standard"])


def test_log_and_nolog_toggle_the_writer(tmp_path):
    session, _ = make_session()
    session.log.path = tmp_path / "splot.log"
    run_colon(session, "nolog")
    assert session.log.enabled is False
    run_colon(session, "log")
    assert session.log.enabled is True


def test_units_changes_the_axis():
    session, _ = make_session()
    run_colon(session, "units nm")
    assert session.view.axis.unit == u.nm


def test_units_rejects_a_nonsense_unit():
    session, _ = make_session()
    run_colon(session, "units furlongs")
    assert "furlong" in session.last_message


def test_units_accepts_a_frequency():
    session, _ = make_session()
    run_colon(session, "units GHz")
    assert session.view.axis.unit == u.GHz


def test_hash_adds_a_comment_to_the_log():
    session, _ = make_session()
    run_colon(session, "# checked by hand")
    assert session.log.lines[-1] == "# checked by hand"


def test_boolean_toggles_accept_yes_and_no():
    session, _ = make_session()
    run_colon(session, "flip yes")
    assert session.view.flip is True
    run_colon(session, "flip no")
    assert session.view.flip is False


def test_boolean_toggle_with_no_argument_flips():
    session, _ = make_session()
    before = session.view.histogram
    run_colon(session, "hist")
    assert session.view.histogram is not before


def test_zero_and_wreset_map_to_view_fields():
    session, _ = make_session()
    run_colon(session, "zero yes")
    assert session.view.zero_base is True
    run_colon(session, "wreset no")
    assert session.view.window_reset is False


def test_overlay_toggles():
    session, _ = make_session()
    run_colon(session, "sky")
    assert "sky" in session.view.overlays
    run_colon(session, "sky")
    assert "sky" not in session.view.overlays


def test_sigma_and_mask_toggles():
    session, _ = make_session()
    run_colon(session, "sigma")
    assert session.view.show_sigma is True
    run_colon(session, "mask")
    assert session.view.show_mask is True


def test_variant_selects_by_name():
    session, _ = make_session()
    entry = session.collection[0]
    entry.variants["BOX/COUNTS"] = entry.spec()
    run_colon(session, "variant BOX/COUNTS")
    assert session.view.variant == "BOX/COUNTS"


def test_variant_rejects_an_unknown_name():
    session, _ = make_session()
    run_colon(session, "variant NOPE")
    assert "NOPE" in session.last_message


def test_show_displays_previous_measurements():
    session, _ = make_session()
    session.log.record("e", center=1.0, cont=1.0, flux=1.0, eqw=1.0)
    run_colon(session, "show")
    assert session.showing_log is True


def test_unknown_colon_command_is_reported():
    session, _ = make_session()
    run_colon(session, "frobnicate")
    assert "frobnicate" in session.last_message


def test_dispaxis_reports_that_it_does_not_apply():
    # splot's :dispaxis and :nsum are 2D-image concerns; we ingest 1D.
    session, _ = make_session()
    run_colon(session, "dispaxis 2")
    assert "1D" in session.last_message or "not" in session.last_message.lower()
