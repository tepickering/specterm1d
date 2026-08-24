"""Importing this package registers the built-in loaders."""
from specterm1d.io import registry  # noqa: F401
from specterm1d.io import pypeit_io  # noqa: F401
from specterm1d.io import specutils_io  # noqa: F401

__all__ = ["registry"]
