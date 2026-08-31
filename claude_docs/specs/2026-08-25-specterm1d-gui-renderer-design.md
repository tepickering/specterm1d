# specterm1d — GUI renderer (two-window mode)

**Date:** 2026-08-25
**Status:** Approved, ready for implementation planning
**Extends:** `claude_docs/specs/2026-08-24-specterm1d-design.md`

## Purpose

Give terminals with no inline-graphics protocol a real matplotlib window
instead of half-block cells, and drive it the way `splot` was driven under
`xgterm`: **you point at a feature in the graphics window and press a key**,
while prompts and measurement results scroll past in the text terminal.

This is a two-window fallback, and it has precedent — it is exactly what IRAF
did on a Tektronix-emulating terminal. Inline graphics in one window remains
the ideal; this is what to do when the terminal cannot provide it.

## Why

The half-block backend renders one pixel per column and two per row. On the
reference terminal (116x43, SF Mono 14) that is a 116x82 pixel figure. Two
rounds of work made it legible — scaled chrome, then terminal-drawn chrome —
and it is still not comfortable to work in, for a reason no encoding fixes:

| | plot width | pixels per column, 4097-pixel UVES order |
|---|---|---|
| half-block, 116x43 | 112 cells | 36.6 |
| braille (2x horizontal) | 224 cells | 18.3 |
| **GUI window, 1200 px** | **1200 px** | **none — see below** |

`plot.decimate()` only engages above `4 * ncols` points. At a 1200-pixel-wide
window that threshold is 4800, so a 4097-pixel order is drawn **undecimated,
every pixel**. The window does not reduce the binning; it removes it.

It also removes the cursor compromise. Terminal cursor positioning is
quantized to a cell — one part in 112 of the visible range — and `--mouse`
has to hijack terminal selection to get even that. A matplotlib motion event
carries `event.xdata` directly: exact, continuous, and free.

## Scope

**In scope:** a `gui` renderer backend; window-sourced key and pointer events
feeding the existing dispatcher; a scrolling text transcript in the terminal;
renderer selection and fallback; a blitted crosshair.

**Out of scope:** any change to `ViewState`, the keymap, the command registry,
the fitting code, the loaders, or the log format. Half-block, kitty, iTerm2 and
sixel behaviour is unchanged. `--dump` and `--cursor` are unchanged — they
construct `HalfblockRenderer` explicitly and never reach this path.

**Deferred:** a `Frontend` protocol that both the terminal TUI and the GUI
implement (see *Architecture*, "why not a refactor"). Click-to-mark during
`AwaitCursor` — marking stays on the space bar, as in `splot`.

## Architecture

### The shape of the change

`SpectrumPlot` already owns a persistent `Figure` with an Agg canvas attached.
A GUI canvas can adopt that same figure:

```python
FigureCanvasTkAgg(plot.fig)      # sets plot.fig.canvas, returns the canvas
```

`FigureCanvasTkAgg`, `FigureCanvasQTAgg` and `FigureCanvasMac` are all
subclasses of `FigureCanvasAgg`, so `canvas.buffer_rgba()` keeps working and
`SpectrumPlot.render()` needs no behavioural change. **There is one plot
model and one render path**, which is what makes chrome sizing, overlays,
sigma bands, fit curves and markers reach the window for free.

The window itself is created toolkit-agnostically, so one code path serves
Qt, Tk and the native macOS backend:

```python
manager = canvas_class.new_manager(plot.fig, num=1)
manager.show()
manager.set_window_title(text)
canvas.flush_events()            # pump the toolkit's event loop
```

### Why not a refactor

The honest end state is a `Frontend` protocol that the terminal TUI and the
GUI both implement, with `Session` reduced to dispatch and state. That is a
real refactor of a 522-line file that stabilized yesterday and sits on an
unmerged PR, and it would put the half-block and text-chrome work at risk to
buy symmetry we do not need yet. Instead the GUI enters through the existing
renderer registry, and `Session` grows three narrow branches. If the GUI path
earns more complexity later, extract the protocol then.

### Renderer protocol

`term/base.py` gains one flag and two optional methods, in the same style as
the existing `text_chrome`. Callers reach them with `getattr(..., default)`,
so no existing backend changes:

