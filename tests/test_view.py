# tests/test_view.py
import astropy.units as u
import numpy as np
import pytest

from specterm1d.spec import SpecCollection, SpecEntry, build_spec
from specterm1d.view import Axis, ViewState


def make_collection(n_entries=2, npix=100):
    entries = []
    for i in range(n_entries):
        wave = np.linspace(5000.0, 6000.0, npix)
        flux = np.full(npix, float(i + 1))
        spec = build_spec(wave, flux, sigma=np.full(npix, 0.1))
        entries.append(SpecEntry(f"OBJ{i:03d}", {"OPT/COUNTS": spec}, "OPT/COUNTS"))
    return SpecCollection(entries=entries)


def test_axis_wave_mode_converts_units():
    spec = build_spec([5000.0, 6000.0], [1.0, 1.0])
    axis = Axis(mode="wave", unit=u.nm)
    assert np.allclose(axis.to_display(spec, spec.wave), [500.0, 600.0])


def test_axis_wave_mode_round_trips():
    spec = build_spec([5000.0, 6000.0], [1.0, 1.0])
    axis = Axis(mode="wave", unit=u.nm)
    x = axis.to_display(spec, spec.wave)
    assert np.allclose(axis.to_wave(spec, x), spec.wave)


def test_axis_handles_frequency_via_spectral_equivalency():
    spec = build_spec([5000.0], [1.0])
    axis = Axis(mode="wave", unit=u.GHz)
    freq = axis.to_display(spec, spec.wave)
    assert freq[0] > 0
    assert np.allclose(axis.to_wave(spec, freq), spec.wave)


def test_axis_pixel_mode_is_the_index():
    spec = build_spec(np.linspace(5000.0, 6000.0, 101), np.ones(101))
    axis = Axis(mode="pixel")
    x = axis.to_display(spec, spec.wave)
    assert x[0] == 0.0 and x[-1] == 100.0


def test_axis_velocity_mode_is_zero_at_the_origin():
    spec = build_spec([4990.0, 5000.0, 5010.0], [1.0, 1, 1])
    axis = Axis(mode="velocity", velocity_origin=5000.0)
    v = axis.to_display(spec, spec.wave)
    assert v[1] == pytest.approx(0.0)
    assert v[0] < 0 and v[2] > 0
    assert np.allclose(axis.to_wave(spec, v), spec.wave)


def test_axis_label_names_the_mode():
    assert "Pixel" in Axis(mode="pixel").label()
    assert "km/s" in Axis(mode="velocity", velocity_origin=5000.0).label()
    assert "Angstrom" in Axis(mode="wave", unit=u.AA).label()


def test_view_starts_on_the_first_entry():
    view = ViewState(make_collection())
    assert view.index == 0
    assert view.entry.label == "OBJ000"


def test_display_spec_is_ascending_even_in_frequency():
    view = ViewState(make_collection())
    view.set_axis(unit=u.GHz)
    x = view.display_spec().wave
    assert np.all(np.diff(x) > 0)


def test_display_spec_keeps_negative_velocities():
    view = ViewState(make_collection())
    view.set_axis(mode="velocity", velocity_origin=5500.0)
    x = view.display_spec().wave
    assert x.min() < 0
    assert view.display_spec().good.all()


def test_reset_limits_spans_the_good_data():
    view = ViewState(make_collection())
    view.reset_limits()
    assert view.xlim[0] == pytest.approx(5000.0)
    assert view.xlim[1] == pytest.approx(6000.0)
    assert view.ylim[1] > view.ylim[0]


def test_reset_limits_ignores_masked_pixels():
    wave = np.linspace(5000.0, 6000.0, 100)
    mask = np.ones(100, dtype=bool)
    mask[:10] = False
    spec = build_spec(wave, np.ones(100), mask=mask)
    coll = SpecCollection(entries=[SpecEntry("a", {"v": spec}, "v")])
    view = ViewState(coll)
    view.reset_limits()
    assert view.xlim[0] > 5000.0


