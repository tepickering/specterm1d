# specterm1d GUI renderer (two-window mode) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give terminals with no inline-graphics protocol a real matplotlib
window driven the way `splot` was driven under `xgterm` — you point in the
graphics window and press a key, while prompts and results scroll in the text
terminal.

**Architecture:** A new `gui` backend joins the existing renderer registry and
adopts `SpectrumPlot`'s existing `Figure`, so there is still exactly one plot
model and one render path. The backend owns the window and its event loop and
exposes them as a queue of `Key` and `Motion` events; `Session` grows three
narrow branches (`run`, `render`, `message`) guarded by a single `interactive`
flag. The terminal half becomes a plain scrolling `Transcript` — no raw mode,
no pinned status line.

**Tech Stack:** Python 3.13, matplotlib (`backend_qtagg` / `backend_tkagg` /
`backend_macosx`, all Agg subclasses), numpy, pytest.

**Spec:** `claude_docs/specs/2026-08-25-specterm1d-gui-renderer-design.md`

## Global Constraints

- Python floor `>=3.13`; matplotlib floor `>=3.7`, numpy `>=2.5` — do not add a
  new runtime dependency, and do not import a toolkit at module import time.
- Out of scope, do not touch: `ViewState`, `keymap`, the command registry, the
  fitting code, the loaders, the log format. Half-block, kitty, iTerm2 and sixel
  behaviour is unchanged. `--dump` and `--cursor` are unchanged.
- Deferred, do not build: a `Frontend` protocol; click-to-mark during
  `AwaitCursor` (marking stays on the space bar, as in `splot`).
- Also deferred: persistent artists via `set_data` in `plot.render()`. It would
  help window mode, but it is a rewrite of `plot.py`'s hot path and belongs in
  its own change. `ax.clear()` stays.
- `ruff` clean at `line-length = 100`, rules `E,F,W,I,B,C4,SIM,RUF`. Never add
  `BLE001` or `S110` to the ignore list.
- The existing 365 tests must stay green. The half-block, chrome,
  cursor-mapping and `--dump` paths are untouched by design; if any of their
  tests need to move, stop and say so — that is a signal the change leaked.
- Renderer preference order, exactly: `("kitty", "iterm2", "sixel", "gui",
  "halfblock")`. Inline graphics still win where they exist.
- Default window size: 1200x800. There is no size flag — resizing is a window
  drag.

## Two deliberate readings of the spec

Both are small; if either is wrong, stop and ask before proceeding.

1. **`SpectrumPlot._draw` is named `draw` here.** The spec writes `_draw`, but
   `Session` has to call it across a module boundary, and a private call across
   modules reads as a mistake. Same signature, same semantics, public name.
2. **"No escape sequences are written to `out`" means no TUI control
   sequences.** `Transcript.prompt()` writes erase-to-EOL (`\x1b[K`) by the
   spec's own definition, so the assertion is scoped to the sequences that
   would mean a TUI is being painted: hide-cursor `\x1b[?25l`, clear-screen
   `\x1b[2J`, reverse-video `\x1b[7m`, and mouse reporting `\x1b[?1000`.

---

### Task 1: `Motion`, the protocol extension, and `key_from_mpl()`

The pure event vocabulary. Everything downstream speaks it.

**Files:**
- Modify: `specterm1d/term/base.py` (add `Motion`, `GuiEvent`, protocol members)
- Create: `specterm1d/term/gui.py`
- Test: `tests/test_gui.py`

**Interfaces:**
- Consumes: `specterm1d.term.input.Key`, an existing frozen dataclass with
  fields `name: str` and `char: str = ""`.
- Produces:
  - `specterm1d.term.base.Motion(x: float, y: float)`, a frozen dataclass.
  - `specterm1d.term.base.GuiEvent = Key | Motion`.
  - `specterm1d.term.gui.key_from_mpl(event_key: str | None) -> Key | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gui.py`:

```python
# tests/test_gui.py
import pytest

from specterm1d.term import gui
from specterm1d.term.base import Motion
from specterm1d.term.input import Key


# ---- key_from_mpl --------------------------------------------------

@pytest.mark.parametrize("event_key,expected", [
    ("left", Key("left")),
    ("right", Key("right")),
    ("up", Key("up")),
    ("down", Key("down")),
    ("shift+left", Key("shift-left")),
    ("shift+right", Key("shift-right")),
    ("shift+up", Key("shift-up")),
    ("shift+down", Key("shift-down")),
    ("escape", Key("escape")),
    ("enter", Key("enter")),
    ("return", Key("enter")),
    ("backspace", Key("backspace")),
    ("pageup", Key("pageup")),
    ("pagedown", Key("pagedown")),
    (" ", Key("char", " ")),
    ("k", Key("char", "k")),
    ("Z", Key("char", "Z")),
    (":", Key("char", ":")),
])
def test_key_from_mpl_maps_onto_the_existing_key_vocabulary(event_key, expected):
    assert gui.key_from_mpl(event_key) == expected


@pytest.mark.parametrize("event_key", [
    None, "", "ctrl+c", "f1", "alt+x", "shift+f1", "super",
])
def test_key_from_mpl_drops_what_the_keymap_has_no_meaning_for(event_key):
    assert gui.key_from_mpl(event_key) is None


def test_key_from_mpl_returns_a_real_key_so_dispatch_needs_no_translation():
    key = gui.key_from_mpl("k")
    assert isinstance(key, Key)
    assert str(key) == "k"


# ---- Motion --------------------------------------------------------

def test_motion_carries_data_coordinates_and_is_frozen():
    motion = Motion(5000.5, 1.25)
    assert (motion.x, motion.y) == (5000.5, 1.25)
    with pytest.raises(Exception):
        motion.x = 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_gui.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'specterm1d.term.gui'`

- [ ] **Step 3: Add `Motion` and the protocol members to `term/base.py`**

Append to the imports and after `CellRect` in `specterm1d/term/base.py`:

```python
from specterm1d.term.input import Key


@dataclass(frozen=True)
class Motion:
    """Pointer position in data coordinates.

    A matplotlib motion event carries ``event.xdata`` directly, so an
    interactive backend can report exactly where the pointer is rather than
    which terminal cell it landed in.
    """

    x: float
    y: float


# What an interactive backend's poll() yields. Key is the terminal's own key
# type, unchanged, which is what lets window keys reach Session.handle() with
# no translation layer.
GuiEvent = Key | Motion
```

Then extend the `Renderer` protocol in the same file:

```python
class Renderer(Protocol):
    name: str

    # True when the backend's pixels are too coarse for rendered text and the
    # terminal should paint the axis decoration as glyphs instead.
    text_chrome: bool = False

    # True when the backend owns its own window and event loop. The session
    # then takes keys from poll() rather than the terminal, prints text rather
    # than painting a status line, and never enters raw mode.
    interactive: bool = False

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        """Pixel (width, height) the figure should be rendered at."""
        ...

    def draw(self, rgba: np.ndarray, rect: CellRect) -> None:
        ...

    def teardown(self) -> None:
        ...

    # Interactive backends only. Callers reach these with getattr(..., default)
    # so no terminal backend has to grow them.

    closed: bool                                # the user closed the window

    def attach(self, plot) -> None:
        """Adopt the figure and open the window."""
        ...

    def poll(self) -> list[GuiEvent]:
        """Drain the queued window events."""
        ...

    def pump(self) -> None:
        """Let the toolkit run its event loop."""
        ...

    def set_title(self, text: str) -> None:
        ...
```

- [ ] **Step 4: Create `term/gui.py` with the key mapping**

```python
"""The GUI backend: a real matplotlib window for terminals with no inline
graphics protocol.

This is the ``xgterm`` model. The window owns interaction; the terminal is a
scrolling transcript. Nothing here imports a toolkit at module import time -
``open_window`` does that lazily, because importing a backend on a headless
box is exactly the case this module has to survive.
"""
from __future__ import annotations

from specterm1d.term.input import Key

_DIRECTIONS = ("left", "right", "up", "down")

# matplotlib's names on the left, the terminal's on the right. 'return' and
# 'enter' both arrive depending on the toolkit.
_NAMED = {
    "escape": "escape",
    "enter": "enter",
    "return": "enter",
    "backspace": "backspace",
    "pageup": "pageup",
    "pagedown": "pagedown",
}


def key_from_mpl(event_key: str | None) -> Key | None:
    """Map ``event.key`` onto the terminal's Key vocabulary.

    Pure, so the whole table is testable without a window. Returns None for
    anything the keymap has no meaning for - modified keys, function keys, and
    the None matplotlib reports when a keypress carries no character.
    """
    if not event_key:
        return None
    if event_key in _DIRECTIONS:
        return Key(event_key)
    if event_key.startswith("shift+"):
        rest = event_key[len("shift+"):]
        return Key(f"shift-{rest}") if rest in _DIRECTIONS else None
    if event_key in _NAMED:
        return Key(_NAMED[event_key])
    if len(event_key) == 1:
        return Key("char", event_key)
    return None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_gui.py -v`
