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
