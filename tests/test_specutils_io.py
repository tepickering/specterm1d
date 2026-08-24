# tests/test_specutils_io.py
import numpy as np
import pytest

from specterm1d.io import registry
import specterm1d.io  # noqa: F401  - triggers built-in loader registration


def test_specutils_loader_is_registered():
    assert "specutils" in [ld.name for ld in registry.loaders()]


def test_loads_tabular_fits(tabular_fits):
    coll = registry.load(tabular_fits)
    assert coll.format == "specutils"
    assert len(coll) == 1
    spec = coll[0].spec()
    assert spec.npix == 500
    assert np.isclose(spec.wave[0], 4000.0)
    assert np.isclose(spec.wave[-1], 9000.0)


def test_inverts_the_specutils_mask_convention(tabular_fits):
    # specutils stores True == bad; Spec.good must be True == good.
    spec = registry.load(tabular_fits)[0].spec()
    assert spec.good[10:20].sum() == 0
    assert spec.good[:10].all()
    assert spec.good[20:].all()


def test_converts_inverse_variance_to_sigma(tabular_fits):
    spec = registry.load(tabular_fits)[0].spec()
    assert np.allclose(spec.sigma, 0.5)


def test_records_units_and_provenance(tabular_fits):
    spec = registry.load(tabular_fits)[0].spec()
    assert spec.wave_unit.to_string() == "Angstrom"
    assert spec.flux_unit is not None
    assert spec.meta.path == str(tabular_fits)
    assert spec.meta.label == tabular_fits.stem


def test_declines_a_non_spectrum_file(tmp_path):
    junk = tmp_path / "junk.fits"
    junk.write_bytes(b"not a fits file at all")
    with pytest.raises(registry.LoaderError):
        registry.load(junk)
