"""pypeit OneSpec and spec1d loaders.

pypeit is an optional dependency, so nothing here imports it at module scope.
Sniffing reads FITS headers with astropy alone, which means a machine without
pypeit still gets a clear "install specterm1d[pypeit]" message rather than an
ImportError during startup.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

from specterm1d.io.registry import Loader, register
from specterm1d.spec import SpecCollection, SpecEntry, SpecMeta, build_spec

_ORDER_SUFFIX = re.compile(r"-ORDER\d+$")

# pypeit's fluxed spectra are in these units throughout.
_FLAM_UNIT = "1e-17 erg / (s cm2 Angstrom)"


def pypeit_available() -> bool:
    try:
        import pypeit  # noqa: F401
    except Exception:
        return False
    return True


def _require_pypeit() -> None:
    if not pypeit_available():
        raise ImportError(
            "this file needs pypeit; install it with: pip install 'specterm1d[pypeit]'"
        )


def _dmodcls(path: Path, index: int | None = None) -> set[str]:
    """Collect DMODCLS values from a FITS file using astropy only."""
    from astropy.io import fits

    try:
        with fits.open(path, memmap=False) as hdul:
            hdus = hdul[1:] if index is None else [hdul[index]]
            return {h.header.get("DMODCLS") for h in hdus}
    except Exception:
        return set()


def sniff_onespec(path: Path) -> bool:
    return "OneSpec" in _dmodcls(path, index=1)


def sniff_spec1d(path: Path) -> bool:
    return "SpecObj" in _dmodcls(path)


def load_onespec(path: Path) -> SpecCollection:
    _require_pypeit()
    from pypeit.onespec import OneSpec

    # chk_version=False deliberately: a datamodel version bump must not stop
    # the viewer opening yesterday's file.
    obj = OneSpec.from_file(str(path), chk_version=False)

    overlays = {}
    for name in ("telluric", "obj_model"):
        arr = getattr(obj, name, None)
        if arr is not None:
            overlays[name] = arr

    fluxed = bool(getattr(obj, "fluxed", False))
    extraction = getattr(obj, "ext_mode", None) or "OPT"
    calibration = "FLAM" if fluxed else "COUNTS"
    label = path.stem

    meta = SpecMeta(
        label=label,
        path=str(path),
        header=dict(getattr(obj, "head0", {}) or {}),
        pyp_spec=getattr(obj, "PYP_SPEC", None),
        extraction=extraction,
        calibration=calibration,
    )

    import astropy.units as u

    spec = build_spec(
        obj.wave,
        obj.flux,
        sigma=getattr(obj, "sigma", None),
        ivar=getattr(obj, "ivar", None),
        mask=getattr(obj, "mask", None),
        mask_convention="good",          # OneSpec.mask is integer, 1 == good
        wave_unit=u.AA,
        flux_unit=u.Unit(_FLAM_UNIT) if fluxed else None,
        overlays=overlays,
        meta=meta,
    )
    key = f"{extraction}/{calibration}"
    return SpecCollection(entries=[SpecEntry(label, {key: spec}, key)])


def _variant(sobj, extraction: str, calibration: str, path: Path, label: str):
    """Build one Spec for an (extraction, calibration) pair, or None."""
    import astropy.units as u

    wave = getattr(sobj, f"{extraction}_WAVE", None)
    field = f"{extraction}_{calibration}"
    flux = getattr(sobj, field, None)
    if wave is None or flux is None:
        return None

    overlays = {}
    sky = getattr(sobj, f"{extraction}_COUNTS_SKY", None)
    if sky is not None:
        overlays["sky"] = sky

    order = getattr(sobj, "ECH_ORDER", None)
    meta = SpecMeta(
        label=label,
        path=str(path),
        pyp_spec=getattr(sobj, "PYPELINE", None),
        ech_order=None if order is None else int(order),
        extraction=extraction,
        calibration=calibration,
    )

    return build_spec(
        wave,
        flux,
        sigma=getattr(sobj, f"{field}_SIG", None),
        ivar=getattr(sobj, f"{field}_IVAR", None),
        mask=getattr(sobj, f"{extraction}_MASK", None),
        mask_convention="good",          # SpecObj masks are bool, True == good
        wave_unit=u.AA,
        flux_unit=u.Unit(_FLAM_UNIT) if calibration == "FLAM" else None,
        overlays=overlays,
        meta=meta,
    )


_VARIANT_PREFERENCE = ("OPT/FLAM", "OPT/COUNTS", "BOX/FLAM", "BOX/COUNTS")


def load_spec1d(path: Path) -> SpecCollection:
    _require_pypeit()
    from pypeit.specobjs import SpecObjs

    sobjs = SpecObjs.from_fitsfile(str(path), chk_version=False)

    entries: list[SpecEntry] = []
    for sobj in sobjs:
        label = str(getattr(sobj, "NAME", "") or f"OBJ{len(entries):04d}")
        variants = {}
        for extraction in ("OPT", "BOX"):
            for calibration in ("COUNTS", "FLAM"):
                spec = _variant(sobj, extraction, calibration, path, label)
                if spec is not None:
                    variants[f"{extraction}/{calibration}"] = spec
        if not variants:
            continue
        default = next(k for k in _VARIANT_PREFERENCE if k in variants)
        entries.append(SpecEntry(label=label, variants=variants, default=default))

    if not entries:
        raise ValueError(f"no extracted spectra found in {path}")

    groups: dict[str, list[int]] | None = None
    if any(e.spec().meta.ech_order is not None for e in entries):
        groups = {}
        for i, entry in enumerate(entries):
            base = _ORDER_SUFFIX.sub("", entry.label)
            groups.setdefault(base, []).append(i)

    return SpecCollection(entries=entries, groups=groups)


register(Loader("pypeit-onespec", sniff_onespec, load_onespec, priority=10))
register(Loader("pypeit-spec1d", sniff_spec1d, load_spec1d, priority=20))
