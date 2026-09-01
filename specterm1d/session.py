"""The interactive session: layout, status line, dispatch, and teardown.

Layout follows splot: the plot fills all but the bottom two rows, then a
status line and a message/prompt line.

Teardown is the failure mode that matters most. Raw mode plus a hidden cursor
plus a stray placed image is the worst way for a TUI to die, so it runs from
try/finally, atexit, and the signal handlers alike, and is idempotent.
"""
from __future__ import annotations

import atexit
import contextlib
import signal
import sys
import time
from pathlib import Path

import numpy as np

from specterm1d import keymap
from specterm1d.logfile import SplotLog
from specterm1d.plot import COLOR_OVERLAY, SpectrumPlot, tick_values
from specterm1d.spec import SpecCollection
from specterm1d.term.base import CellRect, Motion
from specterm1d.term.caps import TerminalCaps
from specterm1d.term.chrome import ChromeLayout, layout_for, render_chrome
from specterm1d.term.input import Key, KeyReader
from specterm1d.transcript import Transcript
from specterm1d.view import ViewState

HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR_SCREEN = "\x1b[2J\x1b[H"
MOUSE_ON = "\x1b[?1000;1002;1006h"
MOUSE_OFF = "\x1b[?1000;1002;1006l"
PIXEL_MOUSE_ON = "\x1b[?1000;1002;1016h"
PIXEL_MOUSE_OFF = "\x1b[?1000;1002;1016l"
PIXEL_MOUSE_LEAVE = 1 << 8

# Arrow-key step as a fraction of the visible x range.
CURSOR_STEP = 0.002
CURSOR_STEP_FAST = 0.05

