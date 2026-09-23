"""Measurement commands."""
from __future__ import annotations

import math

import numpy as np

from specterm1d.fitting import (
    fit_profile,
    gauss_from_width,
    region_stats,
    sumflux,
)
from specterm1d.keymap import command


@command("measure.eqw")
def equivalent_width(session):
    """'e': equivalent width by direct summation between two cursor points."""
    def done(sess, positions):
        (x1, y1), (x2, y2) = positions
        if np.isclose(x1, x2):
            sess.message("cannot get EQW - move the cursor")
            return

        # display_spec, not current_spec: the cursor is in display
        # coordinates, so :units / $ / v must move the measurement with it.
        spec = sess.view.display_spec()
        result = sumflux(spec.wave, spec.flux, spec.sigma, x1, y1, x2, y2)

        sess.view.markers.extend([x1, x2])
        sess.log.record("e", center=result.center, cont=result.cont,
                        flux=result.flux, eqw=result.eqw)

        sess.message("  ".join([
            f"cen={format_measure(result.center, result.center_err, 7)}",
            f"eqw={format_measure(result.eqw, result.eqw_err, 6)}",
            f"cont={format_measure(result.cont, sig=7)}",
            f"flux={format_measure(result.flux, result.flux_err, 6)}",
        ]))

    session.await_cursor(2, "mark two continuum points around the line", done)


@command("measure.stats")
def stats(session):
    """'m': mean, RMS and S/N over a region marked with two x positions."""
    def done(sess, positions):
        x1 = positions[0][0]
        x2 = positions[1][0]
        spec = sess.view.display_spec()
        result = region_stats(spec.wave, spec.flux, spec.good, spec.sigma,
                              x1, x2)
        if result.npix == 0:
            sess.message("no good pixels in that region")
            return

        sess.view.markers.extend([x1, x2])
        sess.log.record("m", avg=result.mean, rms=result.rms, snr=result.snr)

        detail = (f"avg: {result.mean:10.4g}  rms: {result.rms:10.4g}"
                  f"   snr: {result.snr:8.2f}  ({result.npix} pixels)")
        if np.isfinite(result.propagated_snr):
            detail += f"  propagated snr: {result.propagated_snr:.2f}"
        sess.message(detail)

    session.await_cursor(2, "mark the region for statistics", done)


_PROFILE_KINDS = {"g": "gaussian", "l": "lorentzian", "v": "voigt"}
_WIDTH_MODES = {
    "a": "continuum at centre, LEFT half width at half flux",
    "b": "continuum at centre, RIGHT half width at half flux",
    "c": "continuum at centre, FULL width at half flux",
    "l": "flux level at centre, LEFT width",
    "r": "flux level at centre, RIGHT width",
    "k": "flux level at centre, FULL width",
}


def _report_fit(session, fit, kind_label: str) -> None:
    session.view.fits.append((fit.model_x, fit.model_y))
    session.log.record("k", center=fit.center, cont=fit.cont, flux=fit.flux,
                       eqw=fit.eqw, peak=fit.peak, gfwhm=fit.gfwhm,
                       lfwhm=fit.lfwhm)
    # The numbers still go out - they are usually about right, and refusing
    # to show them helps nobody - but a fit sitting on its limits is not a
    # measurement, and saying so beats a plausible-looking width in the log.
    # The numbers still go out - they are usually about right, and refusing
    # to show them helps nobody - but a fit sitting on its limits is not a
    # measurement, and saying so beats a plausible-looking width in the log.
    # First, so it is the part that survives when the line runs out of room.
    warning = (f" [{fit.at_bound} hit the marked range - check the continuum "
               "marks]") if fit.at_bound else ""
    fields = [
        f"{kind_label}{warning}: "
        f"cen={format_measure(fit.center, fit.center_err, 7)}",
        f"eqw={format_measure(fit.eqw, fit.eqw_err, 4)}",
        f"flux={format_measure(fit.flux, fit.flux_err, 6)}",
        f"ampl={format_measure(fit.peak, fit.peak_err, 6)}",
    ]
    # A width the profile does not have (lfwhm for a gaussian) is always
    # zero, and saying so costs a dozen columns of a line that is short of them.
    for name in ("gfwhm", "lfwhm"):
        value, err = getattr(fit, name), getattr(fit, f"{name}_err")
        if value != 0 or np.isfinite(err):
            fields.append(f"{name}={format_measure(value, err, 4)}")
    if np.isfinite(fit.chisq):
        chisq = (f"{fit.chisq:.2f}" if fit.chisq < 100
                 else _compact_exponent(f"{fit.chisq:.3g}"))
        fields.append(f"chi2_r={chisq}")
    session.message("  ".join(fields))


