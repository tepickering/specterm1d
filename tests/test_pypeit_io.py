# tests/test_pypeit_io.py
import numpy as np
import pytest

from specterm1d.io import registry
import specterm1d.io  # noqa: F401


def test_pypeit_loaders_are_registered():
    names = [ld.name for ld in registry.loaders()]
    assert "pypeit-onespec" in names
    assert "pypeit-spec1d" in names


def test_pypeit_loaders_outrank_specutils():
    order = [ld.name for ld in registry.loaders()]
    assert order.index("pypeit-onespec") < order.index("specutils")
    assert order.index("pypeit-spec1d") < order.index("specutils")


def test_sniff_does_not_import_pypeit(monkeypatch, tmp_path):
    # sniff must work on a machine without pypeit installed.
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name.startswith("pypeit"):
            raise ImportError("pypeit is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    junk = tmp_path / "junk.fits"
    junk.write_bytes(b"nope")
    from specterm1d.io import pypeit_io

    assert pypeit_io.sniff_onespec(junk) is False
    assert pypeit_io.sniff_spec1d(junk) is False


def test_loads_synthetic_spec1d(synthetic_spec1d):
    coll = registry.load(synthetic_spec1d)
    assert coll.format == "pypeit-spec1d"
    assert len(coll) == 2


def test_builds_opt_and_box_variants(synthetic_spec1d):
    entry = registry.load(synthetic_spec1d)[0]
    assert "OPT/COUNTS" in entry.variant_keys()
    assert "BOX/COUNTS" in entry.variant_keys()
    assert entry.default == "OPT/COUNTS"
    assert entry.spec("OPT/COUNTS").flux[100] == 10.0
    assert entry.spec("BOX/COUNTS").flux[100] == 20.0


def test_zero_wavelengths_are_masked(synthetic_spec1d):
    # Reproduces real UVES OPT_WAVE zero padding. The fixture zeroes five
    # pixels at each end, but build_spec sorts by wavelength, so all ten
    # land together at the front.
    spec = registry.load(synthetic_spec1d)[0].spec()
    assert (spec.wave[:10] == 0.0).all()
    assert spec.good[:10].sum() == 0
    assert spec.good[10:].all()


def test_preserves_pypeit_true_means_good_mask(synthetic_spec1d):
    spec = registry.load(synthetic_spec1d)[0].spec()
    # OPT_MASK was all True (good); only the zero-wavelength pixels drop out.
    assert spec.good.sum() == spec.npix - 10


def test_sky_is_attached_as_an_overlay(synthetic_spec1d):
    spec = registry.load(synthetic_spec1d)[0].spec("OPT/COUNTS")
    assert "sky" in spec.overlays
    assert np.allclose(spec.overlays["sky"], 3.0)


def test_converts_ivar_to_sigma(synthetic_spec1d):
    spec = registry.load(synthetic_spec1d)[0].spec()
    assert np.allclose(spec.sigma, 0.5)


def test_labels_come_from_specobj_name(synthetic_spec1d):
    labels = [e.label for e in registry.load(synthetic_spec1d).entries]
    assert all(label.startswith("SPAT") for label in labels)
    assert len(set(labels)) == 2


@pytest.mark.devsuite
def test_real_uves_echelle(devsuite_echelle):
    coll = registry.load(devsuite_echelle)
    assert len(coll) == 44
    orders = {e.spec().meta.ech_order for e in coll.entries}
    assert min(orders) == 64 and max(orders) == 108
    # Real OPT_WAVE is zero-padded; the invariant must hold anyway.
    for entry in coll.entries:
        spec = entry.spec()
        assert np.all(np.diff(spec.wave) >= 0)
        assert np.all(spec.wave[spec.good] > 0)


@pytest.mark.devsuite
def test_pypeit_already_masks_zero_wavelengths(devsuite_echelle):
    """Guards the assumption that require_positive is only a backstop here.

    If pypeit ever stops flagging its zero-padded pixels, this fails and the
    backstop becomes load-bearing - worth knowing about explicitly.
    """
    from pypeit.specobjs import SpecObjs

    sobjs = SpecObjs.from_fitsfile(str(devsuite_echelle), chk_version=False)
    zero_and_good = 0
    zero_total = 0
    for sobj in sobjs:
        wave, mask = sobj.OPT_WAVE, sobj.OPT_MASK
        if wave is None or mask is None:
            continue
        zero = wave <= 0
        zero_total += int(zero.sum())
        zero_and_good += int((zero & mask).sum())
    assert zero_total > 0, "fixture no longer exercises zero-padded wavelengths"
    assert zero_and_good == 0


@pytest.mark.devsuite
def test_real_uves_groups_orders_by_object(devsuite_echelle):
    coll = registry.load(devsuite_echelle)
    assert coll.groups is not None
    assert sum(len(v) for v in coll.groups.values()) == len(coll)