```python
class Renderer(Protocol):
    name: str
    text_chrome: bool = False

    # True when the backend owns its own window and event loop. The session
    # then takes keys from poll() rather than the terminal, prints text
    # rather than painting a status line, and never enters raw mode.
    interactive: bool = False

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]: ...
    def draw(self, rgba: np.ndarray, rect: CellRect) -> None: ...
    def teardown(self) -> None: ...

    # Interactive backends only.
    closed: bool                               # the user closed the window
    def attach(self, plot) -> None: ...        # adopt the figure, open the window
    def poll(self) -> list[GuiEvent]: ...      # drain queued window events
    def pump(self) -> None: ...                # let the toolkit run its loop
    def set_title(self, text: str) -> None: ...
```

where

```python
@dataclass(frozen=True)
class Motion:
    """Pointer position in data coordinates."""
    x: float
    y: float

GuiEvent = Key | Motion
```

`Key` is the existing `term.input.Key`, unchanged — which is what lets window
keys reach `Session.handle()` with no translation layer beyond
`key_from_mpl()`. `Motion` never reaches `handle()`; the loop filters it out.

`draw(rgba, rect)` is vestigial for `GuiRenderer` — the pixels are already on
screen, because `SpectrumPlot.render()` ends in `canvas.draw()` and a GUI
canvas paints as it draws. This is the accepted cost of approach A. To avoid
copying a 3.8 MB buffer per frame for nothing, `SpectrumPlot.render()` splits:

```python
def _draw(self, req: PlotRequest) -> None:
    """Everything up to and including canvas.draw(). No buffer copy."""

def render(self, req: PlotRequest) -> np.ndarray:
    self._draw(req)
    return np.array(self.fig.canvas.buffer_rgba(), dtype=np.uint8)
```

Terminal backends keep calling `render()`. The GUI path calls `_draw()`.

### Module layout

```
specterm1d/
  term/
    gui.py          GuiRenderer, backend probing, mpl event -> Key mapping
  transcript.py     scrolling text output for the terminal half
```

`gui.py` holds the window, the event queue and the crosshair. `transcript.py`
is pure and toolkit-free so it can be tested against a `StringIO`.

## Components

### `term/gui.py`

```python
GUI_BACKENDS = ("qtagg", "tkagg", "macosx")

class GuiUnavailable(RuntimeError):
    """No usable GUI backend, or the window could not be created."""

def available(env: dict | None = None) -> bool:
    """Cheap predicate for renderer selection. Never opens a window."""

def open_window(fig, size, backends=GUI_BACKENDS) -> tuple[canvas, manager, str]:
    """First backend whose window actually opens. Raises GuiUnavailable."""

class GuiRenderer:
    name = "gui"
    text_chrome = False
    interactive = True
```

`available()` is a predicate, not a guarantee: it answers "is it worth
trying", and the real answer comes from `open_window()` raising. The two
layers matter — importing `backend_tkagg` succeeds on a headless Linux box
with no `DISPLAY`; only `Tk()` fails. So:

- honour `MPLBACKEND` when set, and try only that backend
- `False` when `DISPLAY` and `WAYLAND_DISPLAY` are both unset and the platform
  is not Darwin — this is the SSH case
- otherwise `True`, and let `open_window()` be the judge

Window creation sets, before the manager exists:

- `rcParams["toolbar"] = "none"` — matplotlib's toolbar would drive `ax`
  limits behind `ViewState`'s back, desyncing the status readout. `ViewState`
  stays the single source of truth for the view.
- every `rcParams["keymap.*"] = []` — matplotlib binds `s` save, `p` pan,
  `o` zoom, `q` quit, `k`/`l` log scale, `g` grid, `f` fullscreen. All eight
  collide with `splot` bindings, and `q` would quit the window out from under
  the session.

### Event mapping

Callbacks append to a list and return; the list is drained by `poll()` from
the session loop. Callbacks fire inside `pump()`, so there is no reentrancy
and no thread — the queue exists to keep dispatch out of the toolkit's stack.

| matplotlib event | becomes |
|---|---|
| `key_press_event` | a `Key`, via the table below |
| `motion_notify_event` | `Motion(x=event.xdata, y=event.ydata)` when `event.inaxes is plot.ax`, else nothing |
| `button_press_event` | same as `Motion` — a click places the cursor |
| `close_event` | sets `renderer.closed`; the loop exits and the session ends |
| `resize_event` | marks the frame dirty and invalidates the crosshair background |

`event.key` maps onto the existing `Key` names:

```
'left' 'right' 'up' 'down'            -> Key(name)
'shift+left' ... 'shift+down'         -> Key('shift-' + direction)
'escape'                              -> Key('escape')
'enter' | 'return'                    -> Key('enter')
'backspace'                           -> Key('backspace')
'pageup' | 'pagedown'                 -> Key(name)
' '                                   -> Key('char', ' ')
any single character                  -> Key('char', char)
anything else (ctrl+..., f1, None)    -> dropped
```

