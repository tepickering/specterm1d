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


# README.md is the PyPI long description as well as the source of most pages
# here, and PyPI serves it detached from the repository - so its screenshots
# have to be absolute URLs. Sphinx has the files sitting right there, though,
# and a docs build should not depend on a URL that only resolves once the
# branch carrying the images has been merged: a pull request preview would
# show broken images every time one was added. Point them back at the local
# copies as the README is read in.
IMAGE_URL_PREFIX = (
    "https://raw.githubusercontent.com/tepickering/specterm1d/main/docs/"
)


def _use_local_images(app, relative_path, parent_docname, content):
    content[0] = content[0].replace(IMAGE_URL_PREFIX, "")


def setup(app):
    app.connect("include-read", _use_local_images)
