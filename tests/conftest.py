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

@pytest.fixture
def synthetic_spec1d(tmp_path):
    """A two-object spec1d written by pypeit itself.

    Object 0 gets zero-padded wavelengths at both ends, reproducing what real
    UVES echelle extractions look like. The mask is deliberately left all-True
    there, which is the *harder* case: it exercises build_spec creating the
    coverage rather than merely agreeing with a mask that already has it.
    """
    pypeit = pytest.importorskip("pypeit")
    from pypeit.specobj import SpecObj
    from pypeit.specobjs import SpecObjs

    npix = 200
    sobjs = SpecObjs()
    for i in range(2):
        sobj = SpecObj("MultiSlit", "DET01", SLITID=100 + i)
        wave = np.linspace(5000.0, 6000.0, npix)
        if i == 0:
            wave[:5] = 0.0
            wave[-5:] = 0.0
        sobj.OPT_WAVE = wave
        sobj.OPT_COUNTS = np.full(npix, 10.0 + i)
        sobj.OPT_COUNTS_IVAR = np.full(npix, 4.0)
        sobj.OPT_MASK = np.ones(npix, dtype=bool)
        sobj.OPT_COUNTS_SKY = np.full(npix, 3.0)
        sobj.BOX_WAVE = wave.copy()
        sobj.BOX_COUNTS = np.full(npix, 20.0 + i)
        sobj.BOX_MASK = np.ones(npix, dtype=bool)
        sobj.SPAT_PIXPOS = 100.0 + i
        sobj.set_name()
        sobjs.add_sobj(sobj)

    path = tmp_path / "spec1d_synthetic.fits"
    sobjs.write_to_fits({"PYP_SPEC": "shane_kast_blue", "DISPNAME": "600/4310"},
                        str(path), overwrite=True)
    return path


@pytest.fixture
def devsuite_echelle():
    """A real UVES echelle spec1d, if the development suite is on disk."""
    from pathlib import Path

    path = Path(
        "/Users/tim/MMT/PypeIt-development-suite/REDUX_OUT/REDUX_OUT/vlt_uves_red/"
        "760/Science/spec1d_UVES.2009-04-20T01:35:52.269-SDSS-J0935+0924_"
        "VLT_UVES_red_20090420T013552.269.fits"
    )
    if not path.exists():
        pytest.skip("PypeIt-development-suite data not present")
    return path