Expected: PASS

- [ ] **Step 6: Check nothing regressed and lint**

Run: `pytest -q && ruff check .`
Expected: 365 existing tests plus the new ones pass; ruff reports no issues.

- [ ] **Step 7: Commit**

```bash
git add specterm1d/term/base.py specterm1d/term/gui.py tests/test_gui.py
git commit -m "feat: add the interactive-renderer vocabulary and mpl key mapping

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: `Transcript`

The terminal half of two-window mode. Pure and toolkit-free, so it tests
against a `StringIO`.

**Files:**
- Create: `specterm1d/transcript.py`
- Test: `tests/test_transcript.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `specterm1d.transcript.Transcript(out)` with
  `line(text: str) -> None` and `prompt(text: str) -> None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_transcript.py`:

```python
# tests/test_transcript.py
import io

from specterm1d.transcript import Transcript


def test_line_appends_a_finished_line():
    out = io.StringIO()
    Transcript(out).line("center = 5001.2")
    assert out.getvalue() == "center = 5001.2\n"


def test_consecutive_lines_scroll():
    out = io.StringIO()
    transcript = Transcript(out)
    transcript.line("one")
    transcript.line("two")
    assert out.getvalue() == "one\ntwo\n"


def test_prompt_redraws_in_place_and_does_not_end_the_line():
    out = io.StringIO()
    Transcript(out).prompt(": show")
    assert out.getvalue() == "\r: show\x1b[K"


def test_consecutive_prompts_do_not_accumulate_lines():
    # AwaitLine echoes on every keystroke. Without in-place redraw a
    # 30-character colon command would leave 30 lines of transcript.
    out = io.StringIO()
    transcript = Transcript(out)
    for text in (":", ":s", ":sh", ":sho", ":show"):
        transcript.prompt(text)
    assert out.getvalue().count("\n") == 0
    assert out.getvalue().endswith("\r:show\x1b[K")


def test_a_line_after_a_prompt_terminates_the_prompt_first():
    out = io.StringIO()
    transcript = Transcript(out)
    transcript.prompt(":show")
    transcript.line("no measurements recorded yet")
    assert out.getvalue() == "\r:show\x1b[K\nno measurements recorded yet\n"


def test_a_line_after_a_finished_line_does_not_add_a_blank():
    out = io.StringIO()
    transcript = Transcript(out)
    transcript.line("one")
    transcript.line("two")
    assert "\n\n" not in out.getvalue()


def test_output_is_flushed_so_prompts_appear_before_the_next_keystroke():
    class Recorder(io.StringIO):
        flushes = 0

        def flush(self):
            type(self).flushes += 1

    out = Recorder()
    transcript = Transcript(out)
    transcript.prompt("x")
    transcript.line("y")
    assert Recorder.flushes >= 2
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_transcript.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'specterm1d.transcript'`

- [ ] **Step 3: Write `specterm1d/transcript.py`**

```python
"""Scrolling text output for the terminal half of two-window mode.

Not a layout. In GUI mode the terminal is what it was under ``xgterm``: a
transcript that scrolls past while the graphics window holds the plot. Two
operations, because an in-progress prompt and a finished line behave
differently - the prompt is overwritten in place, the line is appended.
"""
from __future__ import annotations

ERASE_EOL = "\x1b[K"


class Transcript:
    def __init__(self, out):
        self.out = out
        self._open_prompt = False

    def line(self, text: str) -> None:
        """A finished line. Terminates any open prompt first."""
        if self._open_prompt:
            self.out.write("\n")
            self._open_prompt = False
        self.out.write(text + "\n")
        self.out.flush()

    def prompt(self, text: str) -> None:
        """Redraw an in-progress prompt in place, with no newline.

        AwaitLine echoes on every keystroke; without this a 30-character colon
        command would leave 30 lines of transcript. Erase-to-EOL covers the
        backspace case, where the new text is shorter than what it replaces.
        """
        self.out.write("\r" + text + ERASE_EOL)
        self.out.flush()
        self._open_prompt = True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_transcript.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Lint**

Run: `ruff check .`
Expected: no issues.

- [ ] **Step 6: Commit**

```bash
git add specterm1d/transcript.py tests/test_transcript.py
git commit -m "feat: add the scrolling transcript for the terminal half

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Split `SpectrumPlot.render()` so GUI mode skips the buffer copy

A GUI canvas paints as it draws, so the 3.8 MB RGBA copy is pure waste there.

**Files:**
- Modify: `specterm1d/plot.py:317-381` (the body of `render`)
- Test: `tests/test_plot.py` (append)

**Interfaces:**
- Consumes: `specterm1d.plot.PlotRequest` (existing).
- Produces: `SpectrumPlot.draw(req: PlotRequest) -> None` — everything up to
  and including `canvas.draw()`, no buffer copy. `SpectrumPlot.render(req) ->
  np.ndarray` keeps its exact existing behaviour and return value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_plot.py`:

```python
def test_draw_paints_the_canvas_without_copying_the_buffer():
    # GUI mode paints as it draws; the 3.8 MB copy render() makes is waste
    # there. draw() must still leave a real frame on the canvas.
    from specterm1d.plot import SpectrumPlot
    from specterm1d.spec import build_spec
    from specterm1d.view import ViewState
    from specterm1d.spec import SpecCollection, SpecEntry

    spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 3.0))
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x.fits")
    view = ViewState(coll)
    view.reset_limits()

    plot = SpectrumPlot(200, 120)
    assert plot.draw(view.to_request(title="t")) is None
    buf = np.asarray(plot.fig.canvas.buffer_rgba())
    assert buf.shape == (120, 200, 4)
    assert buf[..., :3].any()


def test_render_still_returns_an_independent_copy_of_the_frame():
    from specterm1d.plot import SpectrumPlot
    from specterm1d.spec import SpecCollection, SpecEntry, build_spec
    from specterm1d.view import ViewState

    spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 3.0))
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x.fits")
    view = ViewState(coll)
    view.reset_limits()

    plot = SpectrumPlot(200, 120)
    first = plot.render(view.to_request(title="t"))
    before = first.copy()
    view.xlim = (5200.0, 5800.0)
    plot.render(view.to_request(title="t2"))
    assert np.array_equal(first, before)     # not a view onto the canvas
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_plot.py -k "draw_paints or independent_copy" -v`
Expected: FAIL — `AttributeError: 'SpectrumPlot' object has no attribute 'draw'`
(the second test passes already; it is the regression guard for the split)

- [ ] **Step 3: Split the method**

In `specterm1d/plot.py`, rename `render` to `draw`, change its signature to
return `None`, delete the trailing `return np.array(...)`, and add a new
`render` beneath it. The final lines of the file become:

```python
        self.fig.canvas.draw()

    def render(self, req: PlotRequest) -> np.ndarray:
        """Draw, then hand back an independent copy of the frame.

        A copy, not a view: buffer_rgba() aliases the renderer's own memory,
        so any frame a caller is still holding would mutate on the next
        render. The halfblock backend diffs against the previous frame.
        """
        self.draw(req)
        return np.array(self.fig.canvas.buffer_rgba(), dtype=np.uint8)
