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
