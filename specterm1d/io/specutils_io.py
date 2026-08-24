"""The generic specutils path.

specutils auto-identifies 29 formats, including IRAF multispec, tabular-fits,
wcs1d-fits, SDSS, HST/COS, HST/STIS, JWST and APOGEE. This loader is the
lowest-priority fallback: the pypeit loaders get first refusal on files they
recognise, because they carry more structure than specutils exposes.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from specterm1d.io.registry import Loader, register
from specterm1d.spec import SpecCollection, SpecEntry, SpecMeta, build_spec


def _identify(path: Path) -> str | None:
    from specutils.io.registers import identify_spectrum_format

    fmt = identify_spectrum_format(str(path))
    if isinstance(fmt, (list, tuple)):
        fmt = fmt[0] if fmt else None
    return fmt or None


def sniff(path: Path) -> bool:
    return _identify(path) is not None


def _rows(arr, axis: int, npix: int):
    """Reshape any companion array to (nrow, npix), or return None."""
    if arr is None:
        return None
    a = np.asarray(arr)
    if a.ndim == 1:
        return a.reshape(1, npix)
    return np.moveaxis(a, axis, -1).reshape(-1, npix)


def _specs_from_spectrum(sp, path: Path) -> list:
    from astropy.nddata import StdDevUncertainty

    wave = np.asarray(sp.spectral_axis.value, dtype=float)
    npix = wave.size
    axis = getattr(sp, "spectral_axis_index", np.asarray(sp.flux.value).ndim - 1)

    flux_rows = _rows(sp.flux.value, axis, npix)
    sigma_rows = None
    if sp.uncertainty is not None:
        sigma_rows = _rows(
            sp.uncertainty.represent_as(StdDevUncertainty).array, axis, npix
        )
    mask_rows = _rows(sp.mask, axis, npix)

    out = []
    for i in range(flux_rows.shape[0]):
        out.append(
            dict(
                wave=wave,
                flux=flux_rows[i],
                sigma=None if sigma_rows is None else sigma_rows[i],
                mask=None if mask_rows is None else mask_rows[i],
                mask_convention="bad",   # specutils follows numpy: True == bad
                wave_unit=sp.spectral_axis.unit,
                flux_unit=sp.flux.unit,
            )
        )
    return out


def load(path: Path) -> SpecCollection:
    from specutils import Spectrum, SpectrumList

    fmt = _identify(path)
    try:
        objects = [Spectrum.read(str(path), format=fmt)]
    except Exception:
        objects = list(SpectrumList.read(str(path), format=fmt))

    payloads = []
    for sp in objects:
        payloads.extend(_specs_from_spectrum(sp, path))

    stem = path.stem
    entries = []
    for i, payload in enumerate(payloads):
        label = stem if len(payloads) == 1 else f"{stem}[{i}]"
        meta = SpecMeta(label=label, path=str(path))
        spec = build_spec(**payload, meta=meta)
        entries.append(SpecEntry(label=label, variants={"SPEC": spec},
                                 default="SPEC"))

    if not entries:
        raise ValueError(f"specutils returned no spectra for {path}")
    return SpecCollection(entries=entries)


register(Loader(name="specutils", sniff=sniff, load=load, priority=50))
