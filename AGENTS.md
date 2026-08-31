# Repository Guidelines

## Project Structure & Module Organization

The `specterm1d/` package contains the application code. Core spectrum and session state live in
`spec.py` and `session.py`; terminal interaction is split across `cli.py`, `view.py`, `plot.py`,
`keymap.py`, and `cursorscript.py`. Keep new behavior close to the module that owns it rather than
expanding the CLI entry point. Tests live in `tests/` and generally mirror user-facing features,
while shared fixtures are defined in `tests/conftest.py`. Keybinding documentation belongs in
`docs/keys.md`. Packaging and tool configuration are centralized in `pyproject.toml`.

## Build, Test, and Development Commands

- `python -m pip install -e '.[dev]'` installs the package in editable mode with pytest, coverage,
  and Ruff.
- `pytest` runs the complete default test suite under `tests/`.
- `pytest tests/test_fitting.py -q` runs one focused test module during development.
- `pytest --cov=specterm1d` reports package coverage; the project does not enforce a numeric floor.
- `ruff check .` checks formatting-adjacent rules, imports, common bugs, and Python 3.13 compatibility.
- `specterm1d --dump frame.png spectrum.fits` performs a non-interactive rendering smoke test.

## Coding Style & Naming Conventions

Use four-space indentation, a 100-character line limit, and Python 3.13 syntax. Ruff enables the
`E`, `F`, `W`, `I`, `B`, `C4`, `SIM`, and `RUF` rule families; fix warnings instead of adding broad
ignores. Use `snake_case` for modules, functions, variables, and fixtures; `PascalCase` for classes;
and `UPPER_CASE` for constants. Keep imports sorted and add concise docstrings where behavior or
terminal cleanup constraints are not obvious.

## Testing Guidelines

Write pytest tests as `tests/test_<feature>.py` with functions named `test_<behavior>`. Prefer
temporary paths and existing fixtures so tests never write logs or generated spectra into the
repository. Mark tests needing local PypeIt development-suite data with `@pytest.mark.devsuite`,
and skip optional dependencies with `pytest.importorskip`. Add regression coverage for every bug
fix, especially around renderer fallback, input handling, and numerical measurements.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit-style subjects such as `feat:`, `fix:`, and `docs:`. Keep
subjects imperative and focused on one logical change. Pull requests should explain the user-visible
effect, list verification commands, and link relevant issues. Include screenshots or dumped frames
for rendering changes, and call out optional-backend or terminal-specific behavior explicitly.
