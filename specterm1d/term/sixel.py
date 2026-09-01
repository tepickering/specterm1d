"""Sixel backend (Windows Terminal >= 1.22, foot, xterm, Konsole, mlterm,
contour).

Encoding is the cost on this path, so we lean on a property of our own
output: the plot uses about a dozen colours by design. A small fixed palette
plus a precomputed 32768-entry lookup table turns quantization into a single
array index instead of a nearest-neighbour search per pixel.

libsixel is used when importable; the numpy encoder is the fallback so the
sixel extra stays optional.
"""
from __future__ import annotations

import numpy as np

from specterm1d import theme

# Room for the theme's own colours plus the blends the antialiaser makes of
# them. Every entry costs a pass over each sixel band at encode time, so this
# is a ceiling rather than a target: the built-in themes come in well under
# it, and only a matplotlib style with a wide prop cycle approaches it.
MAX_COLORS = 32


def palette_for(palette: theme.Theme) -> np.ndarray:
    """The colours a theme can actually put on screen, most used first.

    The antialiaser blends every colour into whatever it is drawn on, and
    which ground that is depends on the role: the spectrum and its markers
    sit on the plot, the box and its numbers on the figure around it. Giving
    each blend the right ground is what keeps thin lines from fringing.
    """
    data = (palette.line, palette.sigma, palette.mask, palette.fit,
            palette.cursor, *palette.overlay)
    if palette.grid:
        data += (palette.grid_color,)
    chrome = (palette.spine, palette.tick_label, palette.text)
    entries = [palette.plot, palette.figure, *data, *chrome]
    entries += [theme.blend(color, palette.plot) for color in data]
    entries += [theme.blend(color, palette.figure) for color in chrome]

    from matplotlib.colors import to_rgb

    # Deduplicated at the lookup table's own five-bit resolution, not by exact
    # RGB: two colours inside one cell are one colour as far as quantization
    # is concerned, and keeping both would cost an encode pass to no effect.
    # The dark theme's sigma band and its line-into-background blend are that
    # pair. Roles come before blends, so the role keeps the cell.
    seen: dict[tuple[int, int, int], tuple[int, int, int]] = {}
    for color in entries:
        rgb = tuple(round(v * 255) for v in to_rgb(color))
        seen.setdefault(tuple(v >> 3 for v in rgb), rgb)  # type: ignore[arg-type]
    return np.array(list(seen.values())[:MAX_COLORS], dtype=np.int32)


def build_lut(palette: np.ndarray) -> np.ndarray:
    """Nearest palette index for every 5-bit-per-channel RGB cell."""
    axis = np.arange(32, dtype=np.int32) * 8 + 4
    grid = np.stack(np.meshgrid(axis, axis, axis, indexing="ij"), axis=-1)
    grid = grid.reshape(-1, 3)
    distance = ((grid[:, None, :] - palette[None, :, :]) ** 2).sum(axis=-1)
    return distance.argmin(axis=1).astype(np.uint8)


# One LUT per theme, kept for as long as the process runs: building one is a
# 32768-row argmin, cheap once and wasteful every frame.
_LUTS: dict[theme.Theme, tuple[np.ndarray, np.ndarray]] = {}


def palette_and_lut(palette: theme.Theme | None = None):
    """The active theme's palette and its lookup table, built once."""
    palette = theme.active() if palette is None else palette
    entry = _LUTS.get(palette)
    if entry is None:
        colors = palette_for(palette)
        entry = _LUTS[palette] = (colors, build_lut(colors))
    return entry


def quantize_palette(rgb: np.ndarray, lut: np.ndarray | None = None) -> np.ndarray:
    lut = palette_and_lut()[1] if lut is None else lut
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
        for char, run in zip(chars, lengths.tolist(), strict=True)
    ])


def encode_sixel(indexed: np.ndarray, palette: np.ndarray | None = None) -> str:
    palette = palette_and_lut()[0] if palette is None else palette
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
    inline_graphics = True

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
            colors, lut = palette_and_lut()
            text = encode_sixel(quantize_palette(rgba[..., :3], lut), colors)
        self.out.write(f"\x1b[{rect.row + 1};{rect.col + 1}H")
        self.out.write(text)
        self.out.flush()

    def teardown(self) -> None:
        pass
