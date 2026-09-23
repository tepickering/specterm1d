# tests/test_measure.py
import re

import pytest

import specterm1d.commands  # noqa: F401
from specterm1d.commands.measure import format_measure
from specterm1d.term.input import Key
from tests.test_session import make_session


def mark(session, x, y):
    session.view.cursor_x = x
    session.view.cursor_y = y
    session.handle(Key("char", " "))


def test_e_reports_and_logs_an_equivalent_width():
    session, _ = make_session()
    session.handle(Key("char", "e"))
    mark(session, 5200.0, 1.0)
    mark(session, 5400.0, 1.0)
    assert "eqw" in session.last_message.lower()
    # eqwidth.x's four-field row: center, cont, flux, eqw. The fixture's flux
    # sits exactly on the marked continuum, so the width is zero. (The
    # centroid is undefined there, which is correct: there is no line.)
    fields = session.log.lines[-1].split()
    assert len(fields) == 4
    assert float(fields[-1]) == pytest.approx(0.0, abs=1e-6)


def test_e_takes_the_continuum_from_the_cursor_y():
    session, _ = make_session()
    session.handle(Key("char", "e"))
    mark(session, 5200.0, 2.0)
    mark(session, 5400.0, 2.0)
    # The fixture's flux is 1.0. Marking the continuum at 2.0 means half of it
    # is missing across 200 A, so EW = (1 - 1/2) * 200 = 100 A. Reading the
    # continuum off the spectrum instead would have given zero.
    eqw = float(session.log.lines[-1].split()[-1])
    assert eqw == pytest.approx(100.0, rel=0.02)


def test_e_needs_two_distinct_positions():
    session, _ = make_session()
    session.handle(Key("char", "e"))
    mark(session, 5300.0, 1.0)
    mark(session, 5300.0, 1.0)
    assert "move" in session.last_message.lower() or \
           "distinct" in session.last_message.lower()


def test_m_reports_mean_rms_and_snr():
    session, _ = make_session()
    session.handle(Key("char", "m"))
    mark(session, 5200.0, 0.0)
    mark(session, 5400.0, 0.0)
    lowered = session.last_message.lower()
    assert "avg" in lowered and "rms" in lowered and "snr" in lowered


def test_m_logs_without_a_column_header():
    from specterm1d.logfile import COLUMN_HEADER

    session, _ = make_session()
    session.handle(Key("char", "m"))
    mark(session, 5200.0, 0.0)
    mark(session, 5400.0, 0.0)
    assert COLUMN_HEADER not in session.log.lines
    assert session.log.lines[-1].startswith("avg:")


def test_m_on_an_empty_region_is_reported():
    session, _ = make_session()
    session.handle(Key("char", "m"))
    mark(session, 9000.0, 0.0)
    mark(session, 9500.0, 0.0)
    assert "no " in session.last_message.lower()


def test_measurement_draws_a_marker_on_the_plot():
    session, _ = make_session()
    session.handle(Key("char", "e"))
    mark(session, 5200.0, 1.0)
    mark(session, 5400.0, 1.0)
    assert session.view.markers


# ---- an unreliable fit says so -------------------------------------

def _bad_continuum_session():
    """A session marked up for a fit whose continuum is far too high."""
    import io

    import numpy as np

    from specterm1d.plot import SpectrumPlot
    from specterm1d.session import Session
    from specterm1d.spec import SpecCollection, SpecEntry, build_spec
    from specterm1d.term.caps import TerminalCaps
    from specterm1d.term.text import TextRenderer

    wave = np.linspace(4995.0, 5025.0, 400)
    flux = 6000.0 + 4.3e6 * np.exp(-0.5 * ((wave - 5009.2) / 1.7) ** 2)
    spec = build_spec(wave, flux, sigma=np.sqrt(flux) + 13.0)
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x")
    caps = TerminalCaps(False, False, False, True, 24, 80, None, None, True)
    out = io.StringIO()
    session = Session(coll, TextRenderer(out=out), SpectrumPlot(80, 44),
                      out, caps)
    session.view.reset_limits()
    return session


def test_a_saturated_fit_is_flagged_in_the_message():
    session = _bad_continuum_session()
    session.view.cursor_y = 2144858.0
    for char in "kg":
        session.handle(Key("char", char))
    for x in (4995.0, 5025.0):
        session.view.cursor_x = x
        session.handle(Key("char", " "))
    assert "check the continuum" in session.last_message


def test_a_saturated_fit_is_still_reported_and_logged():
    session = _bad_continuum_session()
    session.view.cursor_y = 2144858.0
    for char in "kg":
        session.handle(Key("char", char))
    for x in (4995.0, 5025.0):
        session.view.cursor_x = x
        session.handle(Key("char", " "))
    assert "cen=" in session.last_message
    assert session.log.lines


