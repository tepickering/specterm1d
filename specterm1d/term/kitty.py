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
"""
from __future__ import annotations

import base64
import contextlib
import io
import os
import tempfile
from collections import deque
from pathlib import Path
from typing import Iterator

import numpy as np
from PIL import Image

from specterm1d.term.caps import tmux_passthrough

CHUNK = 4096
# Used only when the terminal will not report its pixel size.
NOMINAL_CELL = (8, 17)

# Frames kept on disk. The file for the frame being drawn cannot be removed
# yet - the terminal reads it when it gets round to the escape, not when the
# escape is written - so one frame of slack is kept behind it. t=f rather
# than t=t: kitty deletes a t=t file itself, and owning the whole lifecycle
# here beats depending on its rules about which directories it will delete
# from.
KEEP_FRAMES = 2


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
            control = (f"a=T,f=100,i={image_id},p=1,q=2,"
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
    return (f"\x1b_Ga=T,f=100,t=f,i={image_id},p=1,q=2,"
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
        self._frames: deque = deque()
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

    def _write_frame(self, payload: bytes) -> Path | None:
        """Put one frame on disk, retiring the ones the terminal is done with.

        Returns None if the filesystem will not have it, which turns the file
        route off for good rather than failing once a frame.
        """
        self._counter += 1
        path = self._tmpdir / f"specterm1d-{os.getpid()}-{self._counter}.png"
        try:
            path.write_bytes(payload)
        except OSError:
            self.by_file = False
            return None
        self._frames.append(path)
        while len(self._frames) > KEEP_FRAMES:
            _unlink(self._frames.popleft())
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
        while self._frames:
            _unlink(self._frames.popleft())

