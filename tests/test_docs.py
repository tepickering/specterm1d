# tests/test_docs.py
"""Guards on the docs tree.

Pages include slices of README.md anchored on heading text. A reworded
heading would otherwise yield a silently empty page, so the anchors are
checked here where the rename happens.
"""
import pathlib
import re

DOCS = pathlib.Path(__file__).resolve().parent.parent / "docs"
README = pathlib.Path(__file__).resolve().parent.parent / "README.md"

# Anchors are quoted in the pages because MyST parses directive options as
# YAML, where a bare ``## Install`` is a comment and reaches docutils as
# nothing at all. The quotes are syntax, not part of the heading, so they come
# off before the README is searched.
_ANCHOR = re.compile(r"^:(?:start-after|end-before):[ \t]*(.+?)[ \t]*$", re.M)


def _unquote(anchor):
    if len(anchor) >= 2 and anchor[0] == anchor[-1] and anchor[0] in "\"'":
        return anchor[1:-1]
    return anchor


def readme_include_anchors():
    """(page, anchor) for every include anchor under docs/."""
    found = []
    for page in sorted(DOCS.glob("*.md")):
        for anchor in _ANCHOR.findall(page.read_text()):
            found.append((page, _unquote(anchor)))
    return found


def test_the_anchor_scan_actually_finds_anchors():
    # Guards the guard: a regex that matches nothing would make the test
    # below pass no matter how badly the includes were broken.
    assert len(readme_include_anchors()) >= 12


def test_every_include_anchor_appears_in_the_readme_exactly_once():
    readme = README.read_text()
    wrong = {
        f"{page.name}: {anchor!r}": readme.count(anchor)
        for page, anchor in readme_include_anchors()
        if readme.count(anchor) != 1
    }
    assert wrong == {}
