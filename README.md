# specterm1d

A terminal-based viewer for 1D spectra, with IRAF `splot`'s keybindings.

Opens anything `specutils` can read — IRAF multispec, `tabular-fits`,
`wcs1d-fits`, SDSS, HST/COS, HST/STIS, JWST, APOGEE and more — plus pypeit's
`OneSpec` and `spec1d` products, including echelle files with their orders
grouped by object.

The point is to keep the `splot` muscle memory intact while drawing a real
matplotlib figure in the terminal, rather than an ASCII approximation of one.

## Install

```bash
pip install specterm1d                 # general FITS spectra
pip install 'specterm1d[pypeit]'       # adds OneSpec and spec1d support
pip install 'specterm1d[sixel]'        # optional libsixel encoder
```

pypeit is deliberately optional. Nothing imports it at module scope, so the
tool works as a general FITS viewer without it, and files it cannot open are
reported clearly rather than crashing on an import.

Requires Python 3.13+ and numpy 2.5+.

## Quick start

```bash
specterm1d spec1d_J0935+0924.fits      # or the short alias: st1d
```

Arrow keys move a crosshair, `?` pages the full keymap, `q` quits.

| Flag | Effect |
|------|--------|
| `--renderer kitty\|iterm2\|sixel\|halfblock` | force a backend instead of probing |
| `--units nm` | start in other dispersion units (`um`, `GHz`, anything astropy knows) |
| `--mouse` | enable click-to-position (off by default; see below) |
| `--format NAME` | force a loader instead of sniffing the file |
| `--log FILE` | measurement log path (default `splot.log`) |
| `--cursor FILE` | replay a keystroke script instead of reading the keyboard |
| `--dump OUT.png` | render one frame to a PNG and exit; needs no terminal |
| `--dump-size WxH` | pixel size for `--dump` (default `1200x700`) |
| `--debug` | show full tracebacks instead of one-line errors |

## Terminal support

One matplotlib figure is rendered to an RGBA buffer, and five interchangeable
backends put those pixels on screen. Axes, tick labels, error bands and fit
overlays therefore look the same everywhere; only the fidelity changes.

| Terminal | Backend | Notes |
|----------|---------|-------|
| kitty, Ghostty, WezTerm | kitty graphics | pixel-exact; PNG transport |
| iTerm2 | OSC 1337 inline image | pixel-exact |
| Windows Terminal 1.22+, foot, xterm, Konsole, mlterm, contour | sixel | detected via Primary Device Attributes |
| **stock macOS Terminal, GNOME Terminal, Alacritty** | **graphics window** | no graphics protocol exists; see below |
| ssh with no display, tmux over ssh | halfblock | always available |

The halfblock backend is first-class, not a stub - it is what runs wherever
neither an inline protocol nor a window is available. Each cell is `▀` with the top source pixel as foreground and the
bottom as background, giving `cols x 2*rows` effective pixels; frames are
diffed so a redraw costs only the cells that changed. Terminal.app never
gained 24-bit colour, so there is an xterm-256 path as well as truecolor.

Because that gives a 116x43 window a 116x82 pixel figure, halfblock does not
let matplotlib draw the axis decoration: a 4pt tick label is 5.6 px tall
there, which is a smear across three cells at any font size. Instead the
figure is rendered full bleed with nothing but data, and the terminal paints
the spines, tick marks, labels, title and legend as its own glyphs at your
font size. The curve ends up with more pixels than it had when matplotlib was
spending margins on labels nobody could read.

Under tmux the kitty protocol is never probed — its passthrough is unreliable
— so tmux users get sixel where tmux was built with `--enable-sixel`, and
halfblock otherwise.

### Two-window mode

Terminals with no inline-graphics protocol get a real matplotlib window
instead of half-block cells. This is what IRAF `splot` did on a
Tektronix-emulating terminal like `xgterm`: **you point at a feature in the
graphics window and press a key**, while prompts and measurement results
scroll past in the text terminal.

The terminal is a plain scrolling transcript in this mode — no full-screen
layout, no raw mode, no pinned status line. The live `x`/`y`/`pix` readout
moves to the window title, where your eye already is. `?` and `:show` scroll
past rather than paging.

Every binding means the same thing in both modes; that is the point.

