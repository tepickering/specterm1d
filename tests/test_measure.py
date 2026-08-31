# tests/test_measure.py
import pytest

import specterm1d.commands  # noqa: F401
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
    from specterm1d.term.halfblock import HalfblockRenderer

    wave = np.linspace(4995.0, 5025.0, 400)
    flux = 6000.0 + 4.3e6 * np.exp(-0.5 * ((wave - 5009.2) / 1.7) ** 2)
    spec = build_spec(wave, flux, sigma=np.sqrt(flux) + 13.0)
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x")
    caps = TerminalCaps(False, False, False, True, 24, 80, None, None, True)
    out = io.StringIO()
    session = Session(coll, HalfblockRenderer(out=out), SpectrumPlot(80, 44),
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
    assert "center" in session.last_message
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