```

and the method that was `render` is now:

```python
    def draw(self, req: PlotRequest) -> None:
        """Paint one frame onto the canvas. No buffer copy.

        Split out of render() because a GUI canvas is on screen the moment it
        is drawn, so copying 3.8 MB of RGBA out of it every frame buys nothing.
        """
        ax = self.ax
        ax.clear()
        ...unchanged through...
        self.fig.canvas.draw()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_plot.py -v`
Expected: PASS — every existing plot test plus the two new ones.

- [ ] **Step 5: Confirm nothing else called the old name**

Run: `grep -rn "\.render(" specterm1d/ tests/ | grep -v "renderer"`
Expected: only `SpectrumPlot.render` call sites (`session.render_rgba`,
`session.render`) and tests — all of which still want the copying version.

- [ ] **Step 6: Full suite and lint**

Run: `pytest -q && ruff check .`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add specterm1d/plot.py tests/test_plot.py
git commit -m "refactor: split SpectrumPlot.draw out of render

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Backend probing — `available()` and `open_window()`

Two layers, and the distinction matters: importing `backend_tkagg` succeeds on
a headless Linux box with no `DISPLAY`; only `Tk()` fails. `available()` is a
cheap predicate for renderer selection and never opens a window;
`open_window()` is the real answer.

**Files:**
- Modify: `specterm1d/term/gui.py`
- Test: `tests/test_gui.py` (append)

**Interfaces:**
- Consumes: `key_from_mpl` from Task 1 (same module).
- Produces:
  - `gui.GUI_BACKENDS = ("qtagg", "tkagg", "macosx")`
  - `gui.DEFAULT_SIZE = (1200, 800)`
  - `gui.GuiUnavailable(RuntimeError)`
  - `gui.available(env: dict | None = None, platform: str | None = None) -> bool`
  - `gui.backends_for(env: dict | None = None) -> tuple[str, ...]`
  - `gui.open_window(fig, size: tuple[int, int], backends=None) -> tuple[canvas, manager, str]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gui.py`:

```python
# ---- backend probing -----------------------------------------------

@pytest.fixture
def clean_rcparams():
    """open_window mutates global rcParams on purpose; put them back."""
    from matplotlib import rcParams
    saved = {k: rcParams[k] for k in list(rcParams)
             if k == "toolbar" or k.startswith("keymap.")}
    yield rcParams
    rcParams.update(saved)


def test_available_is_true_on_darwin_with_no_display():
    assert gui.available(env={}, platform="darwin") is True


def test_available_is_false_over_ssh_with_no_display():
    # The case the fallback exists for: X11 forwarding off, tmux over ssh.
    assert gui.available(env={}, platform="linux") is False


def test_available_is_true_with_an_x11_display():
    assert gui.available(env={"DISPLAY": ":0"}, platform="linux") is True


def test_available_is_true_under_wayland():
    assert gui.available(env={"WAYLAND_DISPLAY": "wayland-0"},
                         platform="linux") is True


def test_available_honours_mplbackend_when_it_names_a_gui_backend():
    assert gui.available(env={"MPLBACKEND": "TkAgg"}, platform="linux") is True


def test_available_honours_mplbackend_when_it_names_a_headless_backend():
    assert gui.available(env={"MPLBACKEND": "Agg", "DISPLAY": ":0"},
                         platform="linux") is False


def test_backends_for_tries_every_toolkit_by_default():
    assert gui.backends_for(env={}) == gui.GUI_BACKENDS


def test_backends_for_tries_only_the_one_mplbackend_names():
    assert gui.backends_for(env={"MPLBACKEND": "TkAgg"}) == ("tkagg",)


def test_open_window_raises_gui_unavailable_and_names_the_reason(clean_rcparams):
    from specterm1d.plot import SpectrumPlot

    with pytest.raises(gui.GuiUnavailable) as excinfo:
        gui.open_window(SpectrumPlot(100, 100).fig, (100, 100),
                        backends=("nosuch",))
    assert "nosuch" in str(excinfo.value)


def test_open_window_disables_the_toolbar_and_matplotlibs_own_keymap(clean_rcparams):
    # matplotlib binds s/p/o/q/k/l/g/f. All eight collide with splot, and q
    # would quit the window out from under the session. The toolbar is worse:
    # it drives ax limits behind ViewState's back.
    from specterm1d.plot import SpectrumPlot

    clean_rcparams["toolbar"] = "toolbar2"
    clean_rcparams["keymap.save"] = ["s"]
    clean_rcparams["keymap.quit"] = ["q"]
    with pytest.raises(gui.GuiUnavailable):
        gui.open_window(SpectrumPlot(100, 100).fig, (100, 100),
                        backends=("nosuch",))
    assert clean_rcparams["toolbar"] == "none"
    assert clean_rcparams["keymap.save"] == []
    assert clean_rcparams["keymap.quit"] == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_gui.py -k "available or backends_for or open_window" -v`
Expected: FAIL — `AttributeError: module 'specterm1d.term.gui' has no attribute 'available'`

- [ ] **Step 3: Implement probing in `term/gui.py`**

Add these imports at the top of `specterm1d/term/gui.py`:

```python
import importlib
import os
import sys
```

and append to the module:

```python
GUI_BACKENDS = ("qtagg", "tkagg", "macosx")
DEFAULT_SIZE = (1200, 800)

# Spelled out rather than looked up through matplotlib's backend registry,
# which only exists from 3.9 and whose shape has moved between releases.
_BACKEND_MODULES = {
    "qtagg": ("matplotlib.backends.backend_qtagg", "FigureCanvasQTAgg"),
    "tkagg": ("matplotlib.backends.backend_tkagg", "FigureCanvasTkAgg"),
    "macosx": ("matplotlib.backends.backend_macosx", "FigureCanvasMac"),
}


class GuiUnavailable(RuntimeError):
    """No usable GUI backend, or the window could not be created."""


def available(env: dict | None = None, platform: str | None = None) -> bool:
    """Is a graphics window worth trying? Never opens one.

    A predicate, not a guarantee - the real answer comes from open_window()
    raising. The two layers matter because importing backend_tkagg succeeds on
    a headless box with no DISPLAY; only Tk() fails.
    """
    env = os.environ if env is None else env
    platform = sys.platform if platform is None else platform

    forced = env.get("MPLBACKEND")
    if forced:
        return forced.lower() in GUI_BACKENDS
    if platform == "darwin":
        return True
    return bool(env.get("DISPLAY") or env.get("WAYLAND_DISPLAY"))


def backends_for(env: dict | None = None) -> tuple[str, ...]:
    """Which toolkits to try, in order. MPLBACKEND narrows it to one."""
    env = os.environ if env is None else env
    forced = env.get("MPLBACKEND")
    return (forced.lower(),) if forced else GUI_BACKENDS


def _quiet_rcparams() -> None:
    """Stop matplotlib competing for the window.

    The toolbar would drive ax limits behind ViewState's back, desyncing the
    status readout; ViewState stays the single source of truth for the view.
    The default keymap binds s/p/o/q/k/l/g/f, all eight of which collide with
    splot, and q would quit the window out from under the session.
    """
    from matplotlib import rcParams

    rcParams["toolbar"] = "none"
    for name in list(rcParams):
        if name.startswith("keymap."):
            rcParams[name] = []


def open_window(fig, size: tuple[int, int], backends=None):
    """Open a window showing ``fig``. Returns (canvas, manager, backend name).

    Raises GuiUnavailable, naming every backend it tried and why each failed.
    """
    width, height = size
    names = tuple(backends) if backends is not None else backends_for()
    _quiet_rcparams()

    dpi = fig.get_dpi()
    fig.set_size_inches(width / dpi, height / dpi, forward=True)

    reasons = []
    for name in names:
        entry = _BACKEND_MODULES.get(name)
        if entry is None:
            reasons.append(f"{name}: not a known GUI backend")
            continue
        module_name, class_name = entry
        try:
            module = importlib.import_module(module_name)
            canvas_cls = getattr(module, class_name)
            manager = canvas_cls.new_manager(fig, 1)
            manager.show()
        except Exception as exc:
            reasons.append(f"{name}: {exc}")
            continue
        return manager.canvas, manager, name

    raise GuiUnavailable("; ".join(reasons) or "no GUI backend to try")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_gui.py -v`
Expected: PASS (all Task 1 tests plus 10 new ones)

- [ ] **Step 5: Full suite and lint**

Run: `pytest -q && ruff check .`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add specterm1d/term/gui.py tests/test_gui.py
git commit -m "feat: probe for a usable matplotlib GUI backend

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: `GuiRenderer`

The backend itself: adopts the figure, queues window events, pumps the toolkit.

**Files:**
- Modify: `specterm1d/term/gui.py`
- Test: `tests/test_gui.py` (append)

**Interfaces:**
- Consumes: `key_from_mpl`, `open_window`, `GuiUnavailable`, `DEFAULT_SIZE`
  from Tasks 1 and 4; `Motion` from `specterm1d.term.base`.
- Produces: `gui.GuiRenderer` with

  ```python
  name = "gui"; text_chrome = False; interactive = True
  def __init__(self, size: tuple[int, int] = DEFAULT_SIZE, open_fn=open_window)
  closed: bool
  def target_pixels(self, rows: int, cols: int) -> tuple[int, int]
  def attach(self, plot) -> None            # raises GuiUnavailable
  def poll(self) -> list[GuiEvent]
  def pump(self) -> None
  def set_title(self, text: str) -> None
  def take_resized(self) -> bool
  def draw(self, rgba, rect) -> None        # no-op
  def teardown(self) -> None
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gui.py`:

```python
# ---- GuiRenderer against a fake toolkit ----------------------------

