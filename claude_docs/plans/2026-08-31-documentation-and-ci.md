# Documentation Site and CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a Sphinx documentation site on Read the Docs whose prose is
single-sourced from `README.md`, and add GitHub Actions CI covering code style,
the docs build, and the test suite on Python 3.14 and 3.13.

**Architecture:** Sphinx + MyST-Parser keeps every source file Markdown, so
`docs/keys.md` needs no conversion and the README can be sliced into pages with
`{include}` directives anchored on heading text. A page owns its own headings
and includes only section *bodies*, which keeps heading levels consecutive and
avoids MyST header warnings under `-W`. A pytest guard asserts every include
anchor still exists in the README exactly once, so a heading rename fails at
the moment it happens rather than as a silently empty page.

**Tech Stack:** Sphinx 9, myst-parser 5, furo, Read the Docs, GitHub Actions,
pytest, ruff.

**Spec:** `claude_docs/specs/2026-08-31-documentation-and-ci-design.md`

## Global Constraints

- `requires-python = ">=3.13"`. CI's default target is **3.14**; 3.13 is tested
  because the floor still allows it.
- Dependency floors sit near the development environment, not at the oldest
  workable release: `sphinx>=9.1`, `myst-parser>=5.1`, `furo>=2025.12.19`.
  Verified compatible — myst-parser 5.1 requires `sphinx>=8,<10`, furo
  2025.12.19 requires `sphinx>=7,<10`, and the dev environment has Sphinx 9.1.0
  on Python 3.14.6.
- Documentation source is Markdown only. No reStructuredText files.
- **`README.md` stays plain Markdown with no MyST directives.** GitHub is the
  primary reader until there is a PyPI release, and a `{warning}` block renders
  there as a code block. Directives live in `docs/`, wrapping the includes.
- Every documentation build runs with `-W --keep-going`; Read the Docs sets
  `fail_on_warning: true`. A warning is a failure.
- Agent specs and plans live in `claude_docs/`, never in `docs/`. `docs/` holds
  published content only.
- ruff: `line-length = 100`, `target-version = "py313"`. Everything added here,
  `docs/conf.py` included, must pass `ruff check .`.

---

### Task 1: Sphinx scaffold that builds clean

**Files:**
- Create: `docs/conf.py`
- Create: `docs/index.md`
- Create: `.readthedocs.yaml`
- Modify: `pyproject.toml` (add the `docs` extra)
- Modify: `.gitignore` (ignore the build output)

**Interfaces:**
- Consumes: nothing.
- Produces: a `docs/` Sphinx project that builds warning-free with
  `sphinx-build -W --keep-going docs docs/_build/html`, and a toctree in
  `docs/index.md` that later tasks add pages to.

- [ ] **Step 1: Run the build to watch it fail**

```bash
sphinx-build -W --keep-going docs docs/_build/html
```

Expected: FAIL — `config directory doesn't contain a conf.py file`.

- [ ] **Step 2: Add the docs extra**

In `pyproject.toml`, under `[project.optional-dependencies]`, after the
`sixel` line:

```toml
docs = ["sphinx>=9.1", "myst-parser>=5.1", "furo>=2025.12.19"]
```

- [ ] **Step 3: Install it**

```bash
pip install -e '.[docs]'
```

- [ ] **Step 4: Write `docs/conf.py`**

```python
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
```

- [ ] **Step 5: Write `docs/index.md`**

`keys.md` already exists and has its own H1, so it goes in the toctree now;
every other page is added by Task 2.

````markdown
# specterm1d

A terminal-based viewer for 1D spectra, with IRAF `splot` keybindings and a
plot drawn in the terminal itself.

```{toctree}
:maxdepth: 2

keys
```
````

- [ ] **Step 6: Ignore the build output**

Append to `.gitignore`:

```
docs/_build/
```

- [ ] **Step 7: Run the build to verify it passes**

```bash
sphinx-build -W --keep-going docs docs/_build/html
```

Expected: PASS, `build succeeded`. If it reports `keys` not in any toctree,
the toctree entry in Step 5 is wrong — fix that rather than excluding the file.

- [ ] **Step 8: Write `.readthedocs.yaml`**

```yaml
version: 2

build:
  os: ubuntu-24.04
  tools:
    python: "3.14"

sphinx:
  configuration: docs/conf.py
  fail_on_warning: true

python:
  install:
    - method: pip
      path: .
      extra_requirements:
        - docs
```

If Read the Docs rejects `"3.14"` as an unsupported tool version, set it to
`"3.13"`. The documentation build is not version-sensitive, and CI's
`build_docs` job remains the authoritative check either way.

- [ ] **Step 9: Check lint and tests still pass**

```bash
ruff check . && python -m pytest -q
```

Expected: `All checks passed!` and 546 passed.

- [ ] **Step 10: Commit**

