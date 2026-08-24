# tests/conftest.py
import astropy.units as u
import numpy as np
import pytest
from astropy.nddata import InverseVariance


@pytest.fixture
def tabular_fits(tmp_path):
    """A tabular-fits file with known flux, ivar and mask.

    Mask uses the specutils/numpy convention: True == BAD. Pixels 10..19 are
    flagged, so a correct loader reports exactly those as not-good.
    """
    from specutils import Spectrum

    wave = np.linspace(4000.0, 9000.0, 500) * u.AA
    flux = np.linspace(1.0, 2.0, 500) * u.Unit("1e-17 erg / (s cm2 AA)")
    ivar = InverseVariance(np.full(500, 4.0))
    mask = np.zeros(500, dtype=bool)
    mask[10:20] = True

    spec = Spectrum(flux=flux, spectral_axis=wave, uncertainty=ivar, mask=mask)
    path = tmp_path / "tabular.fits"
    spec.write(path, format="tabular-fits", overwrite=True)
    return path
