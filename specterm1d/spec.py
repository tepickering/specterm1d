"""Core spectrum data model.

Everything above the loader boundary speaks these types. The loaders in
``specterm1d.io`` are the only code that knows about FITS.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import astropy.units as u
import numpy as np


@dataclass
class SpecMeta:
    """Provenance and identity for a single spectrum."""

    label: str = ""
    path: str | None = None
    header: dict = field(default_factory=dict)
    pyp_spec: str | None = None
    ech_order: int | None = None
    extraction: str | None = None    # 'OPT' | 'BOX' | None
    calibration: str | None = None   # 'COUNTS' | 'FLAM' | None


@dataclass
class Spec:
    """One 1D spectrum with optional companion arrays.

    ``mask`` is True where the pixel is GOOD. This is the opposite of the
    numpy/specutils convention and is normalized in :func:`build_spec`.
    """

    wave: np.ndarray
    flux: np.ndarray
    sigma: np.ndarray | None = None
    mask: np.ndarray | None = None
    wave_unit: u.UnitBase = u.AA
    flux_unit: u.UnitBase | None = None
    overlays: dict[str, np.ndarray] = field(default_factory=dict)
    meta: SpecMeta = field(default_factory=SpecMeta)

    @property
    def npix(self) -> int:
        return int(self.wave.size)

    @property
    def good(self) -> np.ndarray:
        if self.mask is None:
            return np.ones(self.npix, dtype=bool)
        return self.mask


def ivar_to_sigma(ivar) -> np.ndarray:
    """Convert an inverse-variance array to one-sigma errors.

    Pixels with non-positive inverse variance carry no information, so they
    become ``inf`` rather than raising or producing a divide warning.
    """
    ivar = np.asarray(ivar, dtype=float)
    sigma = np.full(ivar.shape, np.inf, dtype=float)
    ok = ivar > 0
    sigma[ok] = 1.0 / np.sqrt(ivar[ok])
    return sigma


def build_spec(
    wave,
    flux,
    *,
    sigma=None,
    ivar=None,
    mask=None,
    mask_convention: str = "good",
    wave_unit: u.UnitBase = u.AA,
    flux_unit: u.UnitBase | None = None,
    overlays: dict | None = None,
    meta: SpecMeta | None = None,
    require_positive: bool = True,
) -> Spec:
    """The single constructor every loader uses.

    Normalizes the two conventions that differ between our input formats:
    inverse variance becomes sigma, and the mask becomes True-means-good.

    Also enforces the wavelength invariant: strictly ascending, with
    non-positive and non-finite wavelengths forced masked. pypeit already
    flags its zero-padded ``OPT_WAVE`` pixels as bad, so for those files this
    is a no-op that simply confirms the mask; it does real work only for
    sources that carry no mask, where it creates the coverage instead.

    Args:
        mask_convention: ``"good"`` if True means good (pypeit),
            ``"bad"`` if True means bad (numpy, specutils).
        require_positive: enforce ``wave > 0``. True for loading real
            wavelengths; False when the "wavelength" axis is a display
            transform such as velocity or pixel index, where zero and
            negative values are legitimate.
    """
    wave = np.asarray(wave, dtype=float).ravel()
    flux = np.asarray(flux, dtype=float).ravel()
    if wave.size != flux.size:
        raise ValueError(
            f"wave and flux length mismatch: {wave.size} != {flux.size}"
        )

    if sigma is None and ivar is not None:
        sigma = ivar_to_sigma(ivar)
    if sigma is not None:
        sigma = np.asarray(sigma, dtype=float).ravel()
        if sigma.size != wave.size:
            raise ValueError(
                f"sigma length mismatch: {sigma.size} != {wave.size}"
            )

    if mask is None:
        good = np.ones(wave.size, dtype=bool)
    else:
        m = np.asarray(mask)
        if mask_convention == "good":
            good = m.astype(bool)
        elif mask_convention == "bad":
            good = ~m.astype(bool)
        else:
            raise ValueError(f"unknown mask_convention {mask_convention!r}")
        good = good.ravel().copy()
        if good.size != wave.size:
            raise ValueError(
                f"mask length mismatch: {good.size} != {wave.size}"
            )

    with np.errstate(invalid="ignore"):
        good &= np.isfinite(wave) & np.isfinite(flux)
        if require_positive:
            good &= wave > 0

    ov = {}
    for key, arr in (overlays or {}).items():
        arr = np.asarray(arr, dtype=float).ravel()
        if arr.size != wave.size:
            raise ValueError(
                f"overlay {key!r} length mismatch: {arr.size} != {wave.size}"
            )
        ov[key] = arr

    order = np.argsort(wave, kind="stable")
    if not np.array_equal(order, np.arange(wave.size)):
        wave = wave[order]
        flux = flux[order]
        good = good[order]
        if sigma is not None:
            sigma = sigma[order]
        ov = {k: v[order] for k, v in ov.items()}

    return Spec(
        wave=wave,
        flux=flux,
        sigma=sigma,
        mask=good,
        wave_unit=wave_unit,
        flux_unit=flux_unit,
        overlays=ov,
        meta=meta if meta is not None else SpecMeta(),
    )


@dataclass
class SpecEntry:
    """One navigable item: an object, or an echelle order.

    ``variants`` holds alternate extractions of the same item, keyed
    ``"<extraction>/<calibration>"`` - e.g. ``"OPT/COUNTS"``, ``"BOX/FLAM"``.
    These are separate ``Spec`` objects because ``BOX_WAVE`` and ``OPT_WAVE``
    are genuinely different arrays, not two views of one.
    """

    label: str
    variants: dict[str, Spec]
    default: str

    def spec(self, key: str | None = None) -> Spec:
        return self.variants[key if key is not None else self.default]

    def variant_keys(self) -> list[str]:
        return list(self.variants)


@dataclass
class SpecCollection:
    """Everything one file yielded."""

    entries: list[SpecEntry] = field(default_factory=list)
    path: str | None = None
    format: str | None = None
    groups: dict[str, list[int]] | None = None
    """Echelle only: object name -> indices of its orders in ``entries``."""

    def __len__(self) -> int:
        return len(self.entries)

    def __getitem__(self, i: int) -> SpecEntry:
        return self.entries[i]

    def find(self, key: str | int) -> int:
        """Resolve an index or a label to an index. Raises KeyError."""
        if isinstance(key, int):
            if not 0 <= key < len(self.entries):
                raise KeyError(f"index {key} out of range (0..{len(self.entries) - 1})")
            return key
        for i, entry in enumerate(self.entries):
            if entry.label == key:
                return i
        raise KeyError(f"no entry labelled {key!r}")
