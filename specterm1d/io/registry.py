"""Loader registry.

Loaders are tried in priority order; the first whose ``sniff`` returns True
wins. A failure to load reports which loaders declined and why, because a bare
traceback from deep inside astropy tells the user nothing about their file.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from specterm1d.spec import SpecCollection


class LoaderError(Exception):
    """No loader could handle the file, or the chosen one failed."""


@dataclass
class Loader:
    name: str
    sniff: Callable[[Path], bool]
    load: Callable[[Path], SpecCollection]
    priority: int = 50


_LOADERS: list[Loader] = []


def register(loader: Loader) -> None:
    _LOADERS.append(loader)
    _LOADERS.sort(key=lambda ld: ld.priority)


def loaders() -> list[Loader]:
    return list(_LOADERS)


def clear_registry() -> None:
    """Only for tests."""
    _LOADERS.clear()


def load(path: str | Path, format: str | None = None) -> SpecCollection:
    p = Path(path)
    if not p.exists():
        raise LoaderError(f"no such file: {p}")

    if format is not None:
        for loader in _LOADERS:
            if loader.name == format:
                return _run(loader, p)
        names = ", ".join(ld.name for ld in _LOADERS) or "(none registered)"
        raise LoaderError(f"no loader named {format!r}; available: {names}")

    declines: list[tuple[str, str]] = []
    for loader in _LOADERS:
        try:
            recognised = loader.sniff(p)
        except Exception as exc:
            declines.append((loader.name, f"sniff failed: {exc}"))
            continue
        if not recognised:
            declines.append((loader.name, "did not recognise the file"))
            continue
        return _run(loader, p)

    detail = "\n".join(f"  {name}: {reason}" for name, reason in declines)
    raise LoaderError(f"could not load {p}\n{detail}" if detail
                      else f"could not load {p}: no loaders registered")


def _run(loader: Loader, path: Path) -> SpecCollection:
    try:
        coll = loader.load(path)
    except Exception as exc:
        raise LoaderError(f"{loader.name} failed to load {path}: {exc}") from exc
    coll.path = str(path)
    coll.format = loader.name
    return coll