The mapping is a pure function, `key_from_mpl(event_key) -> Key | None`, and
is tested as a table.

### `transcript.py`

The terminal half is a scrolling transcript, not a full-screen layout — no
raw mode, no hidden cursor, no pinned status line, no paging. Two operations,
because prompt echo and finished output behave differently:

```python
class Transcript:
    def line(self, text: str) -> None:
        """A finished line. Terminates any open prompt first."""

    def prompt(self, text: str) -> None:
        """Redraw an in-progress prompt in place: '\r' + text + erase-to-EOL,
        no newline. AwaitLine calls this on every keystroke; without it a
        30-character colon command would leave 30 lines of transcript."""
```

`Session` holds one, built in `__init__` over `self.out`:
`self.transcript = Transcript(self.out)`. It is constructed in both modes and
simply goes unused by the terminal path, so nothing branches on its existence.

`Session.message()` routes to `line()`. The `AwaitLine` echo path routes to
`prompt()`. `?` and `:show` print their lines through `line()` rather than
paging, so in GUI mode the key reference and the measurement log simply
scroll past, as they did in `splot`.

### `Session` branches

Three places, each guarded by `self.interactive`, set once in `__init__` from
`getattr(renderer, "interactive", False)`:

**`run()`** — replaces the `KeyReader` loop with the window loop. No raw mode,
no `HIDE_CURSOR`, no `CLEAR_SCREEN`:

```python
while not self.renderer.closed and running:
    self.renderer.pump()
    for event in self.renderer.poll():
        if isinstance(event, Motion):
            self.on_motion(event.x, event.y)   # cursor + title only
        else:
            running = self.handle(event)
            dirty = True
    if dirty:
        self.render()
        dirty = False
    self.renderer.set_title(self.status_line())
    time.sleep(POLL_INTERVAL)
```

**`render()`** — no `CellRect`, no text chrome, no footer, and no
`plot.resize()`: in GUI mode the *window* drives the figure size, not the
other way round. Initial size flows figure to window at construction;
every resize after that flows window to figure, and the toolkit has already
applied it by the time we draw.

**`message()`** — writes a transcript line instead of storing a string for a
footer that is never painted.

`on_motion(x, y)` replaces `on_mouse(col, row)` in this mode. It sets
`view.cursor_x/y` from data coordinates directly — no `ax.get_position()`
arithmetic, no cell quantization — and **must not** trigger a render.

### The dirty flag is not optional

Measured on the reference machine, `SpectrumPlot.render()`:

| figure | sigma off | sigma on |
|---|---|---|
| 116x82 (half-block) | — | 13 ms |
| 1200x800 (window) | 86 ms | **182 ms** |

Breakdown at 1200x800: empty axes 8 ms, plus the 4097-point line 41 ms, plus
`fill_between` 60 ms, plus ~20 ms rebuilding artists, the remainder in three
`decimate` calls and the title width measurement.

`Session.run()` today renders unconditionally every 0.25 s. At 182 ms a frame
that is most of a core spent redrawing an unchanged plot, and it makes pointer
tracking impossible. Hence: render on state change only, and never on motion.
`POLL_INTERVAL` is 0.01 s — the loop must poll faster than a person types,
and `pump()` on an idle window is microseconds.

### Crosshair

A drawn crosshair is what made `splot`'s cursor readable against the axes, so
it is in scope — but it cannot be a full redraw. Standard matplotlib blitting:

- after each full render, `background = canvas.copy_from_bbox(ax.bbox)`
- on motion, `canvas.restore_region(background)`, `ax.draw_artist(vline)`,
  `ax.draw_artist(hline)`, `canvas.blit(ax.bbox)` — a few milliseconds
- invalidate `background` on render and on resize

The crosshair is the last task and is separable: if blitting fights the
chosen backend, drop it and ship the pointer plus the title readout, which
already carry exact coordinates.

### Status readout

The window title carries the live readout — `manager.set_window_title()` is a
cheap toolkit call, so it can update on every motion event. It shows what the
terminal status line shows today (`status_line()`, unchanged), which keeps the
numbers where the eye already is instead of on the other window. `status_line()`
truncates to `caps.cols`; on a title that is a harmless no-op at any normal
terminal width, and not worth a second code path.

The window opens at 1200x800 and is then the user's to resize — there is no
size flag. Resizing re-renders at the new size, so the pixel budget is a
window drag rather than a command-line argument.

