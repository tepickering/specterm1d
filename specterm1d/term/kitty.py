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

Every placement carries C=1, which is load-bearing under tmux. Without it the
terminal advances the cursor past the image, and tmux - which does not know an
image was drawn at all - keeps writing from where it believes the cursor to
be. Its model and the screen diverge, and the status line comes out in the
wrong row while the pane scrolls the plot away.
"""
from __future__ import annotations

import base64
import io
from typing import Iterator

import numpy as np
from PIL import Image

from specterm1d.term.caps import tmux_passthrough

CHUNK = 4096
# Used only when the terminal will not report its pixel size.
NOMINAL_CELL = (8, 17)


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


class KittyRenderer:
    name = "kitty"
    inline_graphics = True

    def __init__(self, out, caps, image_id: int = 1):
        self.out = out
        self.caps = caps
        self.image_id = image_id
        self.passthrough = bool(getattr(caps, "tmux", False))

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

    def draw(self, rgba: np.ndarray, rect) -> None:
        # p=1 with a stable image id replaces the placement in situ, so there
        # is no delete-then-draw flash between frames.
        self.out.write(f"\x1b[{rect.row + 1};{rect.col + 1}H")
        for piece in kitty_chunks(png_bytes(rgba), self.image_id,
                                  rect.cols, rect.rows):
            self._graphics(piece)
        self.out.flush()

    def teardown(self) -> None:
        try:
            self._graphics(f"\x1b_Ga=d,d=i,i={self.image_id},q=2;\x1b\\")
            self.out.flush()
        except Exception:
            pass

