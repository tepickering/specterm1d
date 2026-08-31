"""Importing this package registers every command handler."""
from specterm1d.commands import (
    colon,
    display,
    measure,
    transform,
)

__all__ = ["colon", "display", "measure", "transform"]