```bash
git add docs/conf.py docs/index.md .readthedocs.yaml pyproject.toml .gitignore
git commit -m "docs: add a Sphinx scaffold that builds on Read the Docs"
```

---

### Task 2: README single-sourcing and the anchor test

**Files:**
- Create: `tests/test_docs.py`
- Create: `docs/install.md`, `docs/quickstart.md`, `docs/terminals.md`,
  `docs/measuring.md`, `docs/batch.md`, `docs/differences.md`
- Modify: `docs/index.md` (extend the toctree)

**Interfaces:**
- Consumes: the Sphinx project from Task 1.
- Produces: `tests/test_docs.py` with
  `readme_include_anchors() -> list[tuple[pathlib.Path, str]]`, returning
  `(page_path, anchor_text)` for every `:start-after:` / `:end-before:` option
  found under `docs/`. Task 3 adds further tests to this same file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_docs.py`:

```python
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

_ANCHOR = re.compile(r"^:(?:start-after|end-before):[ \t]*(.+?)[ \t]*$", re.M)


def readme_include_anchors():
    """(page, anchor) for every include anchor under docs/."""
    found = []
    for page in sorted(DOCS.glob("*.md")):
        for anchor in _ANCHOR.findall(page.read_text()):
            found.append((page, anchor))
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
```

- [ ] **Step 2: Run it to verify it fails**

```bash
python -m pytest tests/test_docs.py -v
```

Expected: `test_the_anchor_scan_actually_finds_anchors` FAILS with
`assert 0 >= 12` — no pages include anything yet. The second test passes
vacuously; that is why the first one exists.

- [ ] **Step 3: Create the simple pages**

`docs/install.md`:

````markdown
# Install

```{include} ../README.md
:start-after: ## Install
:end-before: ## Quick start
```
````

`docs/quickstart.md`:

````markdown
# Quick start

```{include} ../README.md
:start-after: ## Quick start
:end-before: ## Terminal support
```
````

`docs/measuring.md`:

````markdown
# Measurement log

```{include} ../README.md
:start-after: ## Measurement log
:end-before: ## Batch use
```
````

`docs/batch.md`:

````markdown
# Batch use

```{include} ../README.md
:start-after: ## Batch use
:end-before: ## Licence
```
````

Anchors are written unquoted. docutils treats the option value as literal
text, so `'## Install'` would search for a string containing the quote
characters and match nothing.

- [ ] **Step 4: Create `docs/terminals.md`**

The page owns the subheadings and includes only section bodies. Including the
README's own `###` headings under this page's `#` would skip a level and MyST
would warn, which `-W` turns into a failure.

````markdown
# Terminals

```{include} ../README.md
:start-after: ## Terminal support
:end-before: ### Two-window mode
```

## Two-window mode

```{include} ../README.md
:start-after: ### Two-window mode
:end-before: ### Why iTerm2 gets a window
```

## Why iTerm2 gets a window

```{include} ../README.md
:start-after: ### Why iTerm2 gets a window
:end-before: ## Keys
```
````

- [ ] **Step 5: Create `docs/differences.md`**

````markdown
# Differences and gaps

## Not implemented yet

```{include} ../README.md
:start-after: ## Not implemented yet
:end-before: ## Differences from splot
```

## Differences from splot

```{include} ../README.md
:start-after: ## Differences from splot
:end-before: ## Measurement log
```
````

- [ ] **Step 6: Extend the toctree**

Replace the toctree body in `docs/index.md` with:

````markdown
```{toctree}
:maxdepth: 2

install
quickstart
terminals
keys
measuring
batch
differences
```
````

- [ ] **Step 7: Run the test to verify it passes**

```bash
python -m pytest tests/test_docs.py -v
```

Expected: both tests PASS.

- [ ] **Step 8: Build the docs and read the output**

```bash
sphinx-build -W --keep-going docs docs/_build/html
```

Expected: PASS. Then confirm the includes actually pulled content — an empty
page builds cleanly, so the build alone is not proof:

```bash
grep -c "OPT/COUNTS" docs/_build/html/differences.html
grep -c "1.7 MB" docs/_build/html/terminals.html
```

Expected: a non-zero count from each. If either is `0`, the anchors matched
but selected an empty range — check the `:start-after:` / `:end-before:`
ordering on that page.

- [ ] **Step 9: Run the full suite**

```bash
ruff check . && python -m pytest -q
```

Expected: `All checks passed!` and 548 passed.

- [ ] **Step 10: Commit**

```bash
git add docs tests/test_docs.py
git commit -m "docs: build the site from README sections rather than copies"
```

---

### Task 3: The iTerm2 warning and its citations

**Files:**
- Modify: `README.md` (the "Why iTerm2 gets a window" section — citations only)
- Modify: `docs/terminals.md` (add the admonition)
- Modify: `tests/test_docs.py` (add the citation guards)