def format_measure(value: float, err: float = float("nan"), sig: int = 6) -> str:
    """``value ± err``, the value quoted only as far as its error supports.

    The error keeps two significant figures and the value is rounded to the
    same decimal place, but never to more than ``sig`` figures - the precision
    the log keeps. Without an error it is just ``sig`` significant figures.
    """
    if not math.isfinite(value):
        return f"{value}"
    if not (math.isfinite(err) and err > 0):
        return _compact_exponent(f"{value:.{sig}g}")
    place = math.floor(math.log10(err)) - 1      # last digit of a two-figure error
    return f"{_to_place(value, place, sig)} ± {_to_place(err, place, 2)}"


def _to_place(x: float, place: int, sig: int) -> str:
    """``x`` rounded to the 10**place digit, and to at most ``sig`` figures."""
    if x == 0:
        return f"{0.0:.{max(0, -place)}f}"
    place = max(place, math.floor(math.log10(abs(x))) - sig + 1)
    x = round(x, -place)
    if x == 0:
        return f"{0.0:.{max(0, -place)}f}"
    mag = math.floor(math.log10(abs(x)))         # after rounding: 9.99 -> 10.0
    if -4 <= mag < 5:
        return f"{x:.{max(0, -place)}f}"
    return _compact_exponent(f"{x:.{max(0, mag - place)}e}")


def _compact_exponent(text: str) -> str:
    """``1.83e+07`` as ``1.83e7``: four characters a field, on a full line."""
    mantissa, marker, exponent = text.partition("e")
    return f"{mantissa}e{int(exponent)}" if marker else text


@command("measure.profile")
def profile(session):
    """'k' + g|l|v: fit a single line profile between two continuum points."""
    def chosen(sess, char):
        # splot.hlp: "Any other second key defaults to gaussian."
        kind = char if char in _PROFILE_KINDS else "g"

        def done(inner, positions):
            (x1, y1), (x2, y2) = positions
            if np.isclose(x1, x2):
                inner.message("cannot fit - move the cursor")
                return
            spec = inner.view.display_spec()
            fit = fit_profile(spec.wave, spec.flux, spec.sigma,
                              x1, y1, x2, y2, kind, good=spec.good)
            inner.view.markers.extend([x1, x2])
            _report_fit(inner, fit, _PROFILE_KINDS[kind])

        sess.await_cursor(2, f"mark two continuum points ({_PROFILE_KINDS[kind]})",
                          done)

    session.await_key("profile", chosen, _PROFILE_KINDS)


@command("measure.gauss_width")
def gauss_width(session):
    """'h' + a|b|c|l|r|k: equivalent width from a measured width."""
    def chosen(sess, char):
        if char not in _WIDTH_MODES:
            sess.message(f"h: {char!r} is not a width mode")
            return

        def done(inner, positions):
            x0, y0 = positions[0]
            spec = inner.view.display_spec()
            fit = gauss_from_width(spec.wave, spec.flux, x0, y0, char,
                                   sigma=spec.sigma)
            if not np.isfinite(fit.gfwhm):
                inner.message("could not measure a width at that level")
                return
            inner.view.markers.append(x0)
            _report_fit(inner, fit, f"h/{char}")

        sess.await_cursor(1, _WIDTH_MODES[char], done)

    session.await_key("width mode", chosen, _WIDTH_MODES)