class FakeCanvas:
    def __init__(self, size=(640, 480)):
        self.callbacks = {}
        self.flushed = 0
        self._size = size

    def mpl_connect(self, name, func):
        self.callbacks[name] = func
        return len(self.callbacks)

    def flush_events(self):
        self.flushed += 1

    def get_width_height(self):
        return self._size


class FakeManager:
    def __init__(self, canvas):
        self.canvas = canvas
        self.title = None
        self.destroyed = False

    def set_window_title(self, text):
        self.title = text

    def destroy(self):
        self.destroyed = True


class FakeEvent:
    def __init__(self, key=None, inaxes=None, xdata=None, ydata=None):
        self.key = key
        self.inaxes = inaxes
        self.xdata = xdata
        self.ydata = ydata


def fake_open(fig, size, backends=None):
    canvas = FakeCanvas()
    return canvas, FakeManager(canvas), "fake"


def attached_renderer(size=(400, 300)):
    from specterm1d.plot import SpectrumPlot

    plot = SpectrumPlot(*size)
    renderer = gui.GuiRenderer(size=size, open_fn=fake_open)
    renderer.attach(plot)
    return renderer, plot


def test_gui_renderer_advertises_itself_as_interactive():
    renderer = gui.GuiRenderer(open_fn=fake_open)
    assert renderer.name == "gui"
    assert renderer.interactive is True
    assert renderer.text_chrome is False
    assert renderer.closed is False


def test_target_pixels_is_the_configured_size_before_the_window_exists():
    # cli.py builds the plot before attaching, so this has to answer early.
    renderer = gui.GuiRenderer(size=(1200, 800), open_fn=fake_open)
    assert renderer.target_pixels(40, 100) == (1200, 800)


def test_target_pixels_follows_the_live_canvas_once_attached():
    renderer, _ = attached_renderer()
    assert renderer.target_pixels(40, 100) == (640, 480)


def test_attach_adopts_the_existing_figure():
    renderer, plot = attached_renderer()
    assert renderer.plot is plot


def test_attach_subscribes_to_every_event_the_session_needs():
    renderer, _ = attached_renderer()
    assert set(renderer.canvas.callbacks) == {
        "key_press_event", "motion_notify_event", "button_press_event",
        "close_event", "resize_event",
    }


def test_key_presses_queue_as_terminal_keys():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["key_press_event"](FakeEvent(key="k"))
    assert renderer.poll() == [Key("char", "k")]


def test_unmapped_key_presses_are_dropped_rather_than_queued():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["key_press_event"](FakeEvent(key="ctrl+c"))
    assert renderer.poll() == []


def test_poll_drains_the_queue():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["key_press_event"](FakeEvent(key="a"))
    assert len(renderer.poll()) == 1
    assert renderer.poll() == []


def test_motion_inside_the_axes_queues_data_coordinates():
    renderer, plot = attached_renderer()
    renderer.canvas.callbacks["motion_notify_event"](
        FakeEvent(inaxes=plot.ax, xdata=5000.5, ydata=1.25))
    assert renderer.poll() == [Motion(5000.5, 1.25)]


def test_motion_outside_the_axes_is_ignored():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["motion_notify_event"](
        FakeEvent(inaxes=None, xdata=None, ydata=None))
    assert renderer.poll() == []


def test_a_click_places_the_cursor_the_same_way_motion_does():
    renderer, plot = attached_renderer()
    renderer.canvas.callbacks["button_press_event"](
        FakeEvent(inaxes=plot.ax, xdata=5100.0, ydata=2.0))
    assert renderer.poll() == [Motion(5100.0, 2.0)]


def test_closing_the_window_sets_closed():
    renderer, _ = attached_renderer()
    renderer.canvas.callbacks["close_event"](FakeEvent())
    assert renderer.closed is True


def test_a_resize_is_reported_once_and_then_cleared():
    renderer, _ = attached_renderer()
    assert renderer.take_resized() is False
    renderer.canvas.callbacks["resize_event"](FakeEvent())
    assert renderer.take_resized() is True
    assert renderer.take_resized() is False


def test_pump_runs_the_toolkits_event_loop():
    renderer, _ = attached_renderer()
    renderer.pump()
    renderer.pump()
    assert renderer.canvas.flushed == 2


def test_set_title_carries_the_readout_to_the_window():
    renderer, _ = attached_renderer()
    renderer.set_title("x=5000  y=1.2")
    assert renderer.manager.title == "x=5000  y=1.2"


def test_draw_is_a_no_op_because_the_canvas_is_already_on_screen():
    import numpy as np

    from specterm1d.term.base import CellRect

    renderer, _ = attached_renderer()
    assert renderer.draw(np.zeros((4, 4, 4), dtype=np.uint8),
                         CellRect(0, 0, 2, 4)) is None


def test_teardown_destroys_the_window_and_is_idempotent():
    renderer, _ = attached_renderer()
    manager = renderer.manager
    renderer.teardown()
    renderer.teardown()
    assert manager.destroyed is True


def test_teardown_before_attach_does_not_raise():
    gui.GuiRenderer(open_fn=fake_open).teardown()


def test_pump_and_set_title_before_attach_do_not_raise():
    renderer = gui.GuiRenderer(open_fn=fake_open)
    renderer.pump()
    renderer.set_title("x")


def test_attach_propagates_gui_unavailable_so_cli_can_fall_back():
    from specterm1d.plot import SpectrumPlot

    def refuse(fig, size, backends=None):
        raise gui.GuiUnavailable("tkagg: no display name and no $DISPLAY")

    renderer = gui.GuiRenderer(open_fn=refuse)
    with pytest.raises(gui.GuiUnavailable):
        renderer.attach(SpectrumPlot(100, 100))


# ---- one real window, skipped where there is no display ------------

