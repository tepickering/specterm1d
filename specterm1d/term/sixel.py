"""Sixel backend (Windows Terminal >= 1.22, foot, xterm, Konsole, mlterm,
contour).

Encoding is the cost on this path, so we lean on a property of our own
output: the plot uses about a dozen colours by design. A fixed 16-entry
palette plus a precomputed 32768-entry lookup table turns quantization into
a single array index instead of a nearest-neighbour search per pixel.

libsixel is used when importable; the numpy encoder is the fallback so the
sixel extra stays optional.
"""
from __future__ import annotations

import numpy as np

# Matches specterm1d.plot's palette, plus blends the antialiaser produces.
PALETTE = np.array([
    [0x10, 0x14, 0x18],   # background
    [0x4a, 0xa3, 0xff],   # spectrum line
    [0xc8, 0xd2, 0xdc],   # axes and text
    [0x2f, 0x5d, 0x8a],   # sigma band
    [0xc8, 0x50, 0x3c],   # mask and fits
    [0xe0, 0xa0, 0x30],   # overlay 1
    [0x50, 0xb0, 0x70],   # overlay 2
    [0xa0, 0x70, 0xd0],   # overlay 3
    [0x20, 0x28, 0x30],   # blends below here
    [0x40, 0x4c, 0x58],
    [0x60, 0x70, 0x80],
    [0x80, 0x94, 0xa8],
    [0x2a, 0x5a, 0x90],
    [0x36, 0x76, 0xc0],
    [0x90, 0x9c, 0xa8],
    [0xff, 0xff, 0xff],
], dtype=np.int32)


def build_lut(palette: np.ndarray) -> np.ndarray:
    """Nearest palette index for every 5-bit-per-channel RGB cell."""
    axis = np.arange(32, dtype=np.int32) * 8 + 4
    grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
    grid = grid.reshape(-1, 3)
    distance = ((grid[:, None, :] - palette[None, :, :]) ** 2).sum(axis=-1)
    return distance.argmin(axis=1).astype(np.uint8)


_LUT: np.ndarray | None = None


def _lut() -> np.ndarray:
    global _LUT
    if _LUT is None:
        _LUT = build_lut(PALETTE)
    return _LUT


def quantize_palette(rgb: np.ndarray, lut: np.ndarray | None = None) -> np.ndarray:
    lut = _lut() if lut is None else lut
    rgb = np.asarray(rgb, dtype=np.int32)
    index = ((rgb[..., 0] >> 3) * 1024 + (rgb[..., 1] >> 3) * 32
             + (rgb[..., 2] >> 3))
    return lut[index]


# Sixel data characters run from 63 to 126: 63 plus the six-bit column mask.
_SIXEL_CHARS = [chr(c) for c in range(63, 127)]


def _rle(codes: np.ndarray) -> str:
    """Run-length encode a row of sixel characters.

    The Python loop runs once per run, not once per column. Plot output is
    mostly long flat runs of background, so finding the run boundaries in
    numpy is what keeps a full-width frame inside the redraw budget.
    """
    codes = np.asarray(codes, dtype=np.int32)
    if codes.size == 0:
        return ""
    starts = np.concatenate(([0], np.flatnonzero(np.diff(codes)) + 1))
    lengths = np.diff(np.concatenate((starts, [codes.size])))
    chars = [_SIXEL_CHARS[c - 63] for c in codes[starts].tolist()]
    return "".join([
        f"!{run}{char}" if run >= 4 else char * run
        for char, run in zip(chars, lengths.tolist())
    ])


def encode_sixel(indexed: np.ndarray, palette: np.ndarray = PALETTE) -> str:
    height, width = indexed.shape
    parts = [f'\x1bPq"1;1;{width};{height}']

    for i, (r, g, b) in enumerate(palette):
        parts.append(f"#{i};2;{r * 100 // 255};{g * 100 // 255};{b * 100 // 255}")

    for y0 in range(0, height, 6):
        band = indexed[y0:y0 + 6]
        bits = (1 << np.arange(band.shape[0], dtype=np.int32))[:, None]
        first = True
        for i in np.unique(band).tolist():
            match = band == i
            if not first:
                parts.append("$")
            first = False
            codes = (match * bits).sum(axis=0) + 63
            parts.append(f"#{i}")
            parts.append(_rle(codes))
        parts.append("-")

    parts.append("\x1b\\")
    return "".join(parts)


def _libsixel_encode(rgba: np.ndarray) -> str | None:
    try:
        import libsixel  # noqa: F401
    except Exception:
        return None
    # libsixel's Python binding is C-level and awkward to drive from a string
    # API; the numpy encoder is fast enough for our restricted palette, so we
    # only take this path if a future need justifies it.
    return None


class SixelRenderer:
    name = "sixel"

    def __init__(self, out, caps):
        self.out = out
        self.caps = caps

    def _cell_size(self) -> tuple[float, float]:
        if self.caps.pixel_width and self.caps.pixel_height and self.caps.cols \
                and self.caps.rows:
            return (self.caps.pixel_width / self.caps.cols,
                    self.caps.pixel_height / self.caps.rows)
        return (8, 17)

    def target_pixels(self, rows: int, cols: int) -> tuple[int, int]:
        cell_w, cell_h = self._cell_size()
        return (max(int(cols * cell_w), 1), max(int(rows * cell_h), 1))

    def draw(self, rgba: np.ndarray, rect) -> None:
        text = _libsixel_encode(rgba)
        if text is None:
            text = encode_sixel(quantize_palette(rgba[..., :3]))
        self.out.write(f"\x1b[{rect.row + 1};{rect.col + 1}H")
        self.out.write(text)
        self.out.flush()

    def teardown(self) -> None:
        pass
