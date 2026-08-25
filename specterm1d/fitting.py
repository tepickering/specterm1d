"""Measurement maths.

``sumflux`` is a direct transcription of IRAF's noao/onedspec/splot/sumflux.x
so that measurements agree with splot's. Three details matter and are easy to
get wrong by guessing: the continuum comes from the cursor ramp (eqy1/eqy2),
the centroid is weighted by ``|y - ramp| ** 1.5``, and the sums are scaled by
one mean dispersion ``wpc`` after summing rather than integrated pixel by
pixel.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.special import wofz


@dataclass
class SumFluxResult:
    center: float
    cont: float
    flux: float
    eqw: float
    center_err: float = float("nan")
    flux_err: float = float("nan")
    eqw_err: float = float("nan")


@dataclass
class RegionStats:
    mean: float
    rms: float
    snr: float
    npix: int
    propagated_snr: float = float("nan")


def sumflux(wave, flux, sigma, x1: float, y1: float, x2: float,
            y2: float) -> SumFluxResult:
    """Equivalent width, flux and centroid over a cursor-marked region."""
    wave = np.asarray(wave, dtype=float)
    flux = np.asarray(flux, dtype=float)

    if x2 < x1:
        x1, x2 = x2, x1
        y1, y2 = y2, y1

    n = wave.size
    i1 = int(np.clip(np.searchsorted(wave, x1), 0, n - 1))
    i2 = int(np.clip(np.searchsorted(wave, x2), 0, n - 1))
    if i1 == i2:
        return SumFluxResult(float("nan"), 0.5 * (y1 + y2), 0.0, 0.0)

    slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
    scale = max(abs(y1), abs(y2), 1.0)

    interior = slice(i1 + 1, i2)
    xs = wave[interior]
    ys = flux[interior]
    ramp = y1 + slope * (xs - x1)

    total = ys.sum()
    ramp_total = ramp.sum()

    if np.any(np.isclose(ramp / scale, 0.0)):
        eqw_sum = float("nan")
    else:
        eqw_sum = float((1.0 - ys / ramp).sum())

    # Centroid weighting: sumflux.x uses the 1.5 power of the residual.
    delta = np.abs(ys - ramp) / scale
    csum = float((delta ** 1.5 * xs).sum())
    wsum = float((delta ** 1.5).sum())

    # Fractional end-point weights, verbatim from sumflux.x.
    w1 = _end_weight(wave, i1, x1, n)
    w2 = 1.0 - _end_weight(wave, i2, x2, n)

    total += w1 * flux[i1] + w2 * flux[i2]
    ramp_total += w1 * y1 + w2 * y2
    if not np.isnan(eqw_sum):
        if np.isclose(y1 / scale, 0.0) or np.isclose(y2 / scale, 0.0):
            eqw_sum = float("nan")
        else:
            eqw_sum += w1 * (1.0 - flux[i1] / y1) + w2 * (1.0 - flux[i2] / y2)

    d1 = abs(flux[i1] - y1) / scale
    d2 = abs(flux[i2] - y2) / scale
    csum += w1 * d1 ** 1.5 * x1 + w2 * d2 ** 1.5 * x2
    wsum += w1 * d1 ** 1.5 + w2 * d2 ** 1.5

    center = csum / wsum if wsum != 0.0 else float("nan")

    # One mean dispersion for the whole region, applied after summing.
    if i1 != i2:
        wpc = abs((wave[i2] - wave[i1]) / (i2 - i1))
    elif i1 < n - 1:
        wpc = abs(wave[i1 + 1] - wave[i1])
    else:
        wpc = abs(wave[i1 - 1] - wave[i1])

    total *= wpc
    ramp_total *= wpc
    eqw = eqw_sum * wpc if not np.isnan(eqw_sum) else float("nan")

    flux_err = eqw_err = float("nan")
    if sigma is not None:
        s = np.asarray(sigma, dtype=float)[interior]
        finite = np.isfinite(s)
        flux_err = float(np.sqrt((s[finite] ** 2).sum()) * wpc)
        if not np.isnan(eqw_sum):
            with np.errstate(divide="ignore", invalid="ignore"):
                terms = (s / ramp) ** 2
            eqw_err = float(np.sqrt(np.nansum(terms[finite])) * wpc)

    return SumFluxResult(
        center=center,
        cont=0.5 * (y1 + y2),
        flux=float(total - ramp_total),
        eqw=eqw,
        flux_err=flux_err,
        eqw_err=eqw_err,
    )


def _end_weight(wave, i: int, x: float, n: int) -> float:
    if x < wave[i]:
        denominator = (wave[i] - wave[i - 1]) if i > 0 else (wave[i + 1] - wave[i])
    else:
        denominator = (wave[i + 1] - wave[i]) if i < n - 1 else (wave[i] - wave[i - 1])
    if denominator == 0:
        return 0.0
    return float((wave[i] - x) / denominator)


def region_stats(wave, flux, good, sigma, x1: float, x2: float) -> RegionStats:
    """Mean, RMS and signal-to-noise over a marked region."""
    wave = np.asarray(wave, dtype=float)
    flux = np.asarray(flux, dtype=float)
    lo, hi = (x1, x2) if x1 <= x2 else (x2, x1)

    sel = np.asarray(good, dtype=bool) & (wave >= lo) & (wave <= hi)
    sel &= np.isfinite(flux)
    values = flux[sel]

    if values.size == 0:
        return RegionStats(float("nan"), float("nan"), float("nan"), 0)

    mean = float(values.mean())
    rms = float(values.std(ddof=0))
    snr = float(mean / rms) if rms > 0 else float("inf")

    propagated = float("nan")
    if sigma is not None:
        s = np.asarray(sigma, dtype=float)[sel]
        s = s[np.isfinite(s)]
        if s.size:
            propagated = float(mean / np.sqrt((s ** 2).mean()))

    return RegionStats(mean=mean, rms=rms, snr=snr, npix=int(values.size),
                       propagated_snr=propagated)


FWHM_PER_SIGMA = 2.0 * np.sqrt(2.0 * np.log(2.0))


@dataclass
class ProfileFit:
    center: float
    cont: float
    peak: float
    flux: float
    eqw: float
    gfwhm: float
    lfwhm: float
    model_x: np.ndarray
    model_y: np.ndarray
    rms: float = float("nan")


def gaussian(x, center, amplitude, sigma):
    x = np.asarray(x, dtype=float)
    sigma = max(float(sigma), 1e-12)
    return amplitude * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def lorentzian(x, center, amplitude, gamma):
    """gamma is the half width at half maximum."""
    x = np.asarray(x, dtype=float)
    gamma = max(float(gamma), 1e-12)
    return amplitude * gamma ** 2 / ((x - center) ** 2 + gamma ** 2)


def voigt(x, center, amplitude, sigma, gamma):
    """Normalized to peak ``amplitude`` at ``center``."""
    x = np.asarray(x, dtype=float)
    sigma = max(float(sigma), 1e-12)
    gamma = max(float(gamma), 1e-12)
    z = ((x - center) + 1j * gamma) / (sigma * np.sqrt(2.0))
    profile = np.real(wofz(z))
    peak = np.real(wofz(1j * gamma / (sigma * np.sqrt(2.0))))
    return amplitude * profile / peak


def _ramp(x, x1, y1, x2, y2):
    slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
    return y1 + slope * (np.asarray(x, dtype=float) - x1)


def fit_profile(wave, flux, sigma, x1: float, y1: float, x2: float, y2: float,
                kind: str = "g") -> ProfileFit:
    """Fit one line profile over a linear continuum between two cursor points."""
    wave = np.asarray(wave, dtype=float)
    flux = np.asarray(flux, dtype=float)
    if x2 < x1:
        x1, x2 = x2, x1
        y1, y2 = y2, y1

    inside = (wave >= x1) & (wave <= x2) & np.isfinite(flux)
    xs, ys = wave[inside], flux[inside]
    if xs.size < 4:
        nan = float("nan")
        return ProfileFit(nan, 0.5 * (y1 + y2), nan, nan, nan, nan, nan,
                          np.array([]), np.array([]))

    continuum = _ramp(xs, x1, y1, x2, y2)
    residual = ys - continuum

    weights = np.ones_like(xs)
    if sigma is not None:
        s = np.asarray(sigma, dtype=float)[inside]
        ok = np.isfinite(s) & (s > 0)
        weights = np.where(ok, 1.0 / np.where(ok, s, 1.0), 0.0)
        if not np.any(weights > 0):
            weights = np.ones_like(xs)

    # Weight the initial guess as well as the fit. Seeding on the largest raw
    # residual lets a pixel the sigma array says is worthless capture the
    # solver, and no amount of weighting afterwards recovers from that.
    extreme = int(np.argmax(np.abs(residual) * weights))
    guess_center = float(xs[extreme])
    guess_amp = float(residual[extreme])
    guess_width = max((x2 - x1) / 10.0, np.abs(np.diff(xs)).mean() * 2)

    if kind == "l":
        def model(p, x):
            return lorentzian(x, p[0], p[1], p[2])
        p0 = [guess_center, guess_amp, guess_width / 2.0]
    elif kind == "v":
        def model(p, x):
            return voigt(x, p[0], p[1], p[2], p[3])
        p0 = [guess_center, guess_amp, guess_width / FWHM_PER_SIGMA,
              guess_width / 2.0]
    else:                                  # any other key defaults to gaussian
        kind = "g"

        def model(p, x):
            return gaussian(x, p[0], p[1], p[2])
        p0 = [guess_center, guess_amp, guess_width / FWHM_PER_SIGMA]

    try:
        solution = least_squares(
            lambda p: (model(p, xs) - residual) * weights, p0, method="lm",
            max_nfev=2000,
        )
        params = solution.x
        rms = float(np.sqrt(np.mean((model(params, xs) - residual) ** 2)))
    except Exception:
        params = np.array(p0, dtype=float)
        rms = float("nan")

    center = float(params[0])
    amplitude = float(params[1])

    if kind == "g":
        gfwhm = float(abs(params[2]) * FWHM_PER_SIGMA)
        lfwhm = 0.0
        area = amplitude * abs(params[2]) * np.sqrt(2.0 * np.pi)
    elif kind == "l":
        gfwhm = 0.0
        lfwhm = float(abs(params[2]) * 2.0)
        area = amplitude * abs(params[2]) * np.pi
    else:
        gfwhm = float(abs(params[2]) * FWHM_PER_SIGMA)
        lfwhm = float(abs(params[3]) * 2.0)
        area = float(np.trapezoid(model(params, xs), xs))

    cont_at_center = float(_ramp(np.array([center]), x1, y1, x2, y2)[0])
    eqw = -area / cont_at_center if cont_at_center != 0 else float("nan")

    model_x = np.linspace(x1, x2, min(max(xs.size, 64), 2000))
    model_y = model(params, model_x) + _ramp(model_x, x1, y1, x2, y2)

    return ProfileFit(center=center, cont=cont_at_center, peak=amplitude,
                      flux=float(area), eqw=float(eqw), gfwhm=gfwhm,
                      lfwhm=lfwhm, model_x=model_x, model_y=model_y, rms=rms)


def _crossings(xs, ys, level: float, center: float):
    """Where the curve crosses ``level``, immediately left and right of centre."""
    left = right = float("nan")
    idx = int(np.argmin(np.abs(xs - center)))

    for i in range(idx, 0, -1):
        if (ys[i] - level) * (ys[i - 1] - level) <= 0:
            span = ys[i] - ys[i - 1]
            frac = 0.0 if span == 0 else (level - ys[i - 1]) / span
            left = float(xs[i - 1] + frac * (xs[i] - xs[i - 1]))
            break

    for i in range(idx, xs.size - 1):
        if (ys[i] - level) * (ys[i + 1] - level) <= 0:
            span = ys[i + 1] - ys[i]
            frac = 0.0 if span == 0 else (level - ys[i]) / span
            right = float(xs[i] + frac * (xs[i + 1] - xs[i]))
            break

    return left, right


def gauss_from_width(wave, flux, x0: float, y0: float,
                     mode: str = "c") -> ProfileFit:
    """'h': build the Gaussian implied by a measured width.

    Modes a/b/c take the continuum from the cursor's y and measure at half
    the line depth; modes l/r/k take a flux level relative to a normalized
    continuum of 1 and measure at that level.
    """
    wave = np.asarray(wave, dtype=float)
    flux = np.asarray(flux, dtype=float)

    half_modes = {"a": "left", "b": "right", "c": "full"}
    level_modes = {"l": "left", "r": "right", "k": "full"}
    nan = float("nan")

    idx = int(np.clip(np.searchsorted(wave, x0), 0, wave.size - 1))

    if mode in half_modes:
        cont = float(y0)
        peak = float(flux[idx] - cont)
        level = cont + peak / 2.0
        side = half_modes[mode]
    elif mode in level_modes:
        cont = 1.0
        peak = float(flux[idx] - cont)
        level = float(y0)
        side = level_modes[mode]
    else:
        return ProfileFit(nan, nan, nan, nan, nan, nan, nan,
                          np.array([]), np.array([]))

    left, right = _crossings(wave, flux, level, x0)

    if side == "left":
        width = 2.0 * (x0 - left) if np.isfinite(left) else nan
    elif side == "right":
        width = 2.0 * (right - x0) if np.isfinite(right) else nan
    else:
        width = (right - left) if np.isfinite(left) and np.isfinite(right) else nan

    if not np.isfinite(width) or width <= 0 or peak == 0:
        return ProfileFit(float(x0), cont, peak, nan, nan, nan, 0.0,
                          np.array([]), np.array([]))

    sigma_w = width / FWHM_PER_SIGMA
    area = peak * sigma_w * np.sqrt(2.0 * np.pi)
    eqw = -area / cont if cont != 0 else nan

    model_x = np.linspace(x0 - 3 * width, x0 + 3 * width, 400)
    model_y = gaussian(model_x, x0, peak, sigma_w) + cont

    return ProfileFit(center=float(x0), cont=cont, peak=peak, flux=float(area),
                      eqw=float(eqw), gfwhm=float(width), lfwhm=0.0,
                      model_x=model_x, model_y=model_y)
