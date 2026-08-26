"""The GUI backend: a real matplotlib window for terminals with no inline
graphics protocol.

This is the ``xgterm`` model. The window owns interaction; the terminal is a
scrolling transcript. Nothing here imports a toolkit at module import time -
``open_window`` does that lazily, because importing a backend on a headless
box is exactly the case this module has to survive.
"""
from __future__ import annotations

import importlib
import os
import sys

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