# The GUI loop polls rather than blocking on a file descriptor, so it must
# poll faster than a person types. pump() on an idle window is microseconds.
POLL_INTERVAL = 0.01


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
        self.view.follow_flux()
        self.last_message = ""
        self.files: list = []
        self.file_index: int = 0
        self.overlay_specs: list = []
        self.showing_help: bool = False
        self.hint_index: int = 0
        self.log = SplotLog()
        self.showing_log = False
        self.page_index = 0
        # Only the halfblock backend needs text chrome, and only on a real
        # terminal: --dump writes a PNG, which wants matplotlib's own labels.
        self.text_chrome = bool(getattr(renderer, "text_chrome", False)
                                and caps is not None and caps.is_tty)
        self.plot.bare = self.text_chrome
        # An interactive backend owns its own window and event loop: keys come
        # from poll(), text scrolls in the terminal, and raw mode never starts.
        self.interactive = bool(getattr(renderer, "interactive", False))
        # Built in both modes so nothing branches on its existence; the
        # terminal path simply never uses it.
        self.transcript = Transcript(self.out)
        self._chrome_cache: str | None = None
        self.mouse_enabled = False

        self.pending: object | None = None      # AwaitKey / AwaitCursor
        self.debug = False
        self.finished = False
        self._torn_down = False

    def set_mouse(self, enabled: bool) -> None:
        if self.interactive:
            self.mouse_enabled = False
            self.message("mouse handled by graphics window")
            return
        self.mouse_enabled = enabled
        mouse_on = PIXEL_MOUSE_ON if self.pixel_mouse() else MOUSE_ON
        mouse_off = PIXEL_MOUSE_OFF if self.pixel_mouse() else MOUSE_OFF
        try:
            self.out.write(mouse_on if enabled else mouse_off)
            self.out.flush()
        except Exception:
            pass
        self.message(f"mouse {'on' if enabled else 'off'}")

    def pixel_mouse(self) -> bool:
        """Whether mouse reports arrive as pixels rather than cells.

        Both halves have to hold: the terminal must implement DECSET 1016,
        and the backend must be placing pixels in the terminal for them to
        mean anything. Read from caps rather than cached on the renderer, so
        a resize cannot leave the mode disagreeing with the geometry.
        """
        return bool(self.caps.pixel_mouse
                    and getattr(self.renderer, "inline_graphics", False))

    def _pixel_mouse_left(self, key: Key) -> bool:
        """Whether the pointer left the window, invalidating its coordinates.

        kitty's extension to the pixel protocol, and kitty's alone; terminals
        that do not send it simply never trip this.
        """
        if key.name != "mouse" or not self.pixel_mouse():
            return False
        from specterm1d.term.input import parse_sgr_mouse

        report = parse_sgr_mouse(key.char)
        return report is not None and bool(report[0] & PIXEL_MOUSE_LEAVE)

    def on_mouse(self, col: int, row: int) -> None:
        """Map a 1-based terminal pointer position to data coordinates.

        SGR mouse coordinates normally name cells. A terminal that implements
        DECSET 1016 reports pixels instead; mapping those through its pixel
        geometry preserves motion within a cell. The position is then tested
        against the axes bbox so margins and footer lines remain inactive.
        """
        rect = self.plot_rect()
        if rect.cols <= 0 or rect.rows <= 0:
            return

        if self.pixel_mouse():
            if not self.caps.pixel_width or not self.caps.pixel_height:
                return
            cell_width = self.caps.pixel_width / self.caps.cols
            cell_height = self.caps.pixel_height / self.caps.rows
            frac_x = (col - 1 - rect.col * cell_width) / (
                rect.cols * cell_width
            )
            frac_y = 1.0 - (row - 1 - rect.row * cell_height) / (
                rect.rows * cell_height
            )
        else:
            frac_x = (col - 1 - rect.col) / rect.cols
            frac_y = 1.0 - (row - 1 - rect.row) / rect.rows
        bbox = self.plot.ax.get_position()

        if not (bbox.x0 <= frac_x <= bbox.x1 and bbox.y0 <= frac_y <= bbox.y1):
            return

        tx = (frac_x - bbox.x0) / (bbox.x1 - bbox.x0)
        ty = (frac_y - bbox.y0) / (bbox.y1 - bbox.y0)
        xlo, xhi = self.view.xlim
        ylo, yhi = self.view.ylim
        self.view.cursor_x = float(xlo + tx * (xhi - xlo))
        self.view.cursor_y = float(ylo + ty * (yhi - ylo))
        self.view.lock_cursor_y()

    def on_motion(self, x: float, y: float) -> None:
        """Pointer position from the graphics window, already in data units.

        No ax.get_position() arithmetic and no cell quantization - a
        matplotlib motion event carries event.xdata directly. Must not
        trigger a render: at 1200x800 a frame costs 182 ms.
        """
        self.view.cursor_x = float(x)
        self.view.cursor_y = float(y)
        self.view.lock_cursor_y()
        crosshair = getattr(self.renderer, "crosshair", None)
        if crosshair is not None:
            crosshair(x, y)

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
        self.view.follow_flux()
        self.message(f"loaded {collection.path} ({len(collection)} spectra)")
        return True

    # ---- layout -----------------------------------------------------

    def outer_rect(self) -> CellRect:
        """Everything above the status and message lines."""
        return CellRect(row=0, col=0, rows=max(self.caps.rows - 2, 1),
                        cols=self.caps.cols)

    def chrome_layout(self) -> ChromeLayout:
        """Where the image goes once the text decoration has its share."""
        outer = self.outer_rect()
        _, ylabels = self.y_ticks(outer.rows)
        return layout_for(outer, ylabels, title=True)

    def y_ticks(self, rows: int):
        n = int(np.clip(rows // 5, 2, 6))
        return tick_values(*self.view.ylim, n)

    def x_ticks(self, cols: int):
        n = int(np.clip(cols // 14, 2, 8))
        return tick_values(*self.view.xlim, n)

    def plot_rect(self) -> CellRect:
        if not self.text_chrome:
            return self.outer_rect()
        return self.chrome_layout().plot

    def on_resize(self, rows: int, cols: int, pixel_width: int | None = None,
                  pixel_height: int | None = None) -> None:
        """Adopt the new geometry, pixels included where the terminal gives them.

        The pixel size is not decoration any more: cell_px() divides it by the
        row count to size the chrome, so carrying the old value across a
        resize would leave the labels scaled for the window this used to be.
        Terminals that report nothing keep whatever they had.
        """
        self.caps = TerminalCaps(
            kitty=self.caps.kitty, iterm2=self.caps.iterm2, sixel=self.caps.sixel,
            truecolor=self.caps.truecolor, rows=rows, cols=cols,
            pixel_width=pixel_width or self.caps.pixel_width,
            pixel_height=pixel_height or self.caps.pixel_height,
            is_tty=self.caps.is_tty, gui=self.caps.gui,
            pixel_mouse=self.caps.pixel_mouse, tmux=self.caps.tmux,
            local=self.caps.local,
        )
        self.renderer.teardown()      # force a full repaint
        self._chrome_cache = None

    # ---- rendering --------------------------------------------------

    def render_rgba(self, size: tuple[int, int] | None = None):
        """Render one frame without writing to the terminal.

        ``size`` overrides the terminal-derived geometry. --dump wants that:
        a PNG has no status line to leave two rows for, so it should come out
        at exactly the requested size.
        """
        if size is None:
            rect = self.plot_rect()
            size = self.renderer.target_pixels(rect.rows, rect.cols)
        self.plot.resize(*size)
        return self.plot.render(self.view.to_request(title=self.title()))

    def dump_png(self, path, size: tuple[int, int] | None = None) -> None:
        from PIL import Image

        Image.fromarray(self.render_rgba(size)[..., :3]).save(str(path))

    def cell_px(self) -> float | None:
        """Height of one terminal cell in the pixels the figure is drawn in.

        The inline backends render at the terminal's own pixel budget and show
        it 1:1, so this is what makes matplotlib's labels the height of the
        terminal's text rather than a fixed 8 pt that shrinks as the window
        grows. None where there is nothing to match: no tty (--dump asks for
        an explicit size), or a terminal that does not report its pixels.
        """
        caps = self.caps
        if caps is None or not caps.is_tty or not caps.pixel_height or not caps.rows:
            return None
        return caps.pixel_height / caps.rows

    def title(self) -> str:
        # The basename, not the path: a full absolute path is both unreadable
        # and wide enough to be clipped at either end of the figure.
        path = self.collection.path or ""
        return f"{Path(path).name}  {self.view.entry.label}".strip()

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
            self.plot.draw(self.view.to_request(title=self.title(),
                                                with_cursor=False))
            invalidate = getattr(self.renderer, "invalidate", None)
            if invalidate is not None:
                invalidate()
            return
        layout = self.chrome_layout() if self.text_chrome else None
        rect = layout.plot if layout else self.outer_rect()
        width, height = self.renderer.target_pixels(rect.rows, rect.cols)
        self.plot.cell_px = self.cell_px()
        self.plot.resize(width, height)
        request = self.view.to_request(
            title=self.title(),
            cursor_crosshair=bool(getattr(self.renderer, "inline_graphics", False)),
        )
        rgba = self.plot.render(request)
        self.renderer.draw(rgba, rect)
        if layout is not None:
            self._write_chrome(layout, request)
        self._write_footer()

    def _write_chrome(self, layout: ChromeLayout, request) -> None:
        """Paint the axis decoration as text, skipping unchanged frames.

        Panning redraws it every keystroke; the labels usually have not moved,
        and a few hundred bytes of escape per key is worth avoiding.
        """
        text = render_chrome(
            layout, self.view.xlim, self.view.ylim,
            xticks=self.x_ticks(layout.plot.cols),
            yticks=self.y_ticks(layout.plot.rows),
            title=self.title(),
            xlabel=request.xlabel, ylabel=request.ylabel,
            legend=[(name, COLOR_OVERLAY[i % len(COLOR_OVERLAY)])
                    for i, name in enumerate(sorted(self.view.overlays))],
            truecolor=self.caps.truecolor,
        )
        if text != self._chrome_cache:
            self.out.write(text)
            self._chrome_cache = text

    # ---- full-screen text pages (? and :show) -----------------------
    #
    # Drawn as terminal text rather than into the figure. At halfblock
    # resolution the figure is one pixel per column, where rendered text is
    # illegible; the terminal's own glyphs are crisp on every backend.

    def _text_page_lines(self) -> list[str]:
        if self.showing_help:
            return keymap.help_text(self.caps.cols)
        return self.log.lines or ["(no measurements recorded yet)"]

    def _text_page_count(self) -> tuple[int, int]:
        """(lines per page, number of pages)."""
        per_page = max(self.outer_rect().rows - 1, 1)
        lines = self._text_page_lines()
        return per_page, max((len(lines) + per_page - 1) // per_page, 1)

    def _write_text_page(self) -> None:
        lines = self._text_page_lines()
        per_page, pages = self._text_page_count()
        self.page_index = min(self.page_index, pages - 1)
        start = self.page_index * per_page

        out = [CLEAR_SCREEN]
        for row, line in enumerate(lines[start:start + per_page], start=1):
            out.append(f"\x1b[{row};1H" + line[: self.caps.cols])
        footer = (f"-- {'help' if self.showing_help else 'log'} "
                  f"page {self.page_index + 1}/{pages} -- "
                  "<space> next, b back, any other key closes")
        out.append(f"\x1b[{self.caps.rows};1H\x1b[7m"
                   f"{footer[: self.caps.cols].ljust(self.caps.cols)}\x1b[0m")
        self.out.write("".join(out))
        self.out.flush()

    def _close_text_page(self) -> None:
        self.showing_help = False
        self.showing_log = False
        self.page_index = 0
        if not self.interactive:
            self.renderer.teardown()     # the plot must repaint in full
        self._chrome_cache = None
        self.message("")

    def _handle_text_page(self, key: Key) -> bool:
        _, pages = self._text_page_count()
        forward = key.name == "pagedown" or (key.name == "char" and key.char == " ")
        back = key.name == "pageup" or (key.name == "char" and key.char == "b")

        if back:
            self.page_index = max(self.page_index - 1, 0)
            return True
        if forward and self.page_index + 1 < pages:
            self.page_index += 1
            return True
        self._close_text_page()
        return True

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
        if self.interactive and text:
            self.transcript.line(text)

    def echo(self, text: str) -> None:
        """An in-progress prompt: overwritten in place, not appended."""
        self.last_message = text
        if self.interactive:
            self.transcript.prompt(text)

    # ---- dispatch ---------------------------------------------------

    def move_cursor(self, fraction: float) -> None:
        lo, hi = self.view.xlim
        step = (hi - lo) * fraction
        current = self.view.cursor_x if self.view.cursor_x is not None else lo
        self.view.cursor_x = float(np.clip(current + step, lo, hi))
        self.view.follow_flux()

    def move_cursor_y(self, fraction: float) -> None:
        lo, hi = self.view.ylim
        step = (hi - lo) * fraction
        current = self.view.cursor_y if self.view.cursor_y is not None else lo
        self.view.cursor_y = float(np.clip(current + step, lo, hi))
        self.view.lock_cursor_y()

    def handle(self, key: Key) -> bool:
        if key.name == "resize":
            self.on_resize(*self._terminal_size())
            return True
        if key.name == "eof":
            return False

        if self.showing_help or self.showing_log:
            return self._handle_text_page(key)

        if key.name == "mouse":
            if self._pixel_mouse_left(key):
                return True
            if self.mouse_enabled:
                from specterm1d.term.input import parse_sgr_mouse

                report = parse_sgr_mouse(key.char)
                if report is not None:
                    _, col, row = report
                    self.on_mouse(col, row)
            return True

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
        self.echo(prompt)

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
                self.echo(state.prompt + state.buffer)
            elif key.name == "char":
                state.buffer += key.char
                self.echo(state.prompt + state.buffer)
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
        return result is not False

    def _terminal_size(self) -> tuple[int, int, int | None, int | None]:
        from specterm1d.term.caps import window_size

        return window_size()

    # ---- lifecycle --------------------------------------------------

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

    def run(self) -> None:
        atexit.register(self.teardown)
        for sig in (signal.SIGTERM, signal.SIGHUP):
            with contextlib.suppress(ValueError, OSError):
                signal.signal(sig, lambda *_: (self.teardown(), sys.exit(1)))

        try:
            if self.interactive:
                self._run_gui()
                return
            self.out.write(HIDE_CURSOR + CLEAR_SCREEN)
            with KeyReader() as reader:
                self.render()
                running = True
                while running:
                    keys = reader.read(timeout=0.25)
                    redraw = False
                    for key in keys:
                        if self._pixel_mouse_left(key):
                            continue
                        redraw = True
                        running = self.handle(key)
                        if not running:
                            break
                    # Only on a state change. read() returns an empty batch
                    # every time its select() times out, and redrawing through
                    # that cost a full figure render four times a second for
                    # as long as the plot was open - and, on iTerm2, an inline
                    # image the terminal never frees. Resizes arrive as
                    # Key("resize"), so they are in the batch like any key.
                    if running and redraw:
                        self.render()
            self.finished = True
        finally:
            self.teardown()

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
                self.out.write(
                    PIXEL_MOUSE_OFF if self.pixel_mouse() else MOUSE_OFF)
        except Exception:
            pass
        try:
            self.out.write(SHOW_CURSOR + "\x1b[0m\n")
            self.out.flush()
        except Exception:
            pass
