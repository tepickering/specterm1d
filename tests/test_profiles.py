# tests/test_profiles.py
import numpy as np
import pytest

from specterm1d.fitting import (
    fit_profile, gauss_from_width, gaussian, lorentzian, voigt,
)

FWHM_PER_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))


def absorption(wave, centre=5500.0, fwhm=5.0, depth=0.5, cont=1.0):
    sigma = fwhm / FWHM_PER_SIGMA
    return cont + gaussian(wave, centre, -depth, sigma)


def test_gaussian_peaks_at_its_centre():
    x = np.linspace(-10, 10, 1001)
    y = gaussian(x, 0.0, 2.0, 1.0)
    assert y.max() == pytest.approx(2.0)
    assert x[y.argmax()] == pytest.approx(0.0, abs=0.02)


def test_gaussian_fwhm_is_as_defined():
    x = np.linspace(-10, 10, 20001)
    y = gaussian(x, 0.0, 1.0, 1.0)
    above = x[y >= 0.5]
    assert above.max() - above.min() == pytest.approx(FWHM_PER_SIGMA, rel=1e-3)


def test_lorentzian_has_wider_wings_than_a_gaussian():
    x = np.array([10.0])
    assert lorentzian(x, 0.0, 1.0, 1.0)[0] > gaussian(x, 0.0, 1.0, 1.0)[0]


def test_voigt_reduces_to_a_gaussian_as_gamma_goes_to_zero():
    x = np.linspace(-5, 5, 501)
    v = voigt(x, 0.0, 1.0, 1.0, 1e-8)
    g = gaussian(x, 0.0, 1.0, 1.0)
    assert np.allclose(v / v.max(), g / g.max(), atol=1e-4)


def test_fit_recovers_a_known_gaussian():
    wave = np.linspace(5450.0, 5550.0, 2001)
    flux = absorption(wave, centre=5502.0, fwhm=4.0, depth=0.4)
    fit = fit_profile(wave, flux, None, 5460.0, 1.0, 5540.0, 1.0, "g")
    assert fit.center == pytest.approx(5502.0, abs=0.05)
    assert fit.gfwhm == pytest.approx(4.0, rel=0.02)
    assert fit.peak == pytest.approx(-0.4, rel=0.05)


def test_fit_recovers_the_analytic_equivalent_width():
    wave = np.linspace(5450.0, 5550.0, 4001)
    depth, fwhm = 0.4, 4.0
    flux = absorption(wave, fwhm=fwhm, depth=depth)
    expected = depth * fwhm * np.sqrt(np.pi / (4 * np.log(2)))
    fit = fit_profile(wave, flux, None, 5460.0, 1.0, 5540.0, 1.0, "g")
    assert fit.eqw == pytest.approx(expected, rel=0.03)


def test_absorption_gives_positive_eqw_and_negative_flux():
    wave = np.linspace(5450.0, 5550.0, 2001)
    fit = fit_profile(wave, absorption(wave), None, 5460.0, 1.0, 5540.0, 1.0, "g")
    assert fit.eqw > 0 and fit.flux < 0 and fit.peak < 0


def test_emission_gives_negative_eqw_and_positive_flux():
    wave = np.linspace(5450.0, 5550.0, 2001)
    flux = 2.0 - absorption(wave)
    fit = fit_profile(wave, flux, None, 5460.0, 1.0, 5540.0, 1.0, "g")
    assert fit.eqw < 0 and fit.flux > 0 and fit.peak > 0


def test_fit_handles_a_sloped_continuum():
    wave = np.linspace(5450.0, 5550.0, 2001)
    ramp = 1.0 + (wave - 5450.0) * 0.002
    flux = ramp + gaussian(wave, 5500.0, -0.4, 4.0 / FWHM_PER_SIGMA)
    y1 = 1.0 + (5460.0 - 5450.0) * 0.002
    y2 = 1.0 + (5540.0 - 5450.0) * 0.002
    fit = fit_profile(wave, flux, None, 5460.0, y1, 5540.0, y2, "g")
    assert fit.center == pytest.approx(5500.0, abs=0.1)
    assert fit.gfwhm == pytest.approx(4.0, rel=0.05)