**Interfaces:**
- Consumes: the `DOCS` and `README` path constants from Task 2's
  `tests/test_docs.py`; the new tests are appended to that same file.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_docs.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

```bash
python -m pytest tests/test_docs.py -v
```

Expected: `test_the_terminals_page_warns_about_the_iterm2_leak` FAILS on
`assert "{warning}" in page`, and
`test_the_readme_cites_the_upstream_iterm2_reports` FAILS with both URLs
missing. The third passes already and stays as a regression guard.

- [ ] **Step 3: Add the citations to the README**

In `README.md`, in the "Why iTerm2 gets a window" section, immediately after
the paragraph ending "`--renderer iterm2` still forces the inline path.", add:

```markdown
This is not specific to specterm1d. It has been reported upstream twice —
[#3943](https://gitlab.com/gnachman/iterm2/-/issues/3943) in 2015 and
[#10420](https://gitlab.com/gnachman/iterm2/-/issues/10420) in 2022, the
latter reaching about 20 GB and surviving a scrollback clear and a session
close — and closed both times. The behaviour is still present in 3.6.11, and
has driven a machine into the OOM killer at 138 GB. There is no open upstream
issue to wait on, so the window is where iTerm2 stays.
```

Plain Markdown, no directives: this renders on GitHub and flows into the site
through the existing include.

- [ ] **Step 4: Add the admonition to `docs/terminals.md`**

Immediately after the `# Terminals` heading, before the first include:

````markdown
```{warning}
On iTerm2, every distinct inline image costs about a decoded bitmap of
resident memory for the life of the session — roughly 1.7 MB per redraw on
3.6.11 — and nothing the application can send releases it. specterm1d
therefore routes iTerm2 to a matplotlib window automatically. `--renderer
iterm2` overrides that, at the cost described below.
```
````

- [ ] **Step 5: Run the tests to verify they pass**

```bash
python -m pytest tests/test_docs.py -v
```

Expected: all five tests PASS.

- [ ] **Step 6: Build and confirm the warning renders**

```bash
sphinx-build -W --keep-going docs docs/_build/html
grep -c "admonition warning" docs/_build/html/terminals.html
```

Expected: build PASSES and the count is non-zero.

- [ ] **Step 7: Run the full suite**

```bash
ruff check . && python -m pytest -q
```

Expected: `All checks passed!` and 551 passed.

- [ ] **Step 8: Commit**

```bash
git add README.md docs/terminals.md tests/test_docs.py
git commit -m "docs: cite the upstream iTerm2 reports and warn on the site"
```

---

### Task 4: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` (build badge)

**Interfaces:**
- Consumes: the `docs` extra from Task 1 and the `dev` extra already in
  `pyproject.toml`.
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Verify each matrix command locally first**

CI should not be the first place these run.

```bash
ruff check .
sphinx-build -W --keep-going docs docs/_build/html
MPLBACKEND=Agg python -m pytest -q
```

Expected: all three succeed. Fix anything that does not before writing the
workflow — a red first CI run is hard to tell apart from a broken workflow.

- [ ] **Step 2: Write `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  check:
    name: ${{ matrix.name }}
    runs-on: ubuntu-latest
    env:
      # matplotlib must never reach for a display in CI.
      MPLBACKEND: Agg
    strategy:
      fail-fast: false
      matrix:
        include:
          - name: codestyle
            python: "3.14"
            extras: dev
            command: ruff check .
          - name: build_docs
            python: "3.14"
            extras: docs
            command: sphinx-build -W --keep-going docs docs/_build/html
          - name: test (3.14)
            python: "3.14"
            extras: dev
            command: python -m pytest -q
          - name: test (3.13)
            python: "3.13"
            extras: dev
            command: python -m pytest -q
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python }}
          cache: pip
      - run: pip install -e '.[${{ matrix.extras }}]'
      - run: ${{ matrix.command }}
```

- [ ] **Step 3: Add the badge**

At the top of `README.md`, immediately below the `# specterm1d` heading:

```markdown
[![CI](https://github.com/tepickering/specterm1d/actions/workflows/ci.yml/badge.svg)](https://github.com/tepickering/specterm1d/actions/workflows/ci.yml)
```

- [ ] **Step 4: Confirm the badge did not break an include anchor**

```bash
python -m pytest tests/test_docs.py -q
```

Expected: PASS. The badge sits above `## Install`, outside every included
range, so no anchor moves.

- [ ] **Step 5: Commit and push**

```bash
git add .github/workflows/ci.yml README.md
git commit -m "ci: run codestyle, docs and tests on 3.14 and 3.13"
git push
```

- [ ] **Step 6: Watch the first run**

```bash
gh run watch
```

Expected: four green cells. If `test (3.13)` fails on a dependency that no
longer ships 3.13 wheels, the response is to raise `requires-python` to
`>=3.14` and drop that matrix entry — not to weaken the job. If `build_docs`
fails on a warning, fix the warning; `-W` is deliberate.
