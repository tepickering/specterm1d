"""The interactive session: layout, status line, dispatch, and teardown.

Layout follows splot: the plot fills all but the bottom two rows, then a
status line and a message/prompt line.

Teardown is the failure mode that matters most. Raw mode plus a hidden cursor
plus a stray placed image is the worst way for a TUI to die, so it runs from
try/finally, atexit, and the signal handlers alike, and is idempotent.
"""
from __future__ import annotations

import atexit
import signal
import sys

import numpy as np

from specterm1d.plot import SpectrumPlot
from specterm1d.spec import SpecCollection
from specterm1d.term.base import CellRect
from specterm1d.term.caps import TerminalCaps
from specterm1d import keymap
from specterm1d.term.input import Key, KeyReader
from specterm1d.view import ViewState

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR_SCREEN = "\x1b[2J\x1b[H"

# Arrow-key step as a fraction of the visible x range.
CURSOR_STEP = 0.002
CURSOR_STEP_FAST = 0.05


class Session:
    def __init__(self, collection: SpecCollection, renderer, plot: SpectrumPlot,
                 out=None, caps: TerminalCaps | None = None):
        self.collection = collection
        self.renderer = renderer
        self.plot = plot
        self.out = out if out is not None else sys.stdout
        self.caps = caps
        self.view = ViewState(collection)
        self.view.reset_limits()
        self.view.cursor_x = float(np.mean(self.view.xlim))
        self.view.cursor_y = float(np.mean(self.view.ylim))
        self.last_message = ""
        self.files: list = []
        self.file_index: int = 0
        self.overlay_specs: list = []
        self.showing_help: bool = False
        self.hint_index: int = 0

        self.pending: object | None = None      # AwaitKey / AwaitCursor, Task 9
        self.debug = False
        self._torn_down = False

    def load_path(self, path) -> bool:
        from specterm1d.io import registry

        try:
            collection = registry.load(path)
        except registry.LoaderError as exc:
            self.message(str(exc).splitlines()[0])
            return False

        if self.view.overplot_next:
            self.overlay_specs.append(self.view.current_spec())
        self.collection = collection
        self.view = ViewState(collection)
        self.view.reset_limits()
        self.view.cursor_x = float(np.mean(self.view.xlim))
        self.message(f"loaded {collection.path} ({len(collection)} spectra)")
        return True

    # ---- layout -----------------------------------------------------

    def plot_rect(self) -> CellRect:
        return CellRect(row=0, col=0, rows=max(self.caps.rows - 2, 1),
                        cols=self.caps.cols)

    def on_resize(self, rows: int, cols: int) -> None:
        self.caps = TerminalCaps(
            kitty=self.caps.kitty, iterm2=self.caps.iterm2, sixel=self.caps.sixel,
            truecolor=self.caps.truecolor, rows=rows, cols=cols,
            pixel_width=self.caps.pixel_width, pixel_height=self.caps.pixel_height,
            is_tty=self.caps.is_tty,
        )
        self.renderer.teardown()      # force a full repaint

    # ---- rendering --------------------------------------------------

    def title(self) -> str:
        name = self.collection.path or ""
        return f"{name}  {self.view.entry.label}"

    def render(self) -> None:
        rect = self.plot_rect()
        width, height = self.renderer.target_pixels(rect.rows, rect.cols)
        self.plot.resize(width, height)
        rgba = self.plot.render(self.view.to_request(title=self.title()))
        self.renderer.draw(rgba, rect)
        self._write_footer()

    def _write_footer(self) -> None:
        rows = self.caps.rows
        status = self.status_line().ljust(self.caps.cols)[: self.caps.cols]
        message = self.last_message.ljust(self.caps.cols)[: self.caps.cols]
        self.out.write(f"\x1b[{rows - 1};1H\x1b[7m{status}\x1b[0m")
        self.out.write(f"\x1b[{rows};1H{message}")
        self.out.flush()

    def status_line(self) -> str:
        view = self.view
        spec = view.display_spec()
        x = view.cursor_x
        if x is None:
            xtext, ytext, ptext = "-", "-", "-"
        else:
            pixel = int(np.clip(np.searchsorted(spec.wave, x), 0, spec.npix - 1))
            xtext = f"{x:.4g}"
            ytext = f"{spec.flux[pixel]:.4g}"
            ptext = str(pixel)

        entry_key = view.variant or view.entry.default
        toggles = "".join([
            "S" if view.show_sigma else "",
            "M" if view.show_mask else "",
            "H" if view.histogram else "",
            "Z" if view.zero_base else "",
            "F" if view.flip else "",
        ])
        cursor_y = "-" if view.cursor_y is None else f"{view.cursor_y:.4g}"
        parts = [
            f"x={xtext}", f"y={ytext}", f"cy={cursor_y}", f"pix={ptext}",
            f"[{entry_key}]", f"{view.index + 1}/{len(self.collection)}",
        ]
        if toggles:
            parts.append(toggles)
        line = "  ".join(parts)
        return line[: self.caps.cols]

    def message(self, text: str) -> None:
        self.last_message = text

    # ---- dispatch ---------------------------------------------------

    def move_cursor(self, fraction: float) -> None:
        lo, hi = self.view.xlim
        step = (hi - lo) * fraction
        current = self.view.cursor_x if self.view.cursor_x is not None else lo
        self.view.cursor_x = float(np.clip(current + step, lo, hi))

    def move_cursor_y(self, fraction: float) -> None:
        lo, hi = self.view.ylim
        step = (hi - lo) * fraction
        current = self.view.cursor_y if self.view.cursor_y is not None else lo
        self.view.cursor_y = float(np.clip(current + step, lo, hi))

    def handle(self, key: Key) -> bool:
        if key.name == "resize":
            self.on_resize(*self._terminal_size())
            return True
        if key.name == "eof":
            return False

        if self.pending is not None:
            return self._handle_pending(key)

        if self._move_cursor_key(key):
            return True

        if key.name == "char":
            return self.dispatch_char(key.char)

        return True

    def _move_cursor_key(self, key) -> bool:
        """Arrow keys drive a 2D crosshair, as splot's Tektronix cursor did.

        The y position is not decoration: 'e', 'k' and 'h' take their
        continuum from the cursor's y at each marked point, exactly as
        IRAF's sumflux.x does with eqy1/eqy2.
        """
        if key.name not in ("left", "right", "up", "down", "shift-left",
                            "shift-right", "shift-up", "shift-down"):
            return False
        fast = key.name.startswith("shift")
        step = CURSOR_STEP_FAST if fast else CURSOR_STEP
        if key.name.endswith("left"):
            self.move_cursor(-step)
        elif key.name.endswith("right"):
            self.move_cursor(+step)
        elif key.name.endswith("up"):
            self.move_cursor_y(+step)
        else:
            self.move_cursor_y(-step)
        return True

    # ---- modal states -----------------------------------------------

    def await_key(self, prompt: str, handler, options: dict[str, str]) -> None:
        self.pending = keymap.AwaitKey(prompt, handler, options)
        detail = "  ".join(f"{k}={v}" for k, v in options.items())
        self.message(f"{prompt}: {detail}" if detail else prompt)

    def await_cursor(self, count: int, prompt: str, handler) -> None:
        self.pending = keymap.AwaitCursor(count, prompt, handler)
        self.message(f"{prompt} (<space> to mark, ESC to cancel)")

    def await_line(self, prompt: str, handler) -> None:
        self.pending = keymap.AwaitLine(prompt, handler)
        self.message(prompt)

    def cancel_pending(self, why: str = "cancelled") -> None:
        self.pending = None
        self.message(why)

    def _handle_pending(self, key) -> bool:
        state = self.pending

        if isinstance(state, keymap.AwaitLine):
            if key.name == "escape":
                self.pending = None
                state.handler(self, None)
            elif key.name == "enter":
                self.pending = None
                state.handler(self, state.buffer)
            elif key.name == "backspace":
                state.buffer = state.buffer[:-1]
                self.message(state.prompt + state.buffer)
            elif key.name == "char":
                state.buffer += key.char
                self.message(state.prompt + state.buffer)
            return True

        if key.name == "escape":
            self.cancel_pending()
            return True

        if isinstance(state, keymap.AwaitKey):
            if key.name == "char":
                self.pending = None
                state.handler(self, key.char)
            return True

        if isinstance(state, keymap.AwaitCursor):
            if self._move_cursor_key(key):
                return True
            if key.name == "char" and key.char == " ":
                state.collected.append((float(self.view.cursor_x),
                                        float(self.view.cursor_y)))
                remaining = state.count - len(state.collected)
                if remaining > 0:
                    self.message(f"{state.prompt}: {remaining} more")
                else:
                    self.pending = None
                    state.handler(self, state.collected)
            return True

        self.pending = None
        return True

    def dispatch_char(self, char: str) -> bool:
        binding = keymap.KEYMAP.get(char)
        if binding is None:
            self.message(f"unbound key: {char!r}")
            return True

        if binding.deferred:
            self.message(f"{binding.help} ({char}): not implemented in v1")
            return True

        handler = keymap.get_command(binding.name)
        if handler is None:
            self.message(f"{binding.name}: no handler registered")
            return True

        # A command raising must never kill the session; --debug promotes it.
        try:
            result = handler(self)
        except Exception as exc:
            if self.debug:
                raise
            self.pending = None
            self.message(f"{binding.name} failed: {exc}")
            return True
        return False if result is False else True

    def _terminal_size(self) -> tuple[int, int]:
        from specterm1d.term.caps import window_size

        rows, cols, _, _ = window_size()
        return rows, cols

    # ---- lifecycle --------------------------------------------------

    def run(self) -> None:
        atexit.register(self.teardown)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, lambda *_: (self.teardown(), sys.exit(1)))
            except (ValueError, OSError):
                pass

        try:
            self.out.write(HIDE_CURSOR + CLEAR_SCREEN)
            with KeyReader() as reader:
                self.render()
                running = True
                while running:
                    for key in reader.read(timeout=0.25):
                        running = self.handle(key)
                        if not running:
                            break
                    if running:
                        self.render()
        finally:
            self.teardown()

    def teardown(self) -> None:
        if self._torn_down:
            return
        self._torn_down = True
        try:
            self.renderer.teardown()
        except Exception:
            pass
        try:
            self.out.write(SHOW_CURSOR + "\x1b[0m\n")
            self.out.flush()
        except Exception:
            pass
