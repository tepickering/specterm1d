# tests/test_fitting.py
import numpy as np
import pytest

from specterm1d.fitting import region_stats, sumflux


def gaussian_absorption(wave, centre=5500.0, fwhm=5.0, depth=0.5, cont=1.0):
    sigma = fwhm / (2 * np.sqrt(2 * np.log(2)))
    return cont - depth * np.exp(-0.5 * ((wave - centre) / sigma) ** 2)


def test_flat_continuum_gives_zero_equivalent_width():
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = np.ones_like(wave)
    result = sumflux(wave, flux, None, 5450.0, 1.0, 5550.0, 1.0)
    assert result.eqw == pytest.approx(0.0, abs=1e-6)
    assert result.flux == pytest.approx(0.0, abs=1e-6)


def test_absorption_line_has_positive_equivalent_width():
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = gaussian_absorption(wave)
    result = sumflux(wave, flux, None, 5450.0, 1.0, 5550.0, 1.0)
    assert result.eqw > 0


def test_equivalent_width_matches_the_analytic_value():
    # For a Gaussian of depth d and FWHM w on a unit continuum,
    # EW = d * w * sqrt(pi / (4 ln 2)).
    wave = np.linspace(5400.0, 5600.0, 20001)
    depth, fwhm = 0.5, 5.0
    flux = gaussian_absorption(wave, depth=depth, fwhm=fwhm)
    expected = depth * fwhm * np.sqrt(np.pi / (4 * np.log(2)))
    result = sumflux(wave, flux, None, 5450.0, 1.0, 5550.0, 1.0)
    assert result.eqw == pytest.approx(expected, rel=0.01)


def test_emission_line_has_negative_equivalent_width():
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = 2.0 - gaussian_absorption(wave)
    result = sumflux(wave, flux, None, 5450.0, 1.0, 5550.0, 1.0)
    assert result.eqw < 0


def test_centroid_lands_on_the_line_centre():
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = gaussian_absorption(wave, centre=5510.0)
    result = sumflux(wave, flux, None, 5450.0, 1.0, 5550.0, 1.0)
    assert result.center == pytest.approx(5510.0, abs=0.5)


def test_centroid_uses_the_one_point_five_power_weighting():
    # sumflux.x: csum += abs(delta)**1.5 * x[i]. A plain |delta| weighting
    # gives a measurably different centroid for an asymmetric profile.
    wave = np.linspace(5400.0, 5600.0, 4001)
    flux = (gaussian_absorption(wave, centre=5480.0, depth=0.6, fwhm=4.0)
            + gaussian_absorption(wave, centre=5520.0, depth=0.2, fwhm=4.0) - 1.0)
    result = sumflux(wave, flux, None, 5450.0, 1.0, 5550.0, 1.0)

    ramp = np.ones_like(wave)
    inside = (wave >= 5450.0) & (wave <= 5550.0)
    delta = np.abs(flux - ramp)[inside]
    linear = (delta * wave[inside]).sum() / delta.sum()
    assert abs(result.center - linear) > 0.05


def test_sloped_continuum_is_handled():
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = 1.0 + (wave - 5400.0) * 0.001
    y1 = 1.0 + (5450.0 - 5400.0) * 0.001
    y2 = 1.0 + (5550.0 - 5400.0) * 0.001
    result = sumflux(wave, flux, None, 5450.0, y1, 5550.0, y2)
    assert result.eqw == pytest.approx(0.0, abs=1e-3)


def test_marked_points_may_be_given_in_either_order():
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = gaussian_absorption(wave)
    forward = sumflux(wave, flux, None, 5450.0, 1.0, 5550.0, 1.0)
    reverse = sumflux(wave, flux, None, 5550.0, 1.0, 5450.0, 1.0)
    assert forward.eqw == pytest.approx(reverse.eqw, rel=1e-6)


def test_zero_continuum_yields_an_undefined_equivalent_width():
    # sumflux.x sets esum to INDEF when the ramp passes through zero.
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = gaussian_absorption(wave)
    result = sumflux(wave, flux, None, 5450.0, 0.0, 5550.0, 0.0)
    assert np.isnan(result.eqw)


def test_errors_are_propagated_when_sigma_is_supplied():
    wave = np.linspace(5400.0, 5600.0, 2001)
    flux = gaussian_absorption(wave)
    sigma = np.full_like(wave, 0.01)
    result = sumflux(wave, flux, sigma, 5450.0, 1.0, 5550.0, 1.0)
    assert result.flux_err > 0
    assert result.eqw_err > 0


def test_errors_are_nan_without_sigma():
    wave = np.linspace(5400.0, 5600.0, 2001)
    result = sumflux(wave, np.ones_like(wave), None, 5450.0, 1.0, 5550.0, 1.0)
    assert np.isnan(result.flux_err)


def test_region_stats_on_known_data():
    wave = np.linspace(5000.0, 6000.0, 1001)
    flux = np.full(1001, 4.0)
    good = np.ones(1001, dtype=bool)
    stats = region_stats(wave, flux, good, None, 5200.0, 5800.0)
    assert stats.mean == pytest.approx(4.0)
    assert stats.rms == pytest.approx(0.0, abs=1e-9)
    assert stats.npix == 601


def test_region_stats_snr_is_mean_over_rms():
    rng = np.random.default_rng(0)
    wave = np.linspace(5000.0, 6000.0, 10001)
    flux = 10.0 + rng.normal(0.0, 0.5, wave.size)
    good = np.ones(wave.size, dtype=bool)
    stats = region_stats(wave, flux, good, None, 5000.0, 6000.0)
    assert stats.snr == pytest.approx(20.0, rel=0.1)


def test_region_stats_excludes_masked_pixels():
    wave = np.linspace(5000.0, 6000.0, 1001)
    flux = np.full(1001, 4.0)
    flux[500] = 1e6
    good = np.ones(1001, dtype=bool)
    good[500] = False
    stats = region_stats(wave, flux, good, None, 5000.0, 6000.0)
    assert stats.mean == pytest.approx(4.0)
    assert stats.npix == 1000


def test_region_stats_reports_propagated_snr_when_sigma_exists():
    wave = np.linspace(5000.0, 6000.0, 1001)
    flux = np.full(1001, 4.0)
    good = np.ones(1001, dtype=bool)
    sigma = np.full(1001, 0.4)
    stats = region_stats(wave, flux, good, sigma, 5000.0, 6000.0)
    assert stats.propagated_snr == pytest.approx(10.0, rel=0.01)


def test_region_stats_on_an_empty_region_is_not_fatal():
    wave = np.linspace(5000.0, 6000.0, 101)
    good = np.ones(101, dtype=bool)
    stats = region_stats(wave, np.ones(101), good, None, 7000.0, 8000.0)
    assert stats.npix == 0
    assert np.isnan(stats.mean)