def test_lorentzian_fit_reports_lfwhm_and_zero_gfwhm():
    wave = np.linspace(5450.0, 5550.0, 2001)
    flux = 1.0 + lorentzian(wave, 5500.0, -0.4, 2.0)
    fit = fit_profile(wave, flux, None, 5460.0, 1.0, 5540.0, 1.0, "l")
    assert fit.lfwhm == pytest.approx(4.0, rel=0.05)
    assert fit.gfwhm == 0.0


def test_voigt_fit_reports_both_widths():
    wave = np.linspace(5450.0, 5550.0, 2001)
    flux = 1.0 + voigt(wave, 5500.0, -0.4, 1.5, 1.0)
    fit = fit_profile(wave, flux, None, 5460.0, 1.0, 5540.0, 1.0, "v")
    assert fit.gfwhm > 0 and fit.lfwhm > 0


def test_fit_returns_a_model_curve_for_overplotting():
    wave = np.linspace(5450.0, 5550.0, 2001)
    fit = fit_profile(wave, absorption(wave), None, 5460.0, 1.0, 5540.0, 1.0, "g")
    assert fit.model_x.size == fit.model_y.size > 10
    assert fit.model_x.min() >= 5460.0 - 1 and fit.model_x.max() <= 5540.0 + 1


def test_fit_is_inverse_variance_weighted():
    # A deterministic case rather than a noise draw: a draw leaves both fits
    # within a fraction of a pixel and whichever wins is luck. Here a spike
    # deeper than the line sits at 5480, honestly flagged as worthless by the
    # sigma array. The weighted fit must ignore it and find the real line.
    wave = np.linspace(5450.0, 5550.0, 2001)
    flux = absorption(wave, centre=5500.0, fwhm=5.0, depth=0.5)
    sigma = np.full(wave.size, 0.01)
    spike = int(np.abs(wave - 5480.0).argmin())
    flux[spike - 5:spike + 5] -= 2.0
    sigma[spike - 5:spike + 5] = 100.0

    weighted = fit_profile(wave, flux, sigma, 5460.0, 1.0, 5540.0, 1.0, "g")
    unweighted = fit_profile(wave, flux, None, 5460.0, 1.0, 5540.0, 1.0, "g")
    assert weighted.center == pytest.approx(5500.0, abs=0.05)
    assert weighted.gfwhm == pytest.approx(5.0, rel=0.02)
    assert abs(unweighted.center - 5500.0) > 1.0    # captured by the spike


def test_fit_on_pure_noise_does_not_raise():
    rng = np.random.default_rng(1)
    wave = np.linspace(5450.0, 5550.0, 501)
    flux = rng.normal(1.0, 0.1, wave.size)
    fit = fit_profile(wave, flux, None, 5460.0, 1.0, 5540.0, 1.0, "g")
    assert np.isfinite(fit.rms)


def test_gauss_from_width_full_width_mode_recovers_the_fwhm():
    wave = np.linspace(5450.0, 5550.0, 4001)
    flux = absorption(wave, centre=5500.0, fwhm=4.0, depth=0.5)
    fit = gauss_from_width(wave, flux, 5500.0, 1.0, "c")
    assert fit.gfwhm == pytest.approx(4.0, rel=0.03)


def test_gauss_from_width_half_modes_double_the_measured_width():
    wave = np.linspace(5450.0, 5550.0, 4001)
    flux = absorption(wave, centre=5500.0, fwhm=4.0, depth=0.5)
    left = gauss_from_width(wave, flux, 5500.0, 1.0, "a")
    full = gauss_from_width(wave, flux, 5500.0, 1.0, "c")
    assert left.gfwhm == pytest.approx(full.gfwhm, rel=0.05)


def test_gauss_from_width_level_modes_use_the_marked_flux():
    wave = np.linspace(5450.0, 5550.0, 4001)
    flux = absorption(wave, centre=5500.0, fwhm=4.0, depth=0.5)
    narrow = gauss_from_width(wave, flux, 5500.0, 0.6, "k")
    wide = gauss_from_width(wave, flux, 5500.0, 0.9, "k")
    assert wide.gfwhm > narrow.gfwhm


def test_gauss_from_width_reports_an_unmeasurable_line():
    wave = np.linspace(5450.0, 5550.0, 1001)
    flux = np.ones_like(wave)          # no line at all
    fit = gauss_from_width(wave, flux, 5500.0, 1.0, "c")
    assert np.isnan(fit.gfwhm)
