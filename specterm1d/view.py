"""View state: what part of which spectrum is on screen, and in what units.

Every axis concern lives here. ``display_spec()`` hands ``plot.py`` a Spec
whose wave array is already in display coordinates and sorted ascending, so
the plotting code never has to know about velocity, pixel indices, or
frequency units running backwards.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import astropy.units as u
import numpy as np

from specterm1d.plot import PlotRequest, autoscale
from specterm1d.spec import Spec, SpecCollection, SpecEntry, build_spec

C_KMS = 299792.458


@dataclass
class Axis:
    """Maps between wavelength and the displayed x coordinate."""

    mode: str = "wave"                    # 'wave' | 'pixel' | 'velocity'
    unit: u.UnitBase = u.AA
    velocity_origin: float | None = None  # Angstroms

    def to_display(self, spec: Spec, wave) -> np.ndarray:
        wave = np.asarray(wave, dtype=float)
        if self.mode == "pixel":
            return np.interp(wave, spec.wave, np.arange(spec.npix, dtype=float))
        if self.mode == "velocity":
            w0 = self.velocity_origin
            if not w0:
                return wave
            return C_KMS * (wave - w0) / w0
        quantity = wave * spec.wave_unit
        return quantity.to(self.unit, equivalencies=u.spectral()).value

    def to_wave(self, spec: Spec, x) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        if self.mode == "pixel":
            return np.interp(x, np.arange(spec.npix, dtype=float), spec.wave)
        if self.mode == "velocity":
            w0 = self.velocity_origin
            if not w0:
                return x
            return w0 * (1.0 + x / C_KMS)
        quantity = x * self.unit
        return quantity.to(spec.wave_unit, equivalencies=u.spectral()).value

    def label(self) -> str:
        if self.mode == "pixel":
            return "Pixel"
        if self.mode == "velocity":
            return "Velocity (km/s)"
        return f"Wavelength ({self.unit.to_string()})"


@dataclass
class ViewState:
    collection: SpecCollection
    index: int = 0
    variant: str | None = None
    xlim: tuple[float, float] | None = None
    ylim: tuple[float, float] | None = None
    axis: Axis = field(default_factory=Axis)

    show_sigma: bool = False
    show_mask: bool = False
    overlays: set[str] = field(default_factory=set)
    histogram: bool = False
    zero_base: bool = False
    flip: bool = False
    flip_y: bool = False
    window_reset: bool = True      # :wreset - re-autoscale on entry change
    overplot_next: bool = False

    cursor_x: float | None = None
    cursor_y: float | None = None
    markers: list[float] = field(default_factory=list)
    fits: list[tuple[np.ndarray, np.ndarray]] = field(default_factory=list)

    @property
    def entry(self) -> SpecEntry:
        return self.collection[self.index]

    def current_spec(self) -> Spec:
        """The underlying spectrum, in wavelength space."""
        entry = self.entry
        key = self.variant if self.variant in entry.variants else entry.default
        return entry.variants[key]

    def display_spec(self) -> Spec:
        """The spectrum re-expressed on the current display axis."""
        spec = self.current_spec()
        if self.axis.mode == "wave" and self.axis.unit == spec.wave_unit:
            return spec
        x = self.axis.to_display(spec, spec.wave)
        return build_spec(
            x, spec.flux,
            sigma=spec.sigma,
            mask=spec.good,
            mask_convention="good",
            wave_unit=self.axis.unit if self.axis.mode == "wave" else u.dimensionless_unscaled,
            flux_unit=spec.flux_unit,
            overlays=spec.overlays,
            meta=spec.meta,
            require_positive=False,   # velocity and pixel axes go non-positive
        )

    def reset_limits(self) -> None:
        spec = self.display_spec()
        good = spec.wave[spec.good]
        if good.size == 0:
            self.xlim = (0.0, 1.0)
            self.ylim = (0.0, 1.0)
            return
        self.xlim = (float(good.min()), float(good.max()))
        self.ylim = autoscale(spec, self.xlim, zero_base=self.zero_base)

    def rescale_y(self) -> None:
        spec = self.display_spec()
        self.ylim = autoscale(spec, self.xlim or (spec.wave.min(), spec.wave.max()),
                              zero_base=self.zero_base)

    def set_axis(self, mode: str | None = None, unit: u.UnitBase | None = None,
                 velocity_origin: float | None = None) -> None:
        """Change the axis, carrying the current window across the change."""
        spec = self.current_spec()
        old_wave_limits = None
        if self.xlim is not None:
            old_wave_limits = self.axis.to_wave(spec, np.array(self.xlim))

        if mode is not None:
            self.axis.mode = mode
        if unit is not None:
            self.axis.unit = unit
        if velocity_origin is not None:
            self.axis.velocity_origin = velocity_origin

        if old_wave_limits is not None:
            new = self.axis.to_display(spec, old_wave_limits)
            self.xlim = (float(min(new)), float(max(new)))

    def to_request(self, title: str = "") -> PlotRequest:
        spec = self.display_spec()
        if self.xlim is None or self.ylim is None:
            self.reset_limits()
        xlim = self.xlim
        if self.flip:
            xlim = (xlim[1], xlim[0])
        ylim = self.ylim
        if self.flip_y:
            ylim = (ylim[1], ylim[0])
        markers = tuple(self.markers)
        if self.cursor_x is not None:
            markers = markers + (self.cursor_x,)
        ylabel = "Flux"
        if spec.flux_unit is not None:
            ylabel = f"Flux ({spec.flux_unit.to_string()})"
        return PlotRequest(
            spec=spec,
            xlim=xlim,
            ylim=ylim,
            show_sigma=self.show_sigma,
            show_mask=self.show_mask,
            overlays=tuple(sorted(self.overlays)),
            histogram=self.histogram,
            title=title,
            xlabel=self.axis.label(),
            ylabel=ylabel,
            markers=markers,
            fits=tuple(self.fits),
        )
