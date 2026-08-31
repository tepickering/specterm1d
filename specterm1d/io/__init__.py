"""Importing this package registers the built-in loaders."""
from specterm1d.io import (
    pypeit_io,
    registry,
    specutils_io,
)

__all__ = ["registry"]
