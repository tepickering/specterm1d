# docs/conf.py
"""Sphinx configuration.

Most prose is single-sourced from ../README.md through MyST ``{include}``
directives, so pages here are thin wrappers that own their headings.
"""
from importlib.metadata import version as _version

project = "specterm1d"
author = "T. E. Pickering"
copyright = "2026, T. E. Pickering"
release = _version("specterm1d")

extensions = ["myst_parser"]

# colon_fence lets a directive be written with ::: instead of ```, which keeps
# nested fences readable inside included Markdown.
myst_enable_extensions = ["colon_fence", "deflist"]

exclude_patterns = ["_build"]

html_theme = "furo"
html_title = "specterm1d"
