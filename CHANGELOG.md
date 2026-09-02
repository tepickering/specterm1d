# Changelog

Notable changes to specterm1d, newest first. Versions follow
[semantic versioning](https://semver.org), with the usual 0.x caveat that a
minor bump is where breaking changes live until 1.0.

## [Unreleased]

### Added

- **Logarithmic axes: `:logx`, `:logy`, `:linx`, `:liny`.** Something splot
  never had, and what high dynamic range spectra want - an emission line four
  decades over the continuum leaves everything else flat on the floor of a
  linear plot. Autoscaling holds the bottom within six decades of the peak, so
  positive noise excursions near zero cannot swallow the window, and
  non-positive pixels break the line rather than being clipped onto the axis.
  A switch with nothing positive to show declines and says so. The `text`
  backend draws its own decade ticks, and clicks, arrow keys, zooming and
  panning all work across the axis rather than across the value range.

## [0.2.0] - 2026-09-01

### Added

- **`--theme NAME`.** `xgterm` (the new default), `dark`, or any name in
  `matplotlib.style.available`. A matplotlib style contributes its colours and
  its grid; its fonts, line widths and padding are left alone, because those
  are tuned against the terminal's pixel budget rather than a page. Roles a
  style has no opinion about are derived from the ones it does.
- **kitty graphics under tmux**, wrapped in tmux's DCS passthrough. Needs
  `set -g allow-passthrough on` in `~/.tmux.conf`; without it tmux discards
  the escapes and you get a window or the text backend.

### Changed

- **The default palette is xgterm's**: a cyan box on black, yellow numbers,
  green captions and a white spectrum on a DarkSlateGray surround, sampled
  from a live Community IRAF window. `--theme dark` restores the previous
  blue-on-charcoal look.
- **The `text` backend replaces `halfblock`**, splitting each cell on a 2x2
  grid instead of top-and-bottom halves. On a 4097-pixel UVES order in a
  116x43 window a screen column carries 18 spectrum pixels rather than 37,
  and RMS error against a full-resolution render falls from 63.5 to 53.5.
- The `text` backend defaults to the `dark` theme, one ink on one ground, to
  match a backend that is already a reduction. `--theme` overrides it.
- Plot labels are a notch larger, without changing the dpi the rest of the
  decoration is sized against.
- The sixel palette is derived from the active theme rather than being a
  fixed 16-entry table.
- Naming a backend with `--renderer` or `--gui` now skips the graphics probes
  entirely, since nothing but the choice of renderer reads them.

### Removed

- **`--renderer halfblock`**. Use `--renderer text`.

### Fixed

- A capability probe could leave its payload on screen. Stock Terminal.app
  answers a kitty graphics probe by printing the probe, and it landed in the
  scrollback before the alternate screen was entered. Probes now save and
  restore the cursor around themselves.
- Under tmux, the sixel bit in the Device Attributes reply describes *tmux*,
  which answers it with no client attached at all. It is now checked against
  what tmux says its client can display, instead of drawing tmux's
  `SIXEL IMAGE (134x44)+++++` placeholder in place of a plot.
- kitty placements under tmux no longer let the terminal move the cursor,
  which was desynchronising tmux's cursor model - long blackouts, and a
  status line that jumped from the bottom of the window to the top.

## [0.1.2] - 2026-08-31

### Changed

- Releases are cut from the tag push itself, rather than from a Release
  created by hand. No user-visible change.

## [0.1.1] - 2026-08-31

Tagged but **never published to PyPI** - it predates the release automation
and no Release was ever cut for it, so PyPI goes 0.1.0 to 0.1.2.

### Changed

- Documentation only: the landing page opens with the README's own blurb, and
  specutils and pypeit link to their documentation.

## [0.1.0] - 2026-08-31

First release. A terminal viewer for 1D FITS spectra with IRAF `splot`
keybindings: five interchangeable graphics backends (kitty, iTerm2, sixel, a
matplotlib window, and block glyphs), loaders for specutils and pypeit files,
equivalent widths and gaussian/lorentzian/voigt fits written to a `splot.log`,
cursor scripts for batch measurement, and a documentation site.

[Unreleased]: https://github.com/tepickering/specterm1d/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/tepickering/specterm1d/compare/v0.1.2...v0.2.0
[0.1.2]: https://github.com/tepickering/specterm1d/compare/v0.1.1...v0.1.2
[0.1.1]: https://github.com/tepickering/specterm1d/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/tepickering/specterm1d/releases/tag/v0.1.0