@pytest.mark.skipif(not gui.available(), reason="no GUI display available")
def test_a_real_window_opens_draws_a_frame_and_closes(clean_rcparams):
    import numpy as np

    from specterm1d.plot import SpectrumPlot
    from specterm1d.spec import SpecCollection, SpecEntry, build_spec
    from specterm1d.view import ViewState

    plot = SpectrumPlot(400, 300)
    renderer = gui.GuiRenderer(size=(400, 300))
    try:
        renderer.attach(plot)
    except gui.GuiUnavailable as exc:
        pytest.skip(str(exc))
    try:
        spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 3.0))
        coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")],
                              path="x.fits")
        view = ViewState(coll)
        view.reset_limits()
        plot.draw(view.to_request(title="smoke"))
        renderer.pump()
        renderer.set_title("x=5000")
        assert renderer.target_pixels(40, 100)[0] > 0
        assert renderer.closed is False
    finally:
        renderer.teardown()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_gui.py -k GuiRenderer -v`
Expected: FAIL — `AttributeError: module 'specterm1d.term.gui' has no attribute 'GuiRenderer'`

- [ ] **Step 3: Implement `GuiRenderer`**

Add `import contextlib` to the top of `specterm1d/term/gui.py`, add
`from specterm1d.term.base import Motion` beside the `Key` import, and append:

```python
class GuiRenderer:
    """A real matplotlib window that adopts SpectrumPlot's figure.

    Callbacks append to a list and return; the list is drained by poll() from
    the session loop. They fire inside pump(), so there is no reentrancy and
    no thread - the queue exists to keep dispatch out of the toolkit's stack.
    """

    name = "gui"
    text_chrome = False
    interactive = True

    def __init__(self, size: tuple[int, int] = DEFAULT_SIZE, open_fn=open_window):
        self.size = size
        self._open = open_fn
        self.plot = None
        self.canvas = None
        self.manager = None
        self.backend = None
        self.closed = False
        self.resized = False
        self._events: list = []

    # ---- renderer protocol ------------------------------------------

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        """The configured size before the window exists, the live one after.

        cli.py builds the plot before attaching, so this has to answer before
        there is a canvas to ask.
        """
        if self.canvas is None:
            return self.size
        width, height = self.canvas.get_width_height()
        return (int(width), int(height))

    def draw(self, rgba, rect) -> None:
        """No-op: a GUI canvas is on screen the moment it is drawn."""

    def teardown(self) -> None:
        manager, self.manager = self.manager, None
        self.canvas = None
        if manager is not None:
            with contextlib.suppress(Exception):
                manager.destroy()

    # ---- interactive protocol ---------------------------------------

    def attach(self, plot) -> None:
        self.plot = plot
        self.canvas, self.manager, self.backend = self._open(plot.fig, self.size)
        connect = self.canvas.mpl_connect
        connect("key_press_event", self._on_key)
        connect("motion_notify_event", self._on_motion)
        connect("button_press_event", self._on_motion)
        connect("close_event", self._on_close)
        connect("resize_event", self._on_resize)

    def poll(self) -> list:
        events, self._events = self._events, []
        return events

    def pump(self) -> None:
        if self.canvas is not None:
            self.canvas.flush_events()

    def set_title(self, text: str) -> None:
        if self.manager is not None:
            self.manager.set_window_title(text)

    def take_resized(self) -> bool:
        """True once after each window resize, so the session can redraw."""
        was, self.resized = self.resized, False
        return was

    # ---- toolkit callbacks ------------------------------------------

    def _on_key(self, event) -> None:
        key = key_from_mpl(event.key)
        if key is not None:
            self._events.append(key)

    def _on_motion(self, event) -> None:
        if self.plot is None or event.inaxes is not self.plot.ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        self._events.append(Motion(float(event.xdata), float(event.ydata)))

    def _on_close(self, _event) -> None:
        self.closed = True

    def _on_resize(self, _event) -> None:
        self.resized = True
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_gui.py -v`
Expected: PASS. On a machine with a display the real-window test runs; without
one it is skipped.

- [ ] **Step 5: Full suite and lint**

Run: `pytest -q && ruff check .`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add specterm1d/term/gui.py tests/test_gui.py
git commit -m "feat: add the GuiRenderer backend

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: The three `Session` branches

Window loop, window render, transcript output. Guarded by one flag.

**Files:**
- Modify: `specterm1d/session.py` (`__init__`, `render`, `message`,
  `await_line`, `_handle_pending`, `_close_text_page`, `on_resize`, `run`,
  `teardown`; new `echo`, `on_motion`, `_run_gui`)
- Test: `tests/test_gui_session.py`

**Interfaces:**
- Consumes: `specterm1d.transcript.Transcript` (Task 2);
  `specterm1d.term.base.Motion` (Task 1); `SpectrumPlot.draw` (Task 3); the
  interactive renderer surface from Task 5 (`interactive`, `closed`, `attach`,
  `poll`, `pump`, `set_title`, `take_resized`).
- Produces:
  - `Session.interactive: bool`
  - `Session.transcript: Transcript`
  - `Session.echo(text: str) -> None` — in-place prompt echo
  - `Session.on_motion(x: float, y: float) -> None`
  - `specterm1d.session.POLL_INTERVAL = 0.01`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gui_session.py`:

```python
# tests/test_gui_session.py
import io

import numpy as np
import pytest

from specterm1d.plot import SpectrumPlot
from specterm1d.session import Session
from specterm1d.spec import SpecCollection, SpecEntry, build_spec
from specterm1d.term.base import Motion
from specterm1d.term.caps import TerminalCaps
from specterm1d.term.input import Key

# The sequences that would mean a TUI is being painted. Erase-to-EOL is not
# among them: Transcript.prompt() writes it to redraw a prompt in place.
TUI_SEQUENCES = ("\x1b[?25l", "\x1b[2J", "\x1b[7m", "\x1b[?1000")


class FakeGui:
    """An interactive renderer with a scripted event stream and no window."""

    name = "gui"
    text_chrome = False
    interactive = True

    def __init__(self, script=()):
        self.script = [list(batch) for batch in script]
        self.closed = False
        self.titles = []
        self.draws = 0
        self.pumps = 0
        self.plot = None
        self.torn_down = False

    def target_pixels(self, rows, cols):
        return (400, 300)

    def attach(self, plot):
        self.plot = plot

    def pump(self):
        self.pumps += 1

    def poll(self):
        if not self.script:
            self.closed = True
            return []
        return self.script.pop(0)

    def take_resized(self):
        return False

    def set_title(self, text):
        self.titles.append(text)

    def draw(self, rgba, rect):
        self.draws += 1

    def teardown(self):
        self.torn_down = True


def make_gui_session(script=(), n_entries=3):
    entries = []
    for i in range(n_entries):
        spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, i + 1.0))
        entries.append(SpecEntry(f"OBJ{i:03d}", {"OPT/COUNTS": spec}, "OPT/COUNTS"))
    coll = SpecCollection(entries=entries, path="/tmp/test.fits")
    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=24, cols=80, pixel_width=None, pixel_height=None,
                        is_tty=True)
    out = io.StringIO()
    renderer = FakeGui(script)
    plot = SpectrumPlot(400, 300)
    renderer.attach(plot)
    session = Session(coll, renderer, plot, out, caps)
    session.view.reset_limits()
    return session, renderer, out


@pytest.fixture(autouse=True)
def instant_poll(monkeypatch):
    """The loop sleeps POLL_INTERVAL per turn; tests should not."""
    monkeypatch.setattr("specterm1d.session.POLL_INTERVAL", 0.0)


# ---- mode detection ------------------------------------------------

def test_session_notices_an_interactive_renderer():
    session, _, _ = make_gui_session()
    assert session.interactive is True


def test_session_stays_non_interactive_for_terminal_renderers():
    from specterm1d.term.halfblock import HalfblockRenderer

    out = io.StringIO()
    spec = build_spec(np.linspace(5000.0, 6000.0, 200), np.full(200, 1.0))
    coll = SpecCollection(entries=[SpecEntry("A", {"F": spec}, "F")], path="x")
    caps = TerminalCaps(False, False, False, True, 24, 80, None, None, True)
    session = Session(coll, HalfblockRenderer(out=out), SpectrumPlot(80, 44),
                      out, caps)
    assert session.interactive is False


# ---- pointer -------------------------------------------------------

def test_on_motion_sets_the_cursor_from_data_coordinates():
    session, _, _ = make_gui_session()
    session.on_motion(5432.1, 2.5)
    assert session.view.cursor_x == pytest.approx(5432.1)
    assert session.view.cursor_y == pytest.approx(2.5)


def test_motion_does_not_redraw(monkeypatch):
    # 182 ms a frame at 1200x800; tracking the pointer through a full render
    # is not possible. Motion must never reach plot.draw().
    session, _, _ = make_gui_session()
    calls = []
    monkeypatch.setattr(session.plot, "draw", lambda req: calls.append(req))
    session.on_motion(5100.0, 1.0)
    session.on_motion(5200.0, 1.5)
    assert calls == []


# ---- output --------------------------------------------------------

def test_messages_scroll_past_in_the_transcript():
    session, _, out = make_gui_session()
    session.message("center = 5001.2")
    assert "center = 5001.2\n" in out.getvalue()


def test_an_empty_message_does_not_print_a_blank_line():
    session, _, out = make_gui_session()
    session.message("")
    assert out.getvalue() == ""


def test_prompt_echo_is_redrawn_in_place_not_appended():
    session, _, out = make_gui_session()
    session.echo(": s")
    session.echo(": sh")
    assert out.getvalue().count("\n") == 0


def test_await_line_echoes_over_itself_rather_than_scrolling():
    session, _, out = make_gui_session()
    session.await_line(": ", lambda s, text: None)
    for char in "show":
        session.handle(Key("char", char))
    assert out.getvalue().count("\n") == 0
    assert out.getvalue().endswith(": show\x1b[K")


def test_help_scrolls_past_instead_of_paging():
    session, _, out = make_gui_session()
    session.showing_help = True
    session.render()
    assert session.showing_help is False
    assert out.getvalue().count("\n") > 5


def test_the_measurement_log_scrolls_past_instead_of_paging():
    session, _, out = make_gui_session()
    session.showing_log = True
    session.render()
    assert session.showing_log is False
    assert "no measurements recorded yet" in out.getvalue()


# ---- the loop ------------------------------------------------------

def test_run_dispatches_window_keys_and_exits_when_the_window_closes():
    session, renderer, _ = make_gui_session(
        script=[[Key("char", "n")], [Key("right")]])
    start_index = session.view.index
    session.run()
    assert session.view.index != start_index
    assert renderer.closed is True
    assert session.finished is True


def test_run_puts_the_readout_in_the_window_title():
    session, renderer, _ = make_gui_session(script=[[Key("right")]])
    session.run()
    assert any("pix=" in title for title in renderer.titles)


def test_run_routes_motion_to_the_cursor_and_keys_to_dispatch():
    session, _, _ = make_gui_session(
        script=[[Motion(5500.0, 3.0)], [Key("char", "n")]])
    start_index = session.view.index
    session.run()
    assert session.view.cursor_x == pytest.approx(5500.0)
    assert session.view.index != start_index


def test_run_exits_on_q_as_well_as_on_a_closed_window():
    session, _, _ = make_gui_session(script=[[Key("char", "q")]] + [[]] * 5)
    session.run()
    assert session.finished is True


def test_run_never_paints_a_tui():
    # The regression that matters: in two-window mode the terminal is a plain
    # scrolling transcript, so none of the screen-control sequences appear.
    session, _, out = make_gui_session(
        script=[[Key("char", "n")], [Motion(5500.0, 3.0)]])
    session.run()
    text = out.getvalue()
    for sequence in TUI_SEQUENCES:
        assert sequence not in text


def test_teardown_writes_no_terminal_restoration_in_gui_mode():
    session, renderer, out = make_gui_session()
    session.teardown()
    assert renderer.torn_down is True
    for sequence in TUI_SEQUENCES:
        assert sequence not in out.getvalue()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_gui_session.py -v`
