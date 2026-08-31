# tests/test_spec.py
import numpy as np
import pytest

from specterm1d.spec import (
    Spec,
    SpecCollection,
    SpecEntry,
    build_spec,
    ivar_to_sigma,
)


def test_ivar_to_sigma_inverts_positive_values():
    sigma = ivar_to_sigma(np.array([4.0, 0.25, 1.0]))
    assert np.allclose(sigma, [0.5, 2.0, 1.0])


def test_ivar_to_sigma_marks_nonpositive_as_infinite():
    sigma = ivar_to_sigma(np.array([0.0, -1.0, 4.0]))
    assert np.isinf(sigma[0]) and np.isinf(sigma[1])
    assert sigma[2] == 0.5


def test_build_spec_treats_good_convention_as_true_means_good():
    # pypeit convention: True/1 == good
    mask = np.array([True, True, False, True])
    spec = build_spec([1.0, 2, 3, 4], [1.0, 1, 1, 1], mask=mask, mask_convention="good")
    assert spec.good.tolist() == [True, True, False, True]


def test_build_spec_inverts_bad_convention():
    # specutils/numpy convention: True == bad
    mask = np.array([False, False, True, False])
    spec = build_spec([1.0, 2, 3, 4], [1.0, 1, 1, 1], mask=mask, mask_convention="bad")
    assert spec.good.tolist() == [True, True, False, True]


def test_build_spec_creates_mask_coverage_for_nonpositive_wavelengths():
    # A source with no mask at all: build_spec has to create the coverage.
    spec = build_spec([0.0, 0.0, 5000.0, 5001.0], [1.0, 1, 2, 3])
    assert spec.good.tolist() == [False, False, True, True]


def test_build_spec_agrees_with_an_existing_mask_over_zero_wavelengths():
    # The pypeit case: the file already flags them, so this is a no-op.
    spec = build_spec([0.0, 0.0, 5000.0, 5001.0], [1.0, 1, 2, 3],
                      mask=[False, False, True, True], mask_convention="good")
    assert spec.good.tolist() == [False, False, True, True]


def test_build_spec_keeps_nonpositive_wave_when_not_required():
    # Velocity and pixel-index axes legitimately go to zero and negative.
    spec = build_spec([-100.0, 0.0, 100.0], [1.0, 2, 3], require_positive=False)
    assert spec.good.tolist() == [True, True, True]


def test_build_spec_masks_nonfinite_flux():
    spec = build_spec([1.0, 2, 3], [1.0, np.nan, np.inf])
    assert spec.good.tolist() == [True, False, False]


def test_build_spec_derives_sigma_from_ivar():
    spec = build_spec([1.0, 2], [1.0, 1], ivar=np.array([4.0, 0.0]))
    assert spec.sigma[0] == 0.5
    assert np.isinf(spec.sigma[1])


def test_build_spec_prefers_explicit_sigma_over_ivar():
    spec = build_spec([1.0, 2], [1.0, 1], sigma=np.array([9.0, 9.0]),
                      ivar=np.array([4.0, 4.0]))
    assert spec.sigma.tolist() == [9.0, 9.0]


def test_build_spec_sorts_every_array_together():
    spec = build_spec(
        [3.0, 1.0, 2.0], [30.0, 10.0, 20.0],
        sigma=np.array([3.0, 1.0, 2.0]),
        mask=np.array([True, False, True]),
        overlays={"sky": np.array([300.0, 100.0, 200.0])},
    )
    assert spec.wave.tolist() == [1.0, 2.0, 3.0]
    assert spec.flux.tolist() == [10.0, 20.0, 30.0]
    assert spec.sigma.tolist() == [1.0, 2.0, 3.0]
    assert spec.good.tolist() == [False, True, True]
    assert spec.overlays["sky"].tolist() == [100.0, 200.0, 300.0]


def test_build_spec_rejects_length_mismatch():
    with pytest.raises(ValueError, match="length"):
        build_spec([1.0, 2, 3], [1.0, 2])


def test_spec_good_defaults_to_all_true():
    spec = Spec(wave=np.array([1.0, 2]), flux=np.array([1.0, 1]))
    assert spec.good.tolist() == [True, True]
    assert spec.npix == 2


def test_spec_entry_returns_default_variant():
    a = build_spec([1.0, 2], [1.0, 1])
    b = build_spec([1.0, 2], [2.0, 2])
    entry = SpecEntry(label="obj", variants={"OPT/COUNTS": a, "BOX/COUNTS": b},
                      default="OPT/COUNTS")
    assert entry.spec() is a
    assert entry.spec("BOX/COUNTS") is b
    assert entry.variant_keys() == ["OPT/COUNTS", "BOX/COUNTS"]


def test_collection_groups_default_to_none():
    coll = SpecCollection(entries=[])
    assert coll.groups is None


def test_collection_find_accepts_index_and_label():
    e0 = SpecEntry("ORDER0064", {"a": build_spec([1.0], [1.0])}, "a")
    e1 = SpecEntry("ORDER0065", {"a": build_spec([1.0], [1.0])}, "a")
    coll = SpecCollection(entries=[e0, e1])
    assert len(coll) == 2
    assert coll.find(1) == 1
    assert coll.find("ORDER0065") == 1
    with pytest.raises(KeyError):
        coll.find("nope")
