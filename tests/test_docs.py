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


# The leak is the thing a user is most likely to hit and least likely to
# diagnose, so both the warning and its citations are pinned.
GOOD_CITATIONS = (
    "gnachman/iterm2/-/issues/10420",
    "gnachman/iterm2/-/issues/3943",
)
# Open, and about memory, but it blames tab count and its reporter says
# terminal activity barely matters - the opposite of what we measured. Easy
# to re-add in good faith, so it is pinned out.
WRONG_CITATION = "11261"


def test_the_terminals_page_warns_about_the_iterm2_leak():
    page = (DOCS / "terminals.md").read_text()
    assert "{warning}" in page
    assert "iTerm2" in page


def test_the_readme_cites_the_upstream_iterm2_reports():
    readme = README.read_text()
    missing = [url for url in GOOD_CITATIONS if url not in readme]
    assert missing == []


def test_the_wrong_iterm2_issue_is_not_cited():
    for path in (README, *sorted(DOCS.glob("*.md"))):
        assert WRONG_CITATION not in path.read_text(), path


# ---- packaging guards ----------------------------------------------
#
# README.md is the PyPI long description. What renders on GitHub does not
# necessarily render on PyPI, and a broken project page is only noticeable
# after the version number has been spent.

ROOT = pathlib.Path(__file__).resolve().parent.parent

# [text](target) where target is neither a URL, an anchor, nor a mail link.
_RELATIVE_LINK = re.compile(r"\[[^\]]*\]\((?!https?://|#|mailto:)([^)]+)\)")


def test_the_readme_has_no_repo_relative_links():
    """PyPI serves the README detached from the repository.

    A link like ``(docs/keys.md)`` resolves on GitHub and 404s on the
    project page, where nobody who could fix it is looking.
    """
    assert _RELATIVE_LINK.findall(README.read_text()) == []


def test_the_licence_text_ships_with_the_package():
    """pyproject declares BSD-3-Clause, which requires the notice be
    distributed. A declared licence with no text is a licence in name only."""
    licence = ROOT / "LICENSE"
    assert licence.is_file()
    assert "Redistribution and use in source and binary forms" in \
        licence.read_text()


def test_the_landing_page_introduces_the_project_from_the_readme():
    """The landing page is the first thing a reader sees, and the README
    already opens with the right words. Restating them by hand is how the
    two drift - which they had, down to a reworded first sentence."""
    assert "{include} ../README.md" in (DOCS / "index.md").read_text()