Expected: FAIL — `AttributeError: 'Session' object has no attribute 'interactive'`

- [ ] **Step 3: Wire the flag, the transcript and the pointer into `Session`**

In `specterm1d/session.py`, add `import time` to the imports and

```python
from specterm1d.term.base import CellRect, Motion
from specterm1d.transcript import Transcript
```

Add below `CURSOR_STEP_FAST`:

```python
# The GUI loop polls rather than blocking on a file descriptor, so it must
# poll faster than a person types. pump() on an idle window is microseconds.
POLL_INTERVAL = 0.01
```

In `__init__`, after the `self.text_chrome = ...` block:

```python
        # An interactive backend owns its own window and event loop: keys come
        # from poll(), text scrolls in the terminal, and raw mode never starts.
        self.interactive = bool(getattr(renderer, "interactive", False))
        # Built in both modes so nothing branches on its existence; the
        # terminal path simply never uses it.
        self.transcript = Transcript(self.out)
```

Add `on_motion` beside `on_mouse`:

```python
    def on_motion(self, x: float, y: float) -> None:
        """Pointer position from the graphics window, already in data units.

        No ax.get_position() arithmetic and no cell quantization - a
        matplotlib motion event carries event.xdata directly. Must not
        trigger a render: at 1200x800 a frame costs 182 ms.
        """
        self.view.cursor_x = float(x)
        self.view.cursor_y = float(y)
```

- [ ] **Step 4: Route output through the transcript**

Replace `message` and add `echo`:

```python
    def message(self, text: str) -> None:
        self.last_message = text
        if self.interactive and text:
            self.transcript.line(text)

    def echo(self, text: str) -> None:
        """An in-progress prompt: overwritten in place, not appended."""
        self.last_message = text
        if self.interactive:
            self.transcript.prompt(text)
```

In `await_line`, change `self.message(prompt)` to `self.echo(prompt)`.
In `_handle_pending`'s `AwaitLine` branch, change both
`self.message(state.prompt + state.buffer)` calls to
`self.echo(state.prompt + state.buffer)`.

- [ ] **Step 5: Branch `render` and guard the teardown paths**

Replace the head of `render`:

```python
    def render(self) -> None:
        if self.showing_help or self.showing_log:
            if self.interactive:
                # No paging in two-window mode: the key reference and the
                # measurement log scroll past, as they did in splot.
                for line in self._text_page_lines():
                    self.transcript.line(line)
                self.showing_help = self.showing_log = False
                self.page_index = 0
                return
            self._write_text_page()
            return
        if self.interactive:
            # No CellRect, no text chrome, no footer, and no plot.resize():
            # the window drives the figure size, not the other way round.
            self.plot.draw(self.view.to_request(title=self.title()))
            return
        layout = self.chrome_layout() if self.text_chrome else None
        ...unchanged from here...
```

In `_close_text_page`, guard the repaint so it cannot destroy the window:

```python
        if not self.interactive:
            self.renderer.teardown()     # the plot must repaint in full
```

In `on_resize`, carry the new `gui` capability field through unchanged when it
lands in Task 7 — for now leave `on_resize` alone.

In `teardown`, guard the terminal restoration:

```python
    def teardown(self) -> None:
        if self._torn_down:
            return
        self._torn_down = True
        with contextlib.suppress(Exception):
            self.renderer.teardown()
        if self.interactive:
            # No raw mode, no hidden cursor and no mouse reporting to restore.
            return
        try:
            if self.mouse_enabled:
                self.out.write(MOUSE_OFF)
        except Exception:
            pass
        try:
            self.out.write(SHOW_CURSOR + "\x1b[0m\n")
            self.out.flush()
        except Exception:
            pass
```

- [ ] **Step 6: Add the window loop**

Add `_run_gui` above `run`:

```python
    def _run_gui(self) -> None:
        """The two-window loop: the window owns interaction, we own state.

        Render on state change only. Session.run()'s terminal loop redraws
        unconditionally every 0.25 s; at 182 ms a frame in a 1200x800 window
        that is most of a core spent redrawing an unchanged plot, and it makes
        pointer tracking impossible.
        """
        self.render()
        running, dirty = True, False
        while running and not self.renderer.closed:
            self.renderer.pump()
            for event in self.renderer.poll():
                if isinstance(event, Motion):
                    self.on_motion(event.x, event.y)
                    continue
                running = self.handle(event)
                dirty = True
                if not running:
                    break
            if self.renderer.take_resized():
                dirty = True
            if running and dirty:
                self.render()
                dirty = False
            self.renderer.set_title(self.status_line())
            time.sleep(POLL_INTERVAL)
        self.finished = True
```

and branch `run`:

```python
        try:
            if self.interactive:
                self._run_gui()
                return
            self.out.write(HIDE_CURSOR + CLEAR_SCREEN)
            ...unchanged...
        finally:
            self.teardown()
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `pytest tests/test_gui_session.py -v`
Expected: PASS

- [ ] **Step 8: Confirm the terminal path is untouched**

Run: `pytest tests/test_session.py tests/test_text_chrome.py tests/test_halfblock.py tests/test_mouse.py tests/test_cursorscript.py -q`
Expected: all pass with no changes to those files. If any needs editing, stop —
the change has leaked into the terminal path.

- [ ] **Step 9: Full suite and lint**

Run: `pytest -q && ruff check .`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add specterm1d/session.py tests/test_gui_session.py
git commit -m "feat: drive the session from a graphics window

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Renderer selection, `--gui`, and the fallback

Make `gui` the default where no inline protocol exists, and make a window that
will not open a warning rather than an error.

**Files:**
- Modify: `specterm1d/term/caps.py` (`PREFERENCE`, `TerminalCaps.gui`, `detect`)
- Modify: `specterm1d/term/__init__.py` (register the factory)
- Modify: `specterm1d/session.py` (`on_resize` carries `gui` through)
- Modify: `specterm1d/cli.py` (`RENDERERS`, `--gui`, attach-then-construct)
- Test: `tests/test_caps.py` (append), `tests/test_gui_session.py` (append)

**Interfaces:**
- Consumes: `gui.GuiRenderer`, `gui.available`, `gui.GuiUnavailable` (Tasks 4-5).
- Produces:
  - `TerminalCaps.gui: bool = False`
  - `caps.PREFERENCE == ("kitty", "iterm2", "sixel", "gui", "halfblock")`
  - `cli.RENDERERS == ("kitty", "iterm2", "sixel", "gui", "halfblock")`
  - a `--gui` flag equivalent to `--renderer gui`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_caps.py`:

```python
def test_preference_puts_the_window_above_halfblock_and_below_inline():
    from specterm1d.term.caps import PREFERENCE
    assert PREFERENCE == ("kitty", "iterm2", "sixel", "gui", "halfblock")


def test_a_terminal_with_no_inline_protocol_gets_a_window():
    import specterm1d.term  # noqa: F401  - registers the factories
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, out=None).name == "gui"


def test_no_display_falls_all_the_way_through_to_halfblock():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=False)
    assert choose_renderer(caps, out=None).name == "halfblock"


def test_inline_graphics_still_beat_the_window():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=True, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=True)
    assert choose_renderer(caps, out=None).name == "kitty"


def test_detect_records_whether_a_window_is_worth_trying():
    from specterm1d.term.caps import detect

    caps = detect(env={"DISPLAY": ":0"}, query_fn=lambda q: None,
                  size_fn=lambda: (43, 116, None, None))
    assert caps.gui is True


def test_gui_can_be_forced_by_name():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import TerminalCaps, choose_renderer

    caps = TerminalCaps(kitty=True, iterm2=True, sixel=True, truecolor=True,
                        rows=43, cols=116, pixel_width=800, pixel_height=480,
                        is_tty=True, gui=False)
    assert choose_renderer(caps, override="gui", out=None).name == "gui"
```

