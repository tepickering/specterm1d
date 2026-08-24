# specterm1d — Design

**Date:** 2026-08-24
**Status:** Approved, ready for implementation planning

## Purpose

A terminal-based 1D spectrum viewer for FITS data, reproducing IRAF `splot`'s
keybindings and functionality in a modern terminal.

The tool targets people who already know `splot` and want that interaction model
back without an X server. It reads pypeit `OneSpec` and `spec1d` products
directly, and anything `specutils` can parse otherwise.

Inspiration comes from the `xgterm`/`splot` interface and from `specterm`
(https://jrf.io/posts/specterm/), an audio spectrum visualizer built on
`ratatui` — the borrowing there is the TUI rendering approach, not the domain.

## Scope

**v1 is a viewer plus non-destructive measurement.** Every `splot` key is bound
to its `splot` meaning; keys outside v1 are *registered* and report
"not implemented in v1" rather than being absent, so muscle memory never
silently misfires.

In scope: all display and navigation, equivalent width by summation, region
statistics, single-profile fitting, Gaussian-from-specified-width, boxcar
smoothing, profile subtraction, and measurement logging.

Deferred: `d` (deblend), `t` (ICFIT continuum fitting), `f` (arithmetic mode),
`i` (write spectrum), `j` / `x` (pixel editing), `p` / `u` (redefine
wavelength scale), `y` (standard-star overplot).

## Architecture

Python throughout — `specutils` and `pypeit` are Python-only, and a compiled
core would need an IPC bridge for no gain.

No TUI framework. `splot`'s UI is one full-screen plot, one status line, and an
occasional prompt; a widget toolkit would buy layout machinery we never use
while fighting us over raw graphics escape sequences and over `splot`'s modal
"the next keystroke is an argument to the last one" semantics.

The pipeline is:

    FITS file
      -> loader registry        (io/)      -> SpecCollection of Spec
      -> view state             (view.py)  -> ranges, units, toggles
      -> matplotlib Agg figure  (plot.py)  -> RGBA buffer
      -> renderer backend       (term/)    -> escape sequences on stdout

### Module layout

    specterm1d/
      cli.py            argparse, file globbing, --renderer/--format/--units
      spec.py           Spec, SpecEntry, SpecCollection, unit conversion
      io/
        registry.py     sniff() and the loader protocol
        pypeit_io.py    OneSpec + SpecObjs
        specutils_io.py the generic specutils path
      term/
        caps.py         capability detection, cell-size query, SIGWINCH
        input.py        raw-mode key reader, escape-sequence parsing
        kitty.py  iterm2.py  sixel.py  halfblock.py
      plot.py           the persistent Figure, decimation, overlays
      view.py           ViewState: ranges, units, toggles, overplot stack
      keymap.py         splot table -> command names
      commands/         display.py  measure.py  transform.py  colon.py
      fitting.py        gaussian/lorentzian/voigt, EW integration, region stats
      logfile.py        splot.log-compatible writer
      session.py        the main loop

## Data model

Everything upstream of the renderer speaks one type. Loaders are the only code
that knows about FITS.

```python
@dataclass
class Spec:
    wave:      np.ndarray             # float64, ascending
    flux:      np.ndarray
    sigma:     np.ndarray | None      # derived from ivar where that is what the file holds
    mask:      np.ndarray | None      # True = good
    wave_unit: u.Unit                 # Angstrom by default
    flux_unit: u.Unit | None          # None = uncalibrated counts
    overlays:  dict[str, np.ndarray]  # 'telluric', 'obj_model', 'sky' - same grid as wave
    meta:      SpecMeta               # label, source path, header, PYP_SPEC, ech_order, ...
```

Two normalizations happen at the loader boundary and are never revisited
downstream:

1. **ivar -> sigma**: `1/sqrt(ivar)`, `inf` where `ivar <= 0`.
2. **mask -> True means good**. pypeit's `mask` is 1=good; `specutils`
   follows numpy, where 1=*bad*. Getting this backwards silently blanks the
   entire spectrum, so it is normalized once, at the edge.

### Variants and collections

The OPT/BOX toggle is not a flag: `BOX_WAVE` and `OPT_WAVE` are genuinely
different arrays, so a variant is a whole `Spec`.

```python
@dataclass
class SpecEntry:
    label:    str                     # 'SPAT0473-SLIT0461-DET01' or 'ORDER0142'
    variants: dict[str, Spec]         # 'OPT/COUNTS', 'OPT/FLAM', 'BOX/COUNTS', 'BOX/FLAM'
    default:  str                     # prefer OPT; prefer FLAM when fluxed

class SpecCollection:                 # what one file yields
    entries: list[SpecEntry]
    groups:  list[Group] | None       # echelle: orders grouped under their object
```

This gives `splot`'s navigation keys exact meanings:

| Key | splot meaning | Meaning here |
|-----|---------------|--------------|
| `)` / `(` | next / previous image line | next / previous entry in the collection |
| `#` | query for aperture/line | prompt for entry index or label, tab-completing |
| `%` | get a different band | cycle the variant (OPT<->BOX, COUNTS<->FLAM) |
| `g` | get another spectrum | prompt for a path, load a new collection |
| `q` | next input spectrum, then exit | next file on the command line, then exit |

`%` for the variant toggle is the one key bent to a new meaning. A spec1d's
OPT/BOX pair is the same dispersion in a different band of the same file, which
is close to what `%` meant. Revisit based on user feedback.

## I/O

`sniff(path) -> Loader`, tried in order, first match wins. `--format` overrides.

1. **pypeit OneSpec** — `hdul[1].header['DMODCLS'] == 'OneSpec'`, then
   `OneSpec.from_file(..., chk_version=False)`. Version checking is disabled
   deliberately: a datamodel version bump must not stop the viewer opening
   yesterday's file.
2. **pypeit spec1d** — `DMODCLS == 'SpecObj'` in an extension, then
   `SpecObjs.from_fitsfile()`. `PYPELINE == 'Echelle'` triggers order grouping
   via `ECH_ORDER`.
3. **specutils** — `identify_spectrum_format()`, then `Spectrum.read` /
   `SpectrumList.read`. 29 formats, including `iraf` (multispec),
   `tabular-fits`, `wcs1d-fits`, SDSS, HST/COS, HST/STIS, JWST, and APOGEE.
4. **Failure** — report which loaders were tried and why each declined. Never a
   bare traceback.

`DMODCLS`/`DMODVER` are written by every pypeit `DataContainer`
(`pypeit/datamodel.py:1307`), and pypeit itself discriminates this way
(`pypeit/specobjs.py:83`).

## Rendering

### Renderer interface

```python
class Renderer(Protocol):
    name: str
    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]: ...
    def draw(self, rgba: np.ndarray, rect: CellRect) -> None: ...
    def teardown(self) -> None: ...
```

`target_pixels()` unifies the backends: graphics protocols return the window's
true pixel dimensions, halfblock returns `(cols, 2*rows)`. `plot.py` renders one
figure at whatever size it is told and never knows which backend consumes it.

This is what keeps the fallback cheap. There is **one plot model and one
figure**; backends differ only in how they get pixels onto the screen. Axes,
ticks, labels, error bands, mask breaks, fit overlays and legends reach every
backend identically, with no feature built twice.

### Terminal support

| Terminal | Inline graphics |
|----------|-----------------|
| Apple Terminal.app (stock macOS) | none |
| Ghostty, kitty | kitty protocol |
| iTerm2, WezTerm | iTerm2 protocol + sixel |
| Windows Terminal >= 1.22 | sixel |
| Windows Console / conhost | none |
| Linux: foot, xterm >= patch #359, Konsole, mlterm, contour | sixel |
| Linux: GNOME Terminal / VTE | none |
| Alacritty | none |
| tmux | sixel only if built `--enable-sixel`; kitty passthrough unreliable |

Stock macOS Terminal, GNOME Terminal and Alacritty have no graphics protocol at
all, which is why the halfblock backend is a first-class renderer rather than a
degraded stub. On a stock Mac the fallback *is* the product.

Note that `arewesixelyet.com` is stale: it still lists Windows Terminal as
unsupported, but sixel landed in v1.22.

### Capability detection

In order; first hit wins. `--renderer` and `SPECTERM1D_RENDERER` short-circuit
everything: an explicitly named backend is used without probing, so a terminal
that supports a protocol but does not advertise it can still be driven. Every
query is timeout-guarded and falls through on silence — a terminal that ignores
a query must never hang the tool.

1. **Not a TTY** — refuse interactive mode, suggest `--dump out.png`.
2. **kitty** — query `\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\`, wait <=100 ms
   for `\x1b_Gi=31;OK`. Covers Ghostty, kitty, WezTerm. Not attempted under
   `$TMUX`.
3. **iTerm2** — `TERM_PROGRAM=iTerm.app` or `LC_TERMINAL=iTerm2`.
4. **sixel** — Primary Device Attributes (`\x1b[c`); sixel is advertised as
   `;4;`. This single query covers Windows Terminal >=1.22, foot,
   xterm >=#359, Konsole, mlterm and contour with no per-terminal casing.
5. **halfblock** — always available. Truecolor when `COLORTERM` is
   `truecolor`/`24bit`, otherwise quantized to the xterm-256 cube
   (Terminal.app's case — it never got 24-bit color).

Graphics backends need window pixel dimensions from `TIOCGWINSZ`
(`ws_xpixel`/`ws_ypixel`), falling back to the `\x1b[16t` cell-size query. The
terminals that report these correctly are exactly those with graphics
protocols; halfblock derives its size from `cols x 2*rows` and never needs the
query.

### The figure

One `Figure`, created once, mutated in place. Artists are built once and
updated: main line, +/-sigma band, mask-highlight collection, one line each for
`telluric` / `obj_model` / `sky` toggled via `set_visible()`, plus a transient
group for fit results and region markers cleared on `c` / `r`.

**Decimation** is what makes interaction feel instant. When the in-view pixel
count exceeds roughly 4x the figure width, bin by output column and emit per-bin
`(min, max)`. The drawn curve is visually identical to plotting every point, at
`2 x width` vertices instead of 100k. Recomputed per redraw via `searchsorted`
for the range plus a `reduceat` min/max.

Mask breaks are inserted as `np.nan` **before** decimation, using nan-aware
reductions, so a chip gap breaks the line instead of being bridged by a
straight segment across it.

### Transport

Naively base64-ing a raw RGB buffer is a trap: 1200x700x3 is 2.5 MB, 3.4 MB once
base64'd, written to a pty on every keystroke.

- **kitty / iTerm2** — PNG (`f=100`) at `compress_level=1` via PIL, already a
  matplotlib dependency. Line plots on a flat background compress to roughly
  30-80 KB, so ~100 KB of base64 per frame rather than 3.4 MB. Reuse a fixed
  image id so kitty replaces in place without flicker.
- **sixel** — encoding is the cost here. Use `libsixel-python` when importable;
  otherwise a vectorized numpy encoder against a **fixed 16-color palette**.
  Our plots use about a dozen colors, so restricting the palette on the sixel
  path (and dropping antialiasing there) makes the encode both fast and small.
  Mild quality loss confined to sixel terminals.
- **halfblock** — build the cell grid in numpy, then **diff against the previous
  frame and emit only changed cells**. Without double-buffering a 200x50 grid is
  ~200 KB of ANSI per frame.

Redraw budget, to be measured rather than trusted: decimation well under a
millisecond, `canvas.draw()` 15-35 ms, transport 1-5 ms. Target is under 50 ms
for pan/zoom. If `canvas.draw()` dominates in practice, kitty's shared-memory
transfer (`t=s`) and blitting only the axes region are the escape hatches.

## Interaction

Raw mode via `tty.setraw`. The reader yields a printable key, a parsed escape
sequence, or a synthetic `RESIZE` from a SIGWINCH self-pipe.

`splot`'s two-stage commands become an explicit small state machine: a command
returns `AwaitKey(handler)` and the loop routes the next keypress there. In v1
that serves `k`->`g|l|v`, `h`->`a|b|c|l|r|k` and the `w` window submode; the
deferred `t`->`/|-|f|c|n|q` and `u`->`d|z|l` drop into the same mechanism
unchanged when they land.

The same machine provides `AwaitCursor(n, handler)` for commands wanting two
marked positions — `a`, `e`, `m`, `k` in v1, and `d` later — which is most of
the measurement set.

**Cursor.** `xgterm` gave a mouse-driven crosshair; a terminal does not. The
cursor is keyboard-driven — arrows move one pixel, shift-arrows jump by a screen
fraction, and the status line tracks `x`, `y` and pixel index live. This matches
how `splot` was used on Tektronix terminals without mouse support.

**Mouse.** Optional SGR mouse reporting for cursor positioning, since it hijacks
text selection. Off by default; enabled with `--mouse` or `:mouse yes`.

**Layout.** `splot`'s: the plot fills all but the bottom two rows, then a status
line (`x`, `y`, pixel, entry `n/N`, variant, units, active toggles) and a
message/prompt line where `:` commands and queries land.

## Keymap

All keys keep their `splot` meanings.

**Display and navigation (v1)**

`?` page help - `/` cycle status help - `<space>` report cursor and nearest
pixel - `a` expand/autoscale between two cursors, same point twice autoscales
all - `b` zero base level - `c` clear windowing - `r` redraw - `w` window
submode - `z` zoom x2 in x - `,` `.` shift left/right - `(` `)` prev/next
entry - `#` prompt for entry - `%` variant toggle - `$` pixel<->world coords -
`v` velocity scale about cursor - `o` overplot next - `g` load another
spectrum - `q` next file then exit - `I` hard quit

**Transforms (v1)**

`l` -> f-lambda - `n` -> f-nu - `s` boxcar smooth - `-` subtract the profile
fitted by `k`/`h`

**Measurement (v1)**

`e` EW by summation - `m` mean/RMS/S-N - `k`+`g|l|v` single
Gaussian/Lorentzian/Voigt fit - `h`+`a|b|c|l|r|k` Gaussian from a specified
width

**Registered but deferred**

`d` deblend - `t` ICFIT - `f` arithmetic mode - `i` write spectrum - `j` set
pixel - `x` etch-a-sketch - `p` linear wavelength scale - `u` user coordinate
scale - `y` standard-star overplot

**Notes**

- `w` hides a whole sub-language: gtools' window mode, with its own keymap.
  Those bindings will be lifted from the gtools help file at implementation
  time rather than reconstructed from memory, as `splot.hlp` was. `w` ships in
  v1 covering the gtools keys that manipulate the plot window; any gtools key
  concerning features this tool does not have is registered as
  not-implemented, consistent with the deferred top-level keys.
- `-` is in v1 because it is the natural companion to `k`/`h`: fit a line,
  subtract it, inspect the residual.
- **`U` = undo** is the one addition `splot` lacks. In real `splot`, `s` is
  destructive with no recovery short of reloading via `g`. Since v1 ships four
  mutating transforms (`s`, `-`, `l`, `n`), a transform stack costs almost
  nothing and removes a genuine footgun. Every mutating command pushes onto
  that stack; `U` pops it. `U` is unbound in `splot`, so nothing is displaced.

### Colon commands

As in `splot`: `:log` `:nolog` `:show` `:units <u>` `:# <comment>` `:label`
`:mabove` `:mbelow` `:auto` `:zero` `:hist` `:nosysid` `:wreset` `:flip`
`:overplot`.

Dropped: `:dispaxis`, `:nsum` — 2D-image concerns; this tool ingests 1D.

New: `:mouse [yes|no]`, `:renderer <name>`, `:variant <name>`, and toggles
`:sigma` `:mask` `:telluric` `:sky` `:model`.

`:units` maps onto `astropy.units` with `u.spectral()`, which already handles
wavelength <-> frequency <-> energy <-> wavenumber. Angstrom, nm, micron, Hz
through GHz, eV through MeV and 1/cm all follow, along with `splot`'s `log` and
`inverse` modifiers.

## Analysis

`e` reproduces `splot`'s method: linear continuum between the two marked points,
sum the pixels with partial pixels at the ends, report center, continuum at
center, flux, and equivalent width (positive for absorption).

`k` fits the marked region with `scipy.optimize.least_squares` over a linear
continuum, reporting center, continuum, core intensity, integrated flux,
equivalent width and FWHM.

`h` implements all six width conventions from the help text: `a` left half width
at half flux, `b` right half width at half flux, `c` full width at half flux,
`l` left width at a marked flux level relative to a normalized continuum, `r`
right width at that level, `k` full width at that level.

**Improvement over splot:** where `sigma` exists, fits are inverse-variance
weighted and `m` reports both the empirical RMS and the propagated error.
`splot` had no uncertainty array available; we do.

The `splot.log` output format will be lifted from IRAF's `splot` sources rather
than reconstructed, so existing log-parsing scripts keep working.

## Beyond-splot display features

All four are v1, because the arrays are already in the files:

- **Sigma overlay** — toggleable 1-sigma envelope from `OneSpec.sigma`/`ivar` or
  `OPT_COUNTS_SIG`/`OPT_FLAM_SIG`.
- **Mask handling** — masked pixels break the line rather than being drawn as
  zeros, with a toggle to highlight them. Without this, bad columns and chip
  gaps create fake features that dominate autoscaling.
- **OPT/BOX and counts/FLAM toggle** — via `%`.
- **Model overlays** — `telluric` and `obj_model` from `OneSpec`, sky
  (`OPT_COUNTS_SKY`) from `SpecObj`, each independently toggleable.

## Error handling

The failure mode that matters most is terminal restoration. Raw mode plus a
hidden cursor plus a stray placed image is the worst way for a TUI to die.
Teardown therefore runs from `try/finally`, `atexit`, and `SIGTERM`/`SIGHUP`
handlers alike: restore termios, show cursor, disable mouse reporting, delete
placed images.

Beyond that: any command that raises is caught, reported on the message line,
and the session continues; `--debug` promotes it to a full traceback. A loader
failure leaves the user on the current spectrum with an explanation of which
loaders declined and why.

## Testing

Development is test-first. The measurement math is where correctness lives, so
it is tested first and hardest: synthetic Gaussians with analytically known
equivalent width and FWHM, asymmetric blends, pure-noise spectra, and regions
containing masked pixels.

The renderer boundary is the seam that makes everything else testable. No test
drives a real terminal.

- **Loaders** — small synthetic fixtures generated by writing `OneSpec` and
  `SpecObjs` objects, keeping the suite self-contained. Tests against the real
  dev-suite files (`mmt_binospec_ifu` multislit, `vlt_uves_red` echelle in
  `PypeIt-development-suite/REDUX_OUT`) sit behind a marker that skips when the
  path is absent.
- **Renderers** — golden-image comparison with tolerance for the figure; unit
  tests for halfblock cell mapping on a tiny known array, for kitty escape
  framing and chunking, and for the numpy sixel encoder cross-checked against
  `libsixel` where installed.
- **Input** — feed raw byte strings, assert `Key` events; fake query responses
  to test capability detection.
- **End-to-end, headless** — `splot` has a `cursor` parameter for driving it
  from a command file. Reproducing that as `--cursor script.txt --dump out.png`
  gives full-stack integration tests with no tty: feed a keystroke script,
  assert on the log output and the rendered image.

## Packaging

`pyproject.toml`, Python >= 3.11, console scripts `specterm1d` and `st1d`.

Required: numpy, scipy, matplotlib, astropy, specutils.

**pypeit is an optional extra**, not a hard dependency. It is a heavy install,
and this must be usable as a general FITS spectrum viewer without it. The
loader registry drops the `OneSpec` and `spec1d` entries when the import fails,
and says so clearly if handed a spec1d file anyway.

`libsixel-python` is likewise optional (`[sixel]`), with the numpy encoder as
fallback.

Development targets the existing `pypeit3.14` conda environment, which already
has `specutils 2.4.0` and a pypeit dev build.

### CLI

    specterm1d [FILES...] [--renderer kitty|iterm2|sixel|halfblock] [--format NAME]
               [--units UNIT] [--mouse] [--cursor FILE] [--dump FILE]
               [--log FILE] [--debug]

## Open items for implementation

These are known-unknowns to resolve by reading source, not design gaps:

1. The gtools `w` window-mode keymap, from the IRAF gtools help file.
2. The exact `splot.log` column format, from IRAF's `splot` sources.
3. Measured redraw timings, to confirm the sub-50 ms target and decide whether
   kitty shared-memory transfer is needed.
