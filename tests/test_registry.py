# tests/test_registry.py
from pathlib import Path

import pytest

from specterm1d.io import registry
from specterm1d.spec import SpecCollection, SpecEntry, build_spec


@pytest.fixture(autouse=True)
def clean_registry():
    saved = registry.loaders()
    registry.clear_registry()
    yield
    registry.clear_registry()
    for loader in saved:
        registry.register(loader)


def _collection(label):
    return SpecCollection(
        entries=[SpecEntry(label, {"a": build_spec([1.0, 2.0], [1.0, 1.0])}, "a")]
    )


def test_load_uses_first_loader_that_sniffs_true(tmp_path):
    target = tmp_path / "f.fits"
    target.write_bytes(b"x")
    registry.register(registry.Loader("no", lambda p: False,
                                      lambda p: _collection("no"), priority=10))
    registry.register(registry.Loader("yes", lambda p: True,
                                      lambda p: _collection("yes"), priority=20))
    coll = registry.load(target)
    assert coll[0].label == "yes"


def test_load_records_path_and_format(tmp_path):
    target = tmp_path / "f.fits"
    target.write_bytes(b"x")
    registry.register(registry.Loader("yes", lambda p: True,
                                      lambda p: _collection("yes")))
    coll = registry.load(target)
    assert coll.path == str(target)
    assert coll.format == "yes"


def test_loaders_are_ordered_by_priority(tmp_path):
    registry.register(registry.Loader("late", lambda p: True,
                                      lambda p: _collection("late"), priority=90))
    registry.register(registry.Loader("early", lambda p: True,
                                      lambda p: _collection("early"), priority=1))
    assert [ld.name for ld in registry.loaders()] == ["early", "late"]


def test_load_reports_every_decline(tmp_path):
    target = tmp_path / "f.fits"
    target.write_bytes(b"x")
    registry.register(registry.Loader("alpha", lambda p: False,
                                      lambda p: _collection("a")))
    registry.register(registry.Loader("beta", lambda p: False,
                                      lambda p: _collection("b")))
    with pytest.raises(registry.LoaderError) as excinfo:
        registry.load(target)
    message = str(excinfo.value)
    assert "alpha" in message and "beta" in message


def test_sniff_exception_becomes_a_decline_not_a_crash(tmp_path):
    target = tmp_path / "f.fits"
    target.write_bytes(b"x")

    def boom(path):
        raise OSError("truncated header")

    registry.register(registry.Loader("bad", boom, lambda p: _collection("b")))
    with pytest.raises(registry.LoaderError) as excinfo:
        registry.load(target)
    assert "truncated header" in str(excinfo.value)


def test_explicit_format_bypasses_sniffing(tmp_path):
    target = tmp_path / "f.fits"
    target.write_bytes(b"x")
    registry.register(registry.Loader("picky", lambda p: False,
                                      lambda p: _collection("picky")))
    coll = registry.load(target, format="picky")
    assert coll[0].label == "picky"


def test_unknown_format_name_is_reported(tmp_path):
    target = tmp_path / "f.fits"
    target.write_bytes(b"x")
    registry.register(registry.Loader("real", lambda p: True,
                                      lambda p: _collection("real")))
    with pytest.raises(registry.LoaderError, match="nosuch"):
        registry.load(target, format="nosuch")


def test_missing_file_is_reported(tmp_path):
    with pytest.raises(registry.LoaderError, match="no such file"):
        registry.load(tmp_path / "absent.fits")