Append to `tests/test_gui_session.py`:

```python
# ---- cli wiring ----------------------------------------------------

def test_gui_is_offered_as_a_renderer_choice():
    from specterm1d.cli import RENDERERS, build_parser

    assert RENDERERS == ("kitty", "iterm2", "sixel", "gui", "halfblock")
    assert build_parser().parse_args(["--renderer", "gui", "x.fits"]).renderer == "gui"


def test_the_gui_shortcut_selects_the_gui_renderer():
    from specterm1d.cli import build_parser, resolve_renderer_choice

    args = build_parser().parse_args(["--gui", "x.fits"])
    assert resolve_renderer_choice(args) == "gui"


def test_an_explicit_renderer_wins_over_the_gui_shortcut():
    from specterm1d.cli import build_parser, resolve_renderer_choice

    args = build_parser().parse_args(["--gui", "--renderer", "halfblock", "x.fits"])
    assert resolve_renderer_choice(args) == "halfblock"


def test_no_flags_leaves_the_choice_to_probing():
    from specterm1d.cli import build_parser, resolve_renderer_choice

    assert resolve_renderer_choice(build_parser().parse_args(["x.fits"])) is None


def test_a_window_that_will_not_open_falls_back_with_one_warning(capsys):
    from specterm1d.cli import attach_or_fall_back
    from specterm1d.term import gui as gui_mod

    class Refuses(gui_mod.GuiRenderer):
        def attach(self, plot):
            raise gui_mod.GuiUnavailable("tkagg: no display name and no $DISPLAY")

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=True)
    renderer = attach_or_fall_back(Refuses(), SpectrumPlot(400, 300), caps,
                                   out=io.StringIO())
    assert renderer.name == "halfblock"
    captured = capsys.readouterr()
    assert "graphics window unavailable" in captured.err
    assert captured.err.count("\n") == 1


def test_the_tty_check_still_refuses_a_pipe_in_gui_mode(monkeypatch, capsys,
                                                       tabular_fits):
    # The text half is half the interface: a graphics window with its prompts
    # redirected to a pipe is not a usable tool. --dump and --cursor remain
    # the headless paths. tabular_fits is the conftest fixture, so the loader
    # succeeds and the tty check is what returns 1.
    from specterm1d import cli

    monkeypatch.setattr(
        cli.caps_mod, "detect",
        lambda **kwargs: TerminalCaps(False, False, False, False, 24, 80,
                                      None, None, False),
    )
    assert cli.main(["--gui", str(tabular_fits)]) == 1
    assert "not a tty" in capsys.readouterr().err


def test_a_terminal_renderer_passes_straight_through_attachment():
    from specterm1d.cli import attach_or_fall_back
    from specterm1d.term.halfblock import HalfblockRenderer

    caps = TerminalCaps(kitty=False, iterm2=False, sixel=False, truecolor=True,
                        rows=43, cols=116, pixel_width=None, pixel_height=None,
                        is_tty=True, gui=False)
    renderer = HalfblockRenderer(out=io.StringIO())
    assert attach_or_fall_back(renderer, SpectrumPlot(116, 82), caps,
                               out=io.StringIO()) is renderer
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_caps.py tests/test_gui_session.py -v`
Expected: FAIL — `TypeError: TerminalCaps.__init__() got an unexpected keyword
argument 'gui'` and `ImportError: cannot import name 'resolve_renderer_choice'`

- [ ] **Step 3: Teach `caps.py` about the window**

In `specterm1d/term/caps.py`:

```python
# Renderer preference order. Inline graphics win where they exist - one window
# beats two - then a real graphics window, and halfblock last: correct
# everywhere, comfortable nowhere.
PREFERENCE = ("kitty", "iterm2", "sixel", "gui", "halfblock")
```

Add the field to `TerminalCaps`, last so every existing positional
construction keeps working:

```python
@dataclass(frozen=True)
class TerminalCaps:
    kitty: bool
    iterm2: bool
    sixel: bool
    truecolor: bool
    rows: int
    cols: int
    pixel_width: int | None
    pixel_height: int | None
    is_tty: bool
    # Worth trying a graphics window. choose_renderer reads this by name
    # through the same getattr the protocol flags use.
    gui: bool = False
```

In `detect`, import the backend locally rather than at module scope -
`term/__init__.py` imports `caps` before `gui`, so at module scope the package
is only partly initialised. Add as the first line of the function body:

```python
    # Local: term/__init__ imports caps before gui, and probing is not on any
    # hot path.
    from specterm1d.term import gui as gui_backend
```

and set the field in the returned `TerminalCaps`:

```python
    return TerminalCaps(
        kitty=kitty, iterm2=iterm2, sixel=sixel, truecolor=truecolor,
        rows=rows, cols=cols, pixel_width=xpixel, pixel_height=ypixel,
        is_tty=True, gui=gui_backend.available(env),
    )
```

- [ ] **Step 4: Register the factory and carry `gui` through a resize**

In `specterm1d/term/__init__.py`, add the import and registration and extend
`__all__`:

```python
from specterm1d.term.gui import GuiRenderer
...
register_renderer("gui", lambda caps, out: GuiRenderer())
```

In `specterm1d/session.py`, `on_resize` reconstructs `TerminalCaps`; add
`gui=self.caps.gui,` beside `is_tty=self.caps.is_tty,` so a terminal resize
does not quietly clear the capability.

- [ ] **Step 5: Wire the CLI**

In `specterm1d/cli.py`:

```python
RENDERERS = ("kitty", "iterm2", "sixel", "gui", "halfblock")
```

Add the flag in `build_parser`, next to `--renderer`:

```python
    parser.add_argument("--gui", action="store_true",
                        help="shortcut for --renderer gui (a matplotlib window)")
```

Add two helpers above `main`:

```python
def resolve_renderer_choice(args) -> str | None:
    """--gui is a shortcut; an explicit --renderer always wins."""
    if args.renderer:
        return args.renderer
    return "gui" if args.gui else None


def attach_or_fall_back(renderer, plot, caps, out):
    """Open the renderer's window, or warn once and use halfblock.

    A viewer that refuses to start over a missing window is worse than one
    that draws coarsely, so this is never fatal - even for an explicit
    --renderer gui. Terminal backends have no attach() and pass straight
    through.
    """
    from specterm1d.term.gui import GuiUnavailable
    from specterm1d.term.halfblock import HalfblockRenderer

    attach = getattr(renderer, "attach", None)
    if attach is None:
        return renderer
    try:
        attach(plot)
    except GuiUnavailable as exc:
        print(f"graphics window unavailable ({exc}); using halfblock",
              file=sys.stderr)
        return HalfblockRenderer(out=out, truecolor=caps.truecolor)
    return renderer
```

and reorder the tail of `main` so the plot exists before the window does — this
is what lets the fallback happen without constructing `Session` twice:

```python
    renderer = caps_mod.choose_renderer(caps, override=resolve_renderer_choice(args),
                                        out=sys.stdout)
    width, height = renderer.target_pixels(caps.rows - 2, caps.cols)
    plot = SpectrumPlot(width, height)
    renderer = attach_or_fall_back(renderer, plot, caps, out=sys.stdout)
    session = Session(collection, renderer, plot, out=sys.stdout, caps=caps)
    session.debug = args.debug
```