## Renderer selection

`PREFERENCE` becomes:

```python
PREFERENCE = ("kitty", "iterm2", "sixel", "gui", "halfblock")
```

| terminal | renderer |
|---|---|
| kitty, Ghostty, WezTerm | kitty protocol, inline |
| iTerm2 | iTerm2 protocol, inline |
| xterm with sixel | sixel, inline |
| **Terminal.app, GNOME Terminal, Alacritty** | **gui window** |
| xterm on Linux with X11 | gui window |
| ssh with no display, tmux over ssh | halfblock |

Inline graphics still win where the terminal supports them — one window is
better than two. Half-block is now the last resort it should always have
been: correct everywhere, comfortable nowhere.

Explicit selection, both spellings equivalent:

```
--renderer gui
--gui                 shortcut; sets --renderer gui when no renderer is given
--renderer halfblock  force the terminal path
```

`--renderer` gains `gui` in its `choices`. `RENDERERS` becomes
`("kitty", "iterm2", "sixel", "gui", "halfblock")`.

## Error handling

**No usable backend.** `available()` false, or `open_window()` raises. `cli.py`
falls back to `HalfblockRenderer`, prints one line to stderr naming the reason,
and continues. Never fatal: a viewer that refuses to start over a missing
window is worse than one that draws coarsely.

Ordering in `cli.py` makes this possible without constructing `Session` twice:

```python
renderer = choose_renderer(caps, override=args.renderer, out=sys.stdout)
width, height = renderer.target_pixels(caps.rows - 2, caps.cols)
plot = SpectrumPlot(width, height)
try:
    renderer.attach(plot)          # no-op on terminal backends
except GuiUnavailable as exc:
    print(f"graphics window unavailable ({exc}); using halfblock", file=sys.stderr)
    renderer = HalfblockRenderer(out=sys.stdout, truecolor=caps.truecolor)
session = Session(collection, renderer, plot, out=sys.stdout, caps=caps)
```

`GuiRenderer.target_pixels()` returns the configured window size (1200x800)
before the window exists and the live canvas size afterwards, which is what
lets the plot be built before the window.

**An explicit `--renderer gui` that cannot open** is still a fallback with a
warning, not an error — the user asked for the best available display, and
they get one.

**Window closed by the user** ends the session cleanly, the same as `q`.

**The tty check stays.** `cli.py` still refuses to start when stdout is not a
terminal, GUI mode included: the text half is half the interface, and a
graphics window with its prompts redirected to a pipe is not a usable tool.
`--dump` and `--cursor` remain the headless paths, unchanged.

**Teardown** stays idempotent and still runs from `try/finally`, `atexit` and
the signal handlers. In GUI mode it destroys the manager; there is no raw
mode, hidden cursor or mouse reporting to restore, so those steps no-op.

## Testing

Everything except the window itself is tested without a display.

**Pure units.** `key_from_mpl()` as a table. `Transcript.line()`/`prompt()`
against a `StringIO`, including that a prompt followed by a line terminates
cleanly and that consecutive prompts do not accumulate.

**Fake toolkit.** A duck-typed canvas/manager pair drives `GuiRenderer`
through `attach`, `poll`, `pump`, `set_title` and `teardown` with no display,
and asserts that `rcParams["toolbar"]` and the `keymap.*` entries are cleared.

**Session, end to end, no window.** A fake interactive renderer that yields a
scripted event list exercises the whole GUI loop: keys reach `dispatch_char`,
motion sets `view.cursor_x` without dirtying the frame, results land in the
transcript, and — the regression that matters — **no escape sequences are
written to `out`**, because in this mode the terminal is a plain transcript.

**Selection.** `choose_renderer` picks `gui` when `available()` is true and
skips to `halfblock` when it is not; `available()` is false with no `DISPLAY`
off Darwin, true with one, and honours `MPLBACKEND`.

**Fallback.** `attach()` raising `GuiUnavailable` leaves a working
`HalfblockRenderer` session and one stderr line.

**Real window.** One smoke test, `skipif(not gui.available())`: open, draw a
frame, set a title, close. Marked so CI without a display skips it.

**Regression.** The existing 365 tests must stay green, and `ruff` clean. The
half-block, chrome, cursor-mapping and `--dump` paths are untouched by design;
if any of their tests move, that is a signal the change leaked.

## Documentation

`README.md` gains a two-window section: what it looks like, why the terminal
scrolls instead of painting, the selection table above, and how to force
either mode. The key reference is unchanged — every binding means the same
thing in both modes, which is the point.
