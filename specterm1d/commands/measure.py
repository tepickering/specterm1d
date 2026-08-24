"""Measurement commands."""
from __future__ import annotations

import numpy as np

from specterm1d.fitting import region_stats, sumflux
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
