"""The splot keymap and the modal dispatch machine.

Every key keeps its splot meaning. Keys outside v1 are registered as deferred
and report "not implemented in v1" - never absent, never rebound, so muscle
memory cannot silently misfire.
"""
from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class Binding:
    key: str
    name: str
    help: str
    deferred: bool = False


# ---- modal states ---------------------------------------------------

@dataclass
class AwaitKey:
    """splot's two-stage commands: the next keystroke is an argument."""

    prompt: str
    handler: Callable
    options: dict[str, str] = field(default_factory=dict)


@dataclass
class AwaitCursor:
    """Commands that want N marked positions, taken with <space>.

    Each collected entry is an ``(x, y)`` pair from the 2D crosshair. The y
    matters: IRAF's sumflux.x builds the continuum ramp from the cursor's y
    at each marked point (eqy1, eqy2), not from the spectrum.
    """

    count: int
    prompt: str
    handler: Callable
    collected: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class AwaitLine:
    """A typed reply: the ':' prompt, or a query such as '#'."""

    prompt: str
    handler: Callable
    buffer: str = ""


# ---- command registry -----------------------------------------------

_COMMANDS: dict[str, Callable] = {}


def command(name: str):
    def decorate(fn: Callable) -> Callable:
        _COMMANDS[name] = fn
        return fn
    return decorate


def get_command(name: str) -> Callable | None:
    return _COMMANDS.get(name)


def commands() -> dict[str, Callable]:
    return dict(_COMMANDS)


# ---- the keymap -----------------------------------------------------

DEFERRED = {
    "d": "deblend multiple line profiles",
    "t": "fit a function to the spectrum with ICFIT",
    "f": "arithmetic function mode",
    "i": "write the current spectrum to a file",
    "j": "set the nearest pixel to the cursor value",
    "x": "etch-a-sketch line drawing",
    "p": "define a linear wavelength scale",
    "u": "adjust the user coordinate scale",
    "y": "overplot standard star calibration values",
}

_ACTIVE = [
    ("?", "help.page", "page help information"),
    ("/", "help.cycle", "cycle through short status line help"),
    (" ", "display.report", "report cursor position and nearest pixel"),
    ("a", "display.expand", "expand and autoscale between two cursors"),
    ("b", "display.zero_base", "set the plot base level to zero"),
    ("c", "display.clear", "clear all windowing and redraw"),
    ("e", "measure.eqw", "measure equivalent width by summation"),
    ("g", "display.get", "get another spectrum"),
    ("h", "measure.gauss_width", "equivalent width from a specified width"),
    ("k", "measure.profile", "fit a single line profile"),
    ("l", "transform.flambda", "convert to flux per unit wavelength"),
    ("m", "measure.stats", "mean, RMS and S/N over a region"),
    ("n", "transform.fnu", "convert to flux per unit frequency"),
    ("o", "display.overplot", "overplot the next spectrum"),
    ("q", "display.quit", "go on to the next spectrum, then exit"),
    ("r", "display.redraw", "redraw with the current windowing"),
    ("s", "transform.smooth", "smooth via a boxcar"),
    ("v", "display.velocity", "toggle a velocity scale about the cursor"),
    ("w", "display.window", "window the graph"),
    ("z", "display.zoom", "zoom the graph by a factor of 2 in x"),
    ("(", "display.prev", "go to the preceding spectrum"),
    (")", "display.next", "go to the following spectrum"),
    ("#", "display.goto", "go to a spectrum by index or name"),
    ("%", "display.variant", "cycle the extraction/calibration variant"),
    ("$", "display.pixel_coords", "switch between pixel and world coordinates"),
    ("-", "transform.subtract_fit", "subtract the fitted profile"),
    (",", "display.shift_left", "shift the graph window to the left"),
    (".", "display.shift_right", "shift the graph window to the right"),
    ("U", "transform.undo", "undo the last transform (not in splot)"),
    ("I", "display.interrupt", "leave the graph immediately"),
    (":", "colon.prompt", "enter a colon command"),
]

KEYMAP: dict[str, Binding] = {
    key: Binding(key, name, helptext) for key, name, helptext in _ACTIVE
}
KEYMAP.update({
    key: Binding(key, f"deferred.{key}", helptext, deferred=True)
    for key, helptext in DEFERRED.items()
})

# The gtools window submode reached with 'w', transcribed from IRAF
# pkg/xtools/gtools/gtwindow.x and lib/scr/gtools.key. Shifts are 0.75 of the
# window, zooms are cursor +/- d/4 (a factor of two), and 'p' pans to cursor
# +/- d, which doubles the window - exactly as gt_window1 does it.
WINDOW_KEYS = {
    "a": "autoscale x and y axes",
    "b": "set bottom edge of window",
    "c": "center window at cursor position",
    "d": "shift window down",
    "e": "expand window (mark two corners)",
    "f": "flip x axis",
    "g": "flip y axis",
    "j": "set left edge of window",
    "k": "set right edge of window",
    "l": "shift window left",
    "m": "autoscale x axis",
    "n": "autoscale y axis",
    "p": "pan x and y axes about cursor",
    "r": "shift window right",
    "t": "set top edge of window",
    "u": "shift window up",
    "x": "zoom x axis about cursor",
    "y": "zoom y axis about cursor",
    "z": "zoom x and y axes about cursor",
}

STATUS_HINTS = [
    "? help   a expand   c clear   z zoom   , . pan   ( ) prev/next   q quit",
    "e eqw   m stats   k+g|l|v fit   h+a|b|c|l|r|k width   s smooth   U undo",
    "% variant   $ pixel/world   v velocity   :sigma :mask :sky :telluric",
    "<space> mark or report   # goto   g load   w window   : colon command",
]


def help_text(cols: int = 80) -> list[str]:
    """The full keymap, wrapped to the terminal width."""
    lines = ["specterm1d - IRAF splot keybindings", ""]

    lines.append("Display and navigation")
    for key, _name, helptext in _ACTIVE:
        shown = "<space>" if key == " " else key
        lines.extend(textwrap.wrap(f"  {shown:<8} {helptext}", width=cols,
                                   subsequent_indent=" " * 11) or [f"  {shown}"])

    lines.append("")
    lines.append("Window submode (w), from IRAF gtools")
    for key, helptext in WINDOW_KEYS.items():
        lines.extend(textwrap.wrap(f"  {key:<8} {helptext}", width=cols,
                                   subsequent_indent=" " * 11))

    lines.append("")
    lines.append("Registered but not implemented in v1")
    for key, helptext in sorted(DEFERRED.items()):
        lines.extend(textwrap.wrap(f"  {key:<8} {helptext} - not implemented",
                                   width=cols, subsequent_indent=" " * 11))
    return [line[:cols] for line in lines]