def test_a_good_fit_carries_no_warning():
    session = _bad_continuum_session()
    session.view.cursor_y = 6000.0
    for char in "kg":
        session.handle(Key("char", char))
    for x in (4995.0, 5025.0):
        session.view.cursor_x = x
        session.handle(Key("char", " "))
    assert "check the continuum" not in session.last_message


def test_a_good_fit_reports_its_uncertainties_and_chi_square():
    session = _bad_continuum_session()
    session.view.cursor_y = 6000.0
    for char in "kg":
        session.handle(Key("char", char))
    for x in (4995.0, 5025.0):
        session.view.cursor_x = x
        session.handle(Key("char", " "))
    message = session.last_message
    assert re.search(r"cen=5009\.2\d* ± [0-9.e-]+(  |$)", message)
    assert re.search(r"  eqw=-?[0-9.e-]+ ± [0-9.e-]+(  |$)", message)
    assert re.search(r"  ampl=-?[0-9.e-]+ ± [0-9.e-]+(  |$)", message)
    assert re.search(r"  chi2_r=[0-9.e-]+", message)
    assert "core" not in message and "center" not in message
    assert "lfwhm" not in message                  # a gaussian has none
    assert "   " not in message                    # no fixed-width padding
    assert "+/-" not in message


def test_a_fit_without_errors_shows_no_plus_minus():
    session = _bad_continuum_session()
    session.view.cursor_y = 2144858.0          # a fit pinned to its bounds
    for char in "kg":
        session.handle(Key("char", char))
    for x in (4995.0, 5025.0):
        session.view.cursor_x = x
        session.handle(Key("char", " "))
    assert "±" not in session.last_message


def test_the_profile_fit_uses_the_spectrum_mask():
    import numpy as np

    session = _bad_continuum_session()
    spec = session.view.current_spec()
    near = np.abs(spec.wave - 5000.0) < 0.3
    spec.flux[near] += 3e6              # a bad-pixel spike...
    spec.good[near] = False             # ...that the mask flags
    session.view.cursor_y = 6000.0
    for char in "kg":
        session.handle(Key("char", char))
    for x in (4995.0, 5025.0):
        session.view.cursor_x = x
        session.handle(Key("char", " "))
    assert "cen=5009.2" in session.last_message


def test_e_quotes_its_errors_inline():
    session = _bad_continuum_session()
    session.handle(Key("char", "e"))
    mark(session, 4995.0, 6000.0)
    mark(session, 5025.0, 6000.0)
    message = session.last_message
    assert re.search(r"  eqw=-?[0-9.e-]+ ± [0-9.e-]+  ", message)
    assert re.search(r"  cont=6000  ", message)
    assert re.search(r"  flux=-?[0-9.e-]+ ± [0-9.e-]+$", message)
    assert "+/-" not in message and "   " not in message


def test_e_without_sigma_shows_no_plus_minus():
    session, _ = make_session()
    session.handle(Key("char", "e"))
    mark(session, 5200.0, 2.0)
    mark(session, 5400.0, 2.0)
    assert "±" not in session.last_message



# ---- values are quoted to the precision their errors support --------

@pytest.mark.parametrize(("value", "err", "sig", "text"), [
    (5500.0061, 0.0234, 7, "5500.006 ± 0.023"),       # rounded to the error
    (2.48213, 0.0241, 4, "2.482 ± 0.024"),
    (-0.47372, 0.00451, 6, "-0.4737 ± 0.0045"),
    (1832571.0, 159.0, 6, "1.83257e6 ± 160"),         # error to two figures
    (1.8279e-15, 3.71e-18, 6, "1.8279e-15 ± 3.7e-18"),
    (9.996, 0.0213, 4, "9.996 ± 0.021"),
    (9.9996, 0.213, 4, "10.00 ± 0.21"),               # rounding carries a digit
    (5500.000012, 0.00017, 7, "5500.000 ± 0.00017"),  # never past sig figures
    (3.0, 51.0, 4, "3 ± 51"),                         # error bigger than value
    (0.0, 0.012, 4, "0.000 ± 0.012"),
    (5009.2, float("nan"), 7, "5009.2"),              # no error: sig figures
    (1.83235e7, float("nan"), 6, "1.83235e7"),
    (float("nan"), 0.1, 4, "nan"),
])
def test_format_measure(value, err, sig, text):
    assert format_measure(value, err, sig) == text


def test_the_bounds_warning_survives_the_wrap_at_80_columns():
    from specterm1d.session import wrap_message

    # A voigt has the most fields, so it is the one that spills furthest.
    session = _bad_continuum_session()
    session.view.cursor_y = 2144858.0
    for char in "kv":
        session.handle(Key("char", char))
    for x in (4995.0, 5025.0):
        session.view.cursor_x = x
        session.handle(Key("char", " "))
    shown = "  ".join(wrap_message(session.last_message, 80))
    assert "check the continuum" in shown