(No `plot.resize()` after a fallback: `Session.render()` resizes the figure
from the terminal geometry on every frame in the terminal path.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest tests/test_caps.py tests/test_gui_session.py -v`
Expected: PASS

- [ ] **Step 7: Full suite and lint**

Run: `pytest -q && ruff check .`
Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add specterm1d/term/caps.py specterm1d/term/__init__.py specterm1d/session.py \
        specterm1d/cli.py tests/test_caps.py tests/test_gui_session.py
git commit -m "feat: prefer a graphics window over halfblock, and fall back cleanly

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: The blitted crosshair

What made `splot`'s cursor readable against the axes. Separable by design: if
blitting fights the chosen backend, drop this task and ship the pointer plus
the title readout, which already carry exact coordinates.

**Files:**
- Modify: `specterm1d/term/gui.py` (`GuiRenderer.invalidate`, `crosshair`)
- Modify: `specterm1d/session.py` (`render`, `on_motion`)
- Test: `tests/test_gui.py` (append), `tests/test_gui_session.py` (append)

**Interfaces:**
- Consumes: `GuiRenderer` from Task 5; `plot.COLOR_FG`.
- Produces:
  - `GuiRenderer.invalidate() -> None` — drop the cached background and the
    crosshair artists (`ax.clear()` in `plot.draw` destroys them every frame)
  - `GuiRenderer.crosshair(x: float, y: float) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gui.py`:

```python
# ---- crosshair -----------------------------------------------------

class BlitCanvas(FakeCanvas):
    def __init__(self, size=(640, 480)):
        super().__init__(size)
        self.copies = 0
        self.restores = 0
        self.blits = 0

    def copy_from_bbox(self, bbox):
        self.copies += 1
        return object()

    def restore_region(self, background):
        self.restores += 1

    def blit(self, bbox):
        self.blits += 1


def blit_open(fig, size, backends=None):
    canvas = BlitCanvas()
    return canvas, FakeManager(canvas), "fake"


def blitting_renderer():
    from specterm1d.plot import SpectrumPlot

    plot = SpectrumPlot(400, 300)
    renderer = gui.GuiRenderer(size=(400, 300), open_fn=blit_open)
    renderer.attach(plot)
    return renderer, plot


def test_the_first_crosshair_captures_the_background_and_blits():
    renderer, _ = blitting_renderer()
    renderer.crosshair(5500.0, 1.0)
    assert renderer.canvas.copies == 1
    assert renderer.canvas.restores == 1
    assert renderer.canvas.blits == 1


def test_later_crosshairs_reuse_the_captured_background():
    # The whole point: a few milliseconds per motion event, not 182.
    renderer, _ = blitting_renderer()
    for x in (5100.0, 5200.0, 5300.0):
        renderer.crosshair(x, 1.0)
    assert renderer.canvas.copies == 1
    assert renderer.canvas.blits == 3


def test_the_crosshair_follows_the_pointer():
    renderer, plot = blitting_renderer()
    renderer.crosshair(5100.0, 1.0)
    renderer.crosshair(5900.0, 2.0)
    assert renderer._vline.get_xdata()[0] == pytest.approx(5900.0)
    assert renderer._hline.get_ydata()[0] == pytest.approx(2.0)


def test_invalidate_drops_the_background_and_the_artists():
    # plot.draw() calls ax.clear(), which destroys them; a stale background
    # would blit the previous frame back over the new one.
    renderer, _ = blitting_renderer()
    renderer.crosshair(5100.0, 1.0)
    renderer.invalidate()
    assert renderer._vline is None and renderer._hline is None
    renderer.crosshair(5200.0, 1.0)
    assert renderer.canvas.copies == 2


def test_a_resize_invalidates_the_background():
    renderer, _ = blitting_renderer()
    renderer.crosshair(5100.0, 1.0)
    renderer.canvas.callbacks["resize_event"](FakeEvent())
    renderer.crosshair(5200.0, 1.0)
    assert renderer.canvas.copies == 2


def test_the_crosshair_is_a_no_op_before_attach():
    gui.GuiRenderer(open_fn=blit_open).crosshair(1.0, 2.0)
```

Append to `tests/test_gui_session.py`:

```python
# ---- crosshair wiring ----------------------------------------------

class CrosshairGui(FakeGui):
    def __init__(self, script=()):
        super().__init__(script)
        self.crosshairs = []
        self.invalidations = 0

    def crosshair(self, x, y):
        self.crosshairs.append((x, y))

    def invalidate(self):
        self.invalidations += 1


def test_motion_moves_the_crosshair_without_a_render():
    session, renderer, _ = make_gui_session()
    session.renderer = CrosshairGui()
    session.renderer.attach(session.plot)
    session.on_motion(5500.0, 3.0)
    assert session.renderer.crosshairs == [(5500.0, 3.0)]


def test_a_full_render_invalidates_the_crosshair_background():
    session, _, _ = make_gui_session()
    session.renderer = CrosshairGui()
    session.renderer.attach(session.plot)
    session.render()
    assert session.renderer.invalidations == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_gui.py -k crosshair -v`
Expected: FAIL — `AttributeError: 'GuiRenderer' object has no attribute 'crosshair'`

- [ ] **Step 3: Add the crosshair to `GuiRenderer`**

In `specterm1d/term/gui.py`, add `from specterm1d.plot import COLOR_FG` to the
imports, add to `__init__`:

```python
        self._background = None
        self._vline = None
        self._hline = None
```

change `_on_resize` to invalidate as well:

```python
    def _on_resize(self, _event) -> None:
        self.resized = True
        self.invalidate()
```

and add the two methods:

```python
    def invalidate(self) -> None:
        """Drop the cached background and the crosshair artists.

        plot.draw() calls ax.clear(), which destroys the artists outright, and
        a background captured from the previous frame would blit the old plot
        back over the new one.
        """
        self._background = None
        self._vline = self._hline = None

    def crosshair(self, x: float, y: float) -> None:
        """Move the crosshair by blitting - a few ms, not a full redraw.

        splot drew one because a bare pointer is unreadable against the axes.
        At 182 ms a frame it cannot be a full render, so the clean plot is
        captured once and restored under each new pair of lines.
        """
        if self.canvas is None or self.plot is None:
            return
        ax = self.plot.ax
        if self._background is None:
            # Captured before the artists exist, so the cached region is the
            # plot alone.
            self._background = self.canvas.copy_from_bbox(ax.bbox)
        if self._vline is None:
            self._vline = ax.axvline(x, color=COLOR_FG, lw=0.7, alpha=0.7,
                                     animated=True)
            self._hline = ax.axhline(y, color=COLOR_FG, lw=0.7, alpha=0.7,
                                     animated=True)
        self._vline.set_xdata([x, x])
        self._hline.set_ydata([y, y])
        self.canvas.restore_region(self._background)
        ax.draw_artist(self._vline)
        ax.draw_artist(self._hline)
        self.canvas.blit(ax.bbox)
```

- [ ] **Step 4: Call it from the session**

In `specterm1d/session.py`, extend `on_motion`:

```python
    def on_motion(self, x: float, y: float) -> None:
        """Pointer position from the graphics window, already in data units.

        No ax.get_position() arithmetic and no cell quantization - a
        matplotlib motion event carries event.xdata directly. Must not
        trigger a render: at 1200x800 a frame costs 182 ms.
        """
        self.view.cursor_x = float(x)
        self.view.cursor_y = float(y)
        crosshair = getattr(self.renderer, "crosshair", None)
        if crosshair is not None:
            crosshair(x, y)
```

and in `render`'s interactive branch, invalidate after the draw:

```python
        if self.interactive:
            # No CellRect, no text chrome, no footer, and no plot.resize():
            # the window drives the figure size, not the other way round.
            self.plot.draw(self.view.to_request(title=self.title()))
            invalidate = getattr(self.renderer, "invalidate", None)
            if invalidate is not None:
                invalidate()
            return
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/test_gui.py tests/test_gui_session.py -v`
Expected: PASS

- [ ] **Step 6: Full suite and lint**

Run: `pytest -q && ruff check .`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add specterm1d/term/gui.py specterm1d/session.py tests/test_gui.py \
        tests/test_gui_session.py
git commit -m "feat: blit a crosshair under the pointer

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Document two-window mode

**Files:**
- Modify: `README.md` (the `## Terminal support` section)

**Interfaces:**
- Consumes: the selection table and flags from Task 7.
- Produces: no code.

- [ ] **Step 1: Read the section being replaced**

Run: `sed -n '47,80p' README.md`
Expected: the existing `## Terminal support` section, so the new text keeps its
surrounding voice and does not duplicate what is already there.

- [ ] **Step 2: Add the two-window section**

Insert after the existing `## Terminal support` content, before `## Keys`:

```markdown
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
```

- [ ] **Step 3: Verify the whole feature end to end**

Run: `pytest -q && ruff check .`
Expected: all green — the 365 pre-existing tests plus roughly 70 new ones.

- [ ] **Step 4: Confirm the untouched paths really are untouched**

Run: `git diff --stat main -- specterm1d/term/halfblock.py specterm1d/term/chrome.py specterm1d/keymap.py specterm1d/view.py specterm1d/fitting.py specterm1d/io/`
Expected: empty. Anything listed means the change leaked out of scope.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: describe two-window mode and renderer selection

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```
