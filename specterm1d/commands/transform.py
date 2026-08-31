"""Transforms that modify the spectrum, and the undo stack behind them."""
from __future__ import annotations

import astropy.units as u
import numpy as np

from specterm1d.keymap import command
from specterm1d.spec import build_spec


def boxcar(flux: np.ndarray, good: np.ndarray, box: int,
           sigma: np.ndarray | None = None):
    """Boxcar smooth, normalizing by the count of good pixels per window.

    A plain convolution smears masked values into their neighbours; dividing
    by the good-pixel count in each window keeps bad pixels out of the result
    entirely.
    """
    box = int(box)
    if box <= 0:
        raise ValueError("box size must be positive")

    kernel = np.ones(box, dtype=float)
    weights = good.astype(float)
    numerator = np.convolve(np.where(good, flux, 0.0), kernel, mode="same")
    denominator = np.convolve(weights, kernel, mode="same")

    out = flux.astype(float, copy=True)
    np.divide(numerator, denominator, out=out, where=denominator > 0)

    out_sigma = None
    if sigma is not None:
        effective = np.maximum(denominator, 1.0)
        out_sigma = sigma / np.sqrt(effective)
    return out, out_sigma


def _replace(session, *, flux=None, sigma=None, flux_unit=..., label=""):
    spec = session.view.current_spec()
    new = build_spec(
        spec.wave,
        spec.flux if flux is None else flux,
        sigma=spec.sigma if sigma is None else sigma,
        mask=spec.good,
        mask_convention="good",
        wave_unit=spec.wave_unit,
        flux_unit=spec.flux_unit if flux_unit is ... else flux_unit,
        overlays=spec.overlays,
        meta=spec.meta,
        require_positive=False,
    )
    session.view.push_transform(new, label)


@command("transform.smooth")
def smooth(session):
    def submitted(sess, text):
        if text is None:
            sess.message("cancelled")
            return
        try:
            box = int(text.strip())
        except ValueError:
            sess.message(f"box size must be an integer, got {text!r}")
            return
        if box <= 0:
            sess.message("box size must be positive")
            return
        spec = sess.view.current_spec()
        flux, sigma = boxcar(spec.flux, spec.good, box, spec.sigma)
        _replace(sess, flux=flux, sigma=sigma, label=f"boxcar {box}")
        sess.message(f"smoothed with a boxcar of {box} pixels")

    session.await_line("box size: ", submitted)


def _convert(session, target_kind: str):
    spec = session.view.current_spec()
    if spec.flux_unit is None:
        session.message("spectrum is not flux calibrated; conversion needs units")
        return

    wavelength = spec.wave * spec.wave_unit
    target = (u.erg / (u.s * u.cm ** 2 * u.Hz)) if target_kind == "fnu" \
        else (u.erg / (u.s * u.cm ** 2 * u.AA))
    try:
        converted = (spec.flux * spec.flux_unit).to(
            target, equivalencies=u.spectral_density(wavelength)
        )
    except u.UnitConversionError as exc:
        session.message(f"cannot convert: {exc}")
        return

    sigma = None
    if spec.sigma is not None:
        with np.errstate(invalid="ignore"):
            sigma = (spec.sigma * spec.flux_unit).to(
                target, equivalencies=u.spectral_density(wavelength)
            ).value

    _replace(session, flux=converted.value, sigma=sigma, flux_unit=target,
             label=f"convert to {target_kind}")
    session.view.rescale_y()
    session.message(f"converted to {target.to_string()}")


@command("transform.fnu")
def to_fnu(session):
    _convert(session, "fnu")


@command("transform.flambda")
def to_flambda(session):
    _convert(session, "flambda")


@command("transform.subtract_fit")
def subtract_fit(session):
    """'-': subtract the profile fitted by k or h, over a marked region."""
    if not session.view.fits:
        session.message("no fitted profile to subtract; use k or h first")
        return

    def done(sess, positions):
        xs = [x for x, _ in positions]
        lo, hi = min(xs), max(xs)
        spec = sess.view.current_spec()
        model_x, model_y = sess.view.fits[-1]

        # The marks and the fitted model live in display coordinates; the
        # stored spectrum is always in wavelength. Map both back, and re-sort
        # because units such as GHz reverse the axis.
        axis = sess.view.axis
        lo_w, hi_w = sorted(axis.to_wave(spec, np.array([lo, hi])))
        model_w = axis.to_wave(spec, model_x)
        order = np.argsort(model_w)

        inside = (spec.wave >= lo_w) & (spec.wave <= hi_w)
        model = np.interp(spec.wave, model_w[order], model_y[order],
                          left=0.0, right=0.0)
        flux = spec.flux.copy()
        flux[inside] -= model[inside]
        _replace(sess, flux=flux, label="subtract fit")
        sess.message(f"subtracted the fit over {lo:.6g} - {hi:.6g}")

    session.await_cursor(2, "mark the region to subtract over", done)


@command("transform.undo")
def undo(session):
    label = session.view.undo()
    if label is None:
        session.message("nothing to undo")
        return
    session.view.rescale_y()
    session.message(f"undid: {label}")
