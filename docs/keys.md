# specterm1d key reference

Generated from `specterm1d.keymap`, so it cannot drift from the
implementation. Regenerate with the snippet at the bottom of this file.

## Cursor movement

| Key | Action |
|-----|--------|
| `<left>` `<right>` | move the crosshair in x |
| `<up>` `<down>` | move the crosshair in y |
| `<shift>` + any arrow | move 25x further |

The crosshair's **y** is not decoration: `e`, `k` and `h` take the
continuum from the cursor's y at each marked point, exactly as IRAF's
`sumflux.x` does with `eqy1`/`eqy2`.

```{note}
An arrow moves the crosshair by 0.2% of the visible range, 5% with shift.
That is finer than the mouse can place it in any terminal reporting the
pointer in cells — **every terminal under tmux**, which has no pixel mouse
mode. So where the y value matters, click to get close and then nudge with
the arrows rather than trusting the click. `--gui` gives true pixel
pointing if you would rather have it.
```

## Commands

| Key | Command | Status |
|-----|---------|--------|
| `?` | page help information | v1 |
| `/` | cycle through short status line help | v1 |
| `<space>` | report cursor position and nearest pixel | v1 |
| `a` | expand and autoscale between two cursors | v1 |
| `b` | set the plot base level to zero | v1 |
| `c` | clear all windowing and redraw | v1 |
| `e` | measure equivalent width by summation | v1 |
| `g` | get another spectrum | v1 |
| `h` | equivalent width from a specified width | v1 |
| `k` | fit a single line profile | v1 |
| `l` | convert to flux per unit wavelength | v1 |
| `m` | mean, RMS and S/N over a region | v1 |
| `n` | convert to flux per unit frequency | v1 |
| `o` | overplot the next spectrum | v1 |
| `q` | go on to the next spectrum, then exit | v1 |
| `r` | redraw with the current windowing | v1 |
| `s` | smooth via a boxcar | v1 |
| `v` | toggle a velocity scale about the cursor | v1 |
| `w` | window the graph | v1 |
| `z` | zoom the graph by a factor of 2 in x | v1 |
| `(` | go to the preceding spectrum | v1 |
| `)` | go to the following spectrum | v1 |
| `#` | go to a spectrum by index or name | v1 |
| `%` | cycle the extraction/calibration variant | v1 |
| `$` | switch between pixel and world coordinates | v1 |
| `-` | subtract the fitted profile | v1 |
| `,` | shift the graph window to the left | v1 |
| `.` | shift the graph window to the right | v1 |
| `U` | undo the last transform (not in splot) | v1 |
| `I` | leave the graph immediately | v1 |
| `:` | enter a colon command | v1 |
| `d` | deblend multiple line profiles | **not implemented in v1** |
| `f` | arithmetic function mode | **not implemented in v1** |
| `i` | write the current spectrum to a file | **not implemented in v1** |
| `j` | set the nearest pixel to the cursor value | **not implemented in v1** |
| `p` | define a linear wavelength scale | **not implemented in v1** |
| `t` | fit a function to the spectrum with ICFIT | **not implemented in v1** |
| `u` | adjust the user coordinate scale | **not implemented in v1** |
| `x` | etch-a-sketch line drawing | **not implemented in v1** |
| `y` | overplot standard star calibration values | **not implemented in v1** |

Deferred keys are registered, never absent: pressing one reports
"not implemented in v1" rather than doing nothing or firing something else.

## Two-stage commands

| First | Second | Meaning |
|-------|--------|---------|
| `k` | `g` / `l` / `v` | gaussian / lorentzian / voigt profile fit |
| `k` | anything else | defaults to gaussian, as splot does |
| `h` | `a` / `b` / `c` | continuum from the cursor y; LEFT / RIGHT half, or FULL width at half flux |
| `h` | `l` / `r` / `k` | normalized continuum of 1; LEFT / RIGHT / FULL width at the marked level |
| `w` | see below | the gtools window submode |

## `w` window submode

Transcribed from IRAF `pkg/xtools/gtools/gtwindow.x` and
`lib/scr/gtools.key`. Shifts move 0.75 of the window, zooms are
cursor +/- d/4, and `p` pans to cursor +/- d, which doubles the span.

| Key | Action |
|-----|--------|
| `a` | autoscale x and y axes |
| `b` | set bottom edge of window |
| `c` | center window at cursor position |
| `d` | shift window down |
| `e` | expand window (mark two corners) |
| `f` | flip x axis |
| `g` | flip y axis |
| `j` | set left edge of window |
| `k` | set right edge of window |
| `l` | shift window left |
| `m` | autoscale x axis |
| `n` | autoscale y axis |
| `p` | pan x and y axes about cursor |
| `r` | shift window right |
| `t` | set top edge of window |
| `u` | shift window up |
| `x` | zoom x axis about cursor |
| `y` | zoom y axis about cursor |
| `z` | zoom x and y axes about cursor |

## Colon commands

| Command | Meaning |
|---------|---------|
| `:#` | add a comment line to the log |
| `:auto` | alias for `:wreset` |
| `:dispaxis` | 2D-image concern; specterm1d ingests 1D |
| `:flip` | reverse the dispersion axis |
| `:hist` | draw the spectrum as a histogram |
| `:log` | resume writing measurements to the log file |
| `:mask` | highlight masked pixels |
| `:model` | overlay the object model |
| `:mouse [yes\|no]` | toggle positioning (inline by default; pixel-precise where the terminal does DECSET 1016, cells under tmux) |
| `:nolog` | stop writing to the log file |
| `:nosysid` | accepted for splot compatibility; no effect |
| `:nsum` | 2D-image concern; specterm1d ingests 1D |
| `:overplot` | overplot the next spectrum |
| `:renderer` | report the active renderer |
| `:show` | toggle display of previous measurements |
| `:sigma` | show the one-sigma error band |
| `:sky` | overlay the sky spectrum |
| `:telluric` | overlay the telluric model |
| `:units` | set the dispersion units, e.g. `:units nm`, `:units GHz` |
| `:variant` | select an extraction/calibration variant by name |
| `:wreset` | re-autoscale when moving to another spectrum |
| `:zero` | plot the base level at zero |

Boolean toggles accept `yes`/`no` (also `on`/`off`, `1`/`0`); with no
argument they flip the current setting.

## Cursor scripts

`--cursor FILE` replays a keystroke script instead of reading the
keyboard, reproducing splot's `cursor` parameter. One directive per
line; `#` starts a comment.

```
# <x> <y> <key> [text]   - '-' keeps the current cursor position
5200 1.0 e               # arm an equivalent-width measurement
5200 1.0 <space>         # mark the first continuum point
5400 1.0 <space>         # mark the second
:units nm                # a leading colon runs a colon command
- - s 5                  # trailing text is typed, then Entered
```

Named keys: `<space>`, `<enter>`, `<return>`, `<escape>`, `<esc>`, `<tab>`.

Combine with `--dump out.png` to render the result headlessly, with no
terminal involved at all.

---

Regenerate the command tables above from the implementation:

```bash
python - <<'EOF'
import specterm1d.commands
from specterm1d.keymap import KEYMAP
for key in sorted(KEYMAP):
    b = KEYMAP[key]
    print(key, b.name, b.help, 'deferred' if b.deferred else '')
EOF
```
