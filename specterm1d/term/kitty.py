"""kitty graphics protocol backend (kitty, Ghostty, WezTerm).

Frames go over as PNG rather than raw RGB. Measured: a 1200x700 frame is
3.2 MB of base64 as raw RGB but 123 KB as base64 PNG at compress_level=1.
Writing 3.2 MB to a pty per keystroke is the difference between fluid and
unusable; the 14.8 ms encode is a bargain against that.

Under tmux every graphics escape goes through tmux's DCS passthrough, since
tmux otherwise eats the APC introducer and prints the payload as text. The
cursor positioning does not: that is an ordinary CSI, and tmux has to see it
to keep its own idea of where the cursor is. tmux does not know an image is
there, so a pane repaint - a resize, a pane switch, leaving copy mode - wipes
it until the next keystroke draws the next frame.

Through tmux the frame goes by file rather than inline. A 1920x1216 pane is
720 KB of base64, which the inline path splits into 180 separate passthrough
sequences for tmux to parse and re-emit one after another, interleaved with
its own screen updates - measured, and it flickers. Handing kitty a path
instead is 81 bytes. It needs the terminal to be on this machine, so ssh
keeps the inline path.

Every placement carries C=1, which is load-bearing under tmux. Without it the
terminal advances the cursor past the image, and tmux - which does not know an
image was drawn at all - keeps writing from where it believes the cursor to
be. Its model and the screen diverge, and the status line comes out in the
wrong row while the pane scrolls the plot away.
"""
from __future__ import annotations

import base64
import contextlib
import io
import os
import tempfile
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image

from specterm1d.term.caps import tmux_passthrough

CHUNK = 4096
# Used only when the terminal will not report its pixel size.
NOMINAL_CELL = (8, 17)

# Frame files, reused in a fixed ring and replaced atomically. The terminal
# reads a frame when it reaches the escape rather than when it is written, and
# how far behind it runs is not knowable from here - so nothing is ever
# unlinked out from under it. The worst a lagging reader can do is pick up a
# newer frame under the same name, which is a picture of the same spectrum.
#
# t=f rather than t=t: kitty deletes a t=t file itself, and owning the whole
# lifecycle here beats depending on its rules about which directories it will
# delete from.
RING = 4


def png_bytes(rgba: np.ndarray, compress_level: int = 1) -> bytes:
    buffer = io.BytesIO()
    Image.fromarray(rgba[..., :3]).save(buffer, "PNG",
                                        compress_level=compress_level)
    return buffer.getvalue()


def kitty_chunks(payload: bytes, image_id: int, cols: int, rows: int,
                 chunk: int = CHUNK) -> Iterator[str]:
    """Yield the escape sequences that transmit and place one image.

    Only the first chunk carries the control keys; the rest carry just the
    continuation flag, which is what the protocol requires.
    """
    encoded = base64.b64encode(payload).decode("ascii")
    pieces = [encoded[i:i + chunk] for i in range(0, len(encoded), chunk)] or [""]

    for index, piece in enumerate(pieces):
        more = 1 if index < len(pieces) - 1 else 0
        if index == 0:
            control = (f"a=T,f=100,i={image_id},p=1,q=2,C=1,"
                       f"c={cols},r={rows},m={more}")
        else:
            control = f"m={more}"
        yield f"\x1b_G{control};{piece}\x1b\\"


def _unlink(path: Path) -> None:
    """Remove a frame file, indifferent to it having gone already."""
    with contextlib.suppress(OSError):
        path.unlink()


def kitty_file_chunk(path, image_id: int, cols: int, rows: int) -> str:
    """The escape that displays an image kitty is to read from ``path``."""
    payload = base64.b64encode(str(path).encode()).decode("ascii")
    return (f"\x1b_Ga=T,f=100,t=f,i={image_id},p=1,q=2,C=1,"
            f"c={cols},r={rows};{payload}\x1b\\")


class KittyRenderer:
    name = "kitty"
    inline_graphics = True

    def __init__(self, out, caps, image_id: int = 1, tmpdir=None):
        self.out = out
        self.caps = caps
        self.image_id = image_id
        self.passthrough = bool(getattr(caps, "tmux", False))
        # Only where the inline path is expensive and a file can be read:
        # direct transmission is already fluid when tmux is not in the way.
        self.by_file = self.passthrough and bool(getattr(caps, "local", True))
        self._tmpdir = Path(tmpdir) if tmpdir else Path(tempfile.gettempdir())
        self._counter = 0

    def _graphics(self, sequence: str) -> None:
        self.out.write(tmux_passthrough(sequence) if self.passthrough
                       else sequence)

    def _cell_size(self) -> tuple[float, float]:
        if self.caps.pixel_width and self.caps.pixel_height and self.caps.cols \
                and self.caps.rows:
            return (self.caps.pixel_width / self.caps.cols,
                    self.caps.pixel_height / self.caps.rows)
        return NOMINAL_CELL

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        cell_w, cell_h = self._cell_size()
        return (max(int(cols * cell_w), 1), max(int(rows * cell_h), 1))

    def _frame_paths(self):
        base = f"specterm1d-{os.getpid()}"
        return [self._tmpdir / f"{base}-{slot}.png" for slot in range(RING)]

    def _write_frame(self, payload: bytes) -> Path | None:
        """Put one frame in the next ring slot, atomically.

        Written to a scratch name and renamed, so a reader that arrives
        mid-write sees the previous frame whole rather than half of this one.
        Returns None if the filesystem will not have it, which turns the file
        route off for good rather than failing once a frame.
        """
        path = self._frame_paths()[self._counter % RING]
        self._counter += 1
        part = path.with_suffix(".part")
        try:
            part.write_bytes(payload)
            os.replace(part, path)
        except OSError:
            self.by_file = False
            _unlink(part)
            return None
        return path

    def draw(self, rgba: np.ndarray, rect) -> None:
        # p=1 with a stable image id replaces the placement in situ, so there
        # is no delete-then-draw flash between frames.
        self.out.write(f"\x1b[{rect.row + 1};{rect.col + 1}H")
        payload = png_bytes(rgba)
        path = self._write_frame(payload) if self.by_file else None
        if path is not None:
            self._graphics(kitty_file_chunk(path, self.image_id,
                                            rect.cols, rect.rows))
        else:
            for piece in kitty_chunks(payload, self.image_id,
                                      rect.cols, rect.rows):
                self._graphics(piece)
        self.out.flush()

    def teardown(self) -> None:
        try:
            self._graphics(f"\x1b_Ga=d,d=i,i={self.image_id},q=2;\x1b\\")
            self.out.flush()
        except Exception:
            pass
        for path in self._frame_paths():
            _unlink(path)