| terminal | renderer |
|---|---|
| kitty, Ghostty, WezTerm | kitty protocol, inline |
| iTerm2 | iTerm2 protocol, inline |
| xterm with sixel | sixel, inline |
| Terminal.app, GNOME Terminal, Alacritty | graphics window |
| xterm on Linux with X11 | graphics window |
| ssh with no display, tmux over ssh | half-block |

Inline graphics still win where the terminal supports them — one window beats
two. Half-block is the last resort: correct everywhere, comfortable nowhere.

To force either mode:

```
specterm1d --gui spec1d.fits              # or --renderer gui
specterm1d --renderer halfblock spec1d.fits
```

The window opens at 1200x800 and is then yours to resize; resizing re-renders
at the new size. If no window can be opened — no `DISPLAY`, no usable
toolkit — specterm1d prints one line to stderr and falls back to half-block
rather than refusing to start.

## Keys

The complete reference is in [docs/keys.md](docs/keys.md). The most-used:

| Key | Action |
|-----|--------|
| `<space>` | report the cursor position and nearest pixel |
| `a` | expand between two marks; the same point twice autoscales everything |
| `c` / `r` | clear all windowing / redraw keeping it |
| `z` `,` `.` | zoom by two about the cursor; pan left; pan right |
| `(` `)` `#` | previous / next spectrum; go to one by index or name |
| `e` | equivalent width by summation |
| `m` | mean, RMS and S/N over a region |
| `k` + `g`/`l`/`v` | fit a gaussian, lorentzian or voigt profile |
| `h` + `a`/`b`/`c`/`l`/`r`/`k` | equivalent width from a measured width |
| `s` | boxcar smooth |
| `U` | undo the last transform |
| `w` | the gtools window submode |
| `:` | colon commands (`:units nm`, `:sigma`, `:sky`, `:mask`, …) |
| `q` | next input spectrum, then exit |

Multi-point commands are explicit: press the command key to arm it, then mark
each point with `<space>`. The crosshair's **y** matters — `e`, `k` and `h`
take their continuum from the cursor's y at each marked point, which is what
IRAF's `sumflux.x` does with `eqy1`/`eqy2`.

## Not implemented yet

These keys are **registered** and report "not implemented in v1" when pressed.
They are never silently absent and never rebound to something else, so muscle
memory cannot misfire:

`d` deblend · `t` ICFIT · `f` arithmetic · `i` write to file ·
`j` set pixel to cursor · `x` etch-a-sketch · `p` linear wavelength scale ·
`u` user coordinate scale · `y` standard-star overplot

## Differences from splot

Three, stated plainly:

- **The cursor is keyboard-driven.** Arrow keys move a 2D crosshair, shift
  moves further. This is how `splot` was used on Tektronix terminals with no
  mouse. Mouse positioning is opt-in via `--mouse` or `:mouse yes`, because
  mouse reporting hijacks the terminal's own text selection — which you want
  when copying numbers out of the status line.
- **`%` cycles the extraction/calibration variant** (`OPT/COUNTS`,
  `BOX/COUNTS`, `OPT/FLAM`, …) rather than an image band, which is the useful
  analogue for pypeit products.
- **`U` undoes a transform.** `splot` has no equivalent: there, `s` is
  destructive with no recovery short of reloading the file.

Beyond that, four display features `splot` had no data for: a one-sigma error
band (`:sigma`), masked-pixel highlighting (`:mask`), sky/telluric/model
overlays (`:sky`, `:telluric`, `:model`), and inverse-variance weighting of
profile fits.

## Measurement log

Measurements append to `splot.log` in IRAF's own column formats, taken from
`anshdr.x`, `eqwidth.x`, `gfit.x` and `avgsnr.x` — including the detail that
the `m` key suppresses the column header. Existing log-parsing scripts keep
working:

```
    center      cont      flux       eqw      core     gfwhm     lfwhm
    5183.6     1.234    -0.456      0.37
avg:        1.5  rms:       0.25   snr:     6.00
```

`:nolog` stops writing, `:log` resumes, and `:# some text` adds a comment.

## Batch use

`--cursor` replays a keystroke script, reproducing `splot`'s `cursor`
parameter. Combined with `--dump` it runs with no terminal at all:

```bash
cat > measure.txt <<'EOF'
5200 1.0 e
5200 1.0 <space>
5400 1.0 <space>
EOF

specterm1d spec.fits --cursor measure.txt --log out.log --dump frame.png
```

## Licence

BSD-3-Clause.
