# Documentation site and CI — design

Date: 2026-08-31
Status: approved for planning

## Goals

1. A Sphinx documentation site published on Read the Docs.
2. No prose duplicated between `README.md` and the site. A section lives in
   exactly one file.
3. The iTerm2 inline-image leak documented prominently, with upstream
   citations rather than only our own measurement.
4. GitHub Actions CI covering code style, the documentation build, and the
   test suite on Python 3.13 and 3.14.

## Non-goals

- **No API reference.** specterm1d is a CLI, not a library. The docstrings in
  `session.py` and `plot.py` are maintainer-facing, and `AGENTS.md` already
  describes module layout. Autodoc here would generate a large section with no
  audience. Revisit if the `io/` loaders ever become a public interface.
- **No tox.** Four one-line commands do not justify a second configuration
  file. The job names still follow the astropy convention so the matrix reads
  familiarly.
- **No change to renderer selection.** Whether `--renderer iterm2` and the
  no-GUI fallback should keep permitting the leaking inline path is a real
  question, but a behavioural one. It is tracked separately, not settled here.

## Toolchain

Sphinx with `myst-parser`, so every source file stays Markdown: `docs/keys.md`
moves into the tree unchanged and the README includes need no conversion.
Theme is `furo`. A new `docs` extra in `pyproject.toml` carries
`sphinx`, `myst-parser` and `furo`; `.readthedocs.yaml` pins Python 3.14 and
installs `.[docs]`.

Development records - the specs and plans formerly under
`docs/superpowers/` - move to `claude_docs/` as part of this work, so Sphinx
never sees them. They are working notes rather than site content, and leaving
them inside the source tree would need an `exclude_patterns` entry that a
later addition could silently outgrow; under `-W`, a file that is neither
excluded nor in a toctree fails the build. `conf.py` still excludes `_build`.

## Page structure

| Page | Content |
|---|---|
| `index.md` | Written for the site: what specterm1d is, the splot lineage, the toctree |
| `install.md` | Includes README "Install" |
| `quickstart.md` | Includes README "Quick start" |
| `terminals.md` | Includes README "Terminal support" through "Keys"; adds the iTerm2 admonition |
| `keys.md` | The existing file, moved in unchanged |
| `measuring.md` | Includes README "Measurement log" |
| `batch.md` | Includes README "Batch use" |
| `differences.md` | Includes README "Differences from splot" and "Not implemented yet" |

## Single-sourcing, and its two sharp edges

Pages pull README content with MyST `{include}` using `:start-after:` and
`:end-before:` anchored on literal heading text.

**Anchor drift.** Rewording a README heading silently yields an empty or
over-long page. Two guards: a test asserting every anchor string still exists
in `README.md`, which fails at the moment of the rename; and `-W` on the CI
docs build, since a bad include warns rather than errors.

**Admonitions.** A `{warning}` directive in `README.md` renders as a code
block on GitHub, which is where most readers will be until there is a PyPI
release. So the README stays plain Markdown and `terminals.md` wraps its
include with a docs-only admonition. Directives belong to the site; the README
stays portable.

## iTerm2

The leak is the one thing in these docs a user is most likely to hit and least
likely to diagnose, so it gets a warning admonition on `terminals.md` above the
included prose, plus upstream citations the README currently lacks:

- [#10420 "Memory leak when using inline image feature"](https://gitlab.com/gnachman/iterm2/-/issues/10420)
  — filed 2022-05-24 against 3.5.0beta5. Roughly 20 GB retained after a few
  hundred inline images, not released by clearing the scrollback or closing
  the session. **Closed 2022-06-29.**
- [#3943 "imgcat | divider | etc... Releasing memory after displaying inline images"](https://gitlab.com/gnachman/iterm2/-/issues/3943)
  — filed and closed in October 2015 against 2.9.20151001. Clearing the buffer
  does not free inline-image memory.

Both are closed, and neither appears to have been fixed: we measure the same
behaviour on 3.6.11 in 2026 at 1.7 MB per frame, and it has driven this
project's author into the OOM killer at 138 GB resident - the same order as
#10420's report, and from ordinary use rather than a stress test. The documentation therefore
says the leak has been reported upstream twice and closed both times, and is
still reproducible — not that a fix is pending. There is no open issue to wait
on, so nothing should promise the demotion is temporary.

Filing a fresh upstream report with the per-frame measurement would be a real
contribution, and is a follow-up rather than part of this work.

Deliberately **not** cited: [#11261 "High CPU and Memory Usage"](https://gitlab.com/gnachman/iterm2/-/work_items/11261).
It is open and it concerns memory, but it attributes growth to the number of
tabs, and its reporter states that what they do in the terminal has little
impact — close to the opposite of our finding, which is driven entirely by
what the application draws. Recorded here so it is not re-added later in good
faith.

## CI

`.github/workflows/ci.yml`, one job, an `include:` matrix, `fail-fast: false`
so a single red cell does not mask the others. Python 3.14 is the default
target; 3.13 is tested because `requires-python` still allows it.

| Name | Python | Installs | Runs |
|---|---|---|---|
| `codestyle` | 3.14 | `.[dev]` | `ruff check .` |
| `build_docs` | 3.14 | `.[docs]` | `sphinx-build -W --keep-going docs docs/_build/html` |
| `test` | 3.14 | `.[dev]` | `pytest -q` |
| `test` | 3.13 | `.[dev]` | `pytest -q` |

`MPLBACKEND: Agg` is set on the job so matplotlib never reaches for a display.
`caps.detect()` is safe under CI: stdin is not a tty, so every probe returns
immediately without writing escape sequences.

A build badge goes at the top of `README.md`.

## Risks

- **Python 3.13 wheels.** The matrix tests the floor as well as the default.
  If a dependency drops 3.13 before we do, that cell goes red for reasons
  unrelated to this code, and the response is to raise `requires-python`
  rather than to weaken the job.
- **RTD build environment.** Read the Docs must offer Python 3.14. If it does
  not yet, the config pins the newest it has and the CI `build_docs` job
  remains the authoritative check.
- **First CI run.** This repository has never had CI. The first run may
  surface pre-existing problems that are not regressions. Fix or file them;
  do not disable the job.

## Order of work

1. Move `docs/superpowers/` to `claude_docs/`, repointing the
   cross-references inside those files. (Done ahead of the plan, since the
   spec itself lived there.)
2. Sphinx scaffold, `conf.py`, the `docs` extra, `.readthedocs.yaml`.
3. Pages and the README includes.
4. The anchor test.
5. The iTerm2 admonition and citations.
6. GitHub Actions, last: `build_docs` needs something to build.
