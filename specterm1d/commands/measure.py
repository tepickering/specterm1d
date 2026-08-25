"""Measurement commands."""
from __future__ import annotations

import numpy as np

from specterm1d.fitting import (
    fit_profile, gauss_from_width, region_stats, sumflux,
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

        detail = (f"center = {result.center:9.7g}, eqw = {result.eqw:9.4f}, "
                  f"continuum = {result.cont:9.7g} flux = {result.flux:9.6g}")
        if np.isfinite(result.eqw_err):
            detail += f"  (+/- {result.eqw_err:.3g})"
        sess.message(detail)

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
    session.message(
        f"{kind_label}: center = {fit.center:9.7g}, eqw = {fit.eqw:9.4g}, "
        f"flux = {fit.flux:9.6g}, core = {fit.peak:9.6g}, "
        f"gfwhm = {fit.gfwhm:9.4g}, lfwhm = {fit.lfwhm:9.4g}"
    )


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
                              x1, y1, x2, y2, kind)
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
            fit = gauss_from_width(spec.wave, spec.flux, x0, y0, char)
            if not np.isfinite(fit.gfwhm):
                inner.message("could not measure a width at that level")
                return
            inner.view.markers.append(x0)
            _report_fit(inner, fit, f"h/{char}")

        sess.await_cursor(1, _WIDTH_MODES[char], done)

    session.await_key("width mode", chosen, _WIDTH_MODES)
