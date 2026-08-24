"""Importing this package registers every command handler."""
from specterm1d.commands import colon  # noqa: F401
from specterm1d.commands import display  # noqa: F401

__all__ = ["colon", "display"]
