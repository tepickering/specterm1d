# tests/test_transform.py
import astropy.units as u
import numpy as np
import pytest

import specterm1d.commands  # noqa: F401
from specterm1d.commands.transform import boxcar
from specterm1d.spec import SpecCollection, SpecEntry, build_spec
from specterm1d.term.input import Key
from specterm1d.view import ViewState
from tests.test_session import make_session


def press(session, *chars):
    for ch in chars:
        session.handle(Key("char", ch))


def type_line(session, text):
    for ch in text:
        session.handle(Key("char", ch))
    session.handle(Key("enter"))


def test_boxcar_averages_a_flat_array_to_itself():
    flux = np.full(20, 3.0)
    good = np.ones(20, dtype=bool)
    smoothed, _ = boxcar(flux, good, 5)
    assert np.allclose(smoothed, 3.0)


def test_boxcar_ignores_masked_pixels():
    flux = np.full(20, 1.0)
    flux[10] = 1000.0            # a bad pixel...
    good = np.ones(20, dtype=bool)
    good[10] = False             # ...that is masked
    smoothed, _ = boxcar(flux, good, 5)
    assert np.allclose(smoothed[8:13][good[8:13]], 1.0)


def test_boxcar_reduces_sigma_by_root_n():
    flux = np.zeros(20)
    good = np.ones(20, dtype=bool)
    sigma = np.full(20, 1.0)
    _, out_sigma = boxcar(flux, good, 4, sigma=sigma)
    assert out_sigma[10] == pytest.approx(0.5, rel=0.01)


def test_boxcar_rejects_a_non_positive_box():
    with pytest.raises(ValueError):
        boxcar(np.zeros(5), np.ones(5, dtype=bool), 0)


def test_s_prompts_for_a_box_and_smooths():
    session, _ = make_session()
    press(session, "s")
    type_line(session, "5")
    assert "5" in session.last_message
    assert session.view.undo_stack


def test_s_rejects_a_non_numeric_box():
    session, _ = make_session()
    press(session, "s")
    type_line(session, "wide")
    assert "wide" in session.last_message
    assert not session.view.undo_stack


def test_undo_restores_the_previous_spectrum():
    session, _ = make_session()
    original = session.view.current_spec().flux.copy()
    press(session, "s")
    type_line(session, "5")
    press(session, "U")
    assert np.allclose(session.view.current_spec().flux, original)


def test_undo_with_an_empty_stack_says_so():
    session, _ = make_session()
    press(session, "U")
    assert "nothing" in session.last_message.lower()


def test_undo_unwinds_in_order():
    session, _ = make_session()
    press(session, "s")
    type_line(session, "3")
    press(session, "s")
    type_line(session, "7")
    assert len(session.view.undo_stack) == 2
    press(session, "U")
    assert len(session.view.undo_stack) == 1


def test_transforms_are_scoped_to_the_current_entry():
    session, _ = make_session(n_entries=2)
    press(session, "s")
    type_line(session, "5")
    smoothed = session.view.current_spec().flux.copy()
    press(session, ")")
    assert not np.allclose(session.view.current_spec().flux[:5], smoothed[:5])
    press(session, "(")
    assert np.allclose(session.view.current_spec().flux, smoothed)


def _fluxed_session():
    wave = np.linspace(5000.0, 6000.0, 100)
    spec = build_spec(wave, np.full(100, 1.0),
                      flux_unit=u.Unit("1e-17 erg / (s cm2 AA)"))
    coll = SpecCollection(entries=[SpecEntry("a", {"v": spec}, "v")])
    session, _ = make_session()
    session.collection = coll
    session.view = ViewState(coll)
    session.view.reset_limits()
    session.view.cursor_x = 5500.0
    return session


def test_n_converts_flambda_to_fnu():
    session = _fluxed_session()
    press(session, "n")
    unit = session.view.current_spec().flux_unit
    assert unit.is_equivalent(u.Unit("erg / (s cm2 Hz)"))


def test_l_converts_back_to_flambda():
    session = _fluxed_session()
    press(session, "n")
    press(session, "l")
    unit = session.view.current_spec().flux_unit
    assert unit.is_equivalent(u.Unit("erg / (s cm2 AA)"))


def test_flux_conversion_on_uncalibrated_counts_is_refused():
    session, _ = make_session()   # flux_unit is None
    press(session, "n")
    assert "calibrat" in session.last_message.lower()
    assert not session.view.undo_stack
