"""The GUI backend: a real matplotlib window for terminals with no inline
graphics protocol.

This is the ``xgterm`` model. The window owns interaction; the terminal is a
scrolling transcript. Nothing here imports a toolkit at module import time -
``open_window`` does that lazily, because importing a backend on a headless
box is exactly the case this module has to survive.
"""
from __future__ import annotations

import contextlib
import importlib
import os
import sys

from specterm1d.term.base import Motion
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