def test_changing_units_rescales_the_limits():
    view = ViewState(make_collection())
    view.reset_limits()
    view.set_axis(unit=u.nm)
    assert view.xlim[0] == pytest.approx(500.0)
    assert view.xlim[1] == pytest.approx(600.0)


def test_to_request_carries_the_toggles():
    view = ViewState(make_collection())
    view.reset_limits()
    view.show_sigma = True
    view.overlays.add("sky")
    req = view.to_request(title="t")
    assert req.show_sigma is True
    assert "sky" in req.overlays
    assert req.title == "t"


def test_flip_reverses_the_x_limits():
    view = ViewState(make_collection())
    view.reset_limits()
    view.flip = True
    req = view.to_request()
    assert req.xlim[0] > req.xlim[1]


def test_zero_base_pins_the_floor():
    view = ViewState(make_collection())
    view.zero_base = True
    view.reset_limits()
    assert view.ylim[0] == 0.0


def test_variant_selection_falls_back_to_the_default():
    a = build_spec([1.0, 2], [1.0, 1])
    b = build_spec([1.0, 2], [2.0, 2])
    coll = SpecCollection(entries=[
        SpecEntry("x", {"OPT/COUNTS": a, "BOX/COUNTS": b}, "OPT/COUNTS")
    ])
    view = ViewState(coll)
    assert view.current_spec() is a
    view.variant = "BOX/COUNTS"
    assert view.current_spec() is b


def _one_entry_view():
    from specterm1d.spec import SpecCollection, SpecEntry, build_spec
    from specterm1d.view import ViewState

    spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 1.0))
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x")
    view = ViewState(coll)
    view.reset_limits()
    return view


def test_to_request_draws_the_cursor_as_a_marker_by_default():
    view = _one_entry_view()
    view.cursor_x = 5500.0
    assert 5500.0 in view.to_request().markers


def test_to_request_can_leave_the_cursor_out():
    # In two-window mode the pointer and the blitted crosshair already show
    # where the cursor is, and a marker line only updates on a full render -
    # so it freezes behind the pointer and reads as a second, wrong cursor.
    view = _one_entry_view()
    view.cursor_x = 5500.0
    assert 5500.0 not in view.to_request(with_cursor=False).markers


def test_leaving_the_cursor_out_keeps_the_real_markers():
    view = _one_entry_view()
    view.cursor_x = 5500.0
    view.markers.extend([5100.0, 5900.0])
    assert view.to_request(with_cursor=False).markers == (5100.0, 5900.0)


# ---- the cursor's y follows the spectrum until you move it ---------

def test_the_cursor_y_starts_on_the_spectrum():
    # Mid-window is a hopeless continuum guess where one bright line sets the
    # autoscale: on a 2500:1 spectrum it sits a thousand times above the
    # continuum, and walking down to it takes 250 arrow presses.
    view = _one_entry_view()
    view.cursor_x = 5500.0
    view.follow_flux()
    assert view.cursor_y == pytest.approx(1.0)


def test_following_stops_once_you_move_the_cursor_yourself():
    view = _one_entry_view()
    view.cursor_x = 5500.0
    view.follow_flux()
    view.cursor_y = 42.0
    view.lock_cursor_y()
    view.cursor_x = 5600.0
    view.follow_flux()
    assert view.cursor_y == pytest.approx(42.0)


def test_a_new_window_lets_the_cursor_follow_again():
    view = _one_entry_view()
    view.lock_cursor_y()
    view.reset_limits()
    view.cursor_x = 5500.0
    view.follow_flux()
    assert view.cursor_y == pytest.approx(1.0)


def test_following_a_cursor_off_the_spectrum_leaves_y_alone():
    view = _one_entry_view()
    view.cursor_x = 5500.0
    view.follow_flux()
    before = view.cursor_y
    view.cursor_x = None
    view.follow_flux()
    assert view.cursor_y == pytest.approx(before)
