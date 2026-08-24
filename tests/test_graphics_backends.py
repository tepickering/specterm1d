# tests/test_graphics_backends.py
import base64
import io
import re

import numpy as np
import pytest

from specterm1d.term.base import CellRect
from specterm1d.term.iterm2 import ITerm2Renderer
from specterm1d.term.kitty import KittyRenderer, kitty_chunks, png_bytes
from specterm1d.term.sixel import (
    PALETTE, SixelRenderer, build_lut, encode_sixel, quantize_palette,
)


def _rgba(h=8, w=8, value=64):
    a = np.full((h, w, 4), value, dtype=np.uint8)
    a[..., 3] = 255
    return a


def _caps(rows=24, cols=80, xp=800, yp=480):
    from specterm1d.term.caps import TerminalCaps
    return TerminalCaps(kitty=True, iterm2=True, sixel=True, truecolor=True,
                        rows=rows, cols=cols, pixel_width=xp, pixel_height=yp,
                        is_tty=True)


# ---- PNG transport -------------------------------------------------

def test_png_bytes_has_a_png_signature():
    assert png_bytes(_rgba()).startswith(b"\x89PNG\r\n\x1a\n")


def test_png_is_dramatically_smaller_than_raw_rgb():
    rgba = _rgba(700, 1200)
    assert len(png_bytes(rgba)) < rgba[..., :3].nbytes / 10


# ---- kitty ---------------------------------------------------------

def test_kitty_first_chunk_carries_the_control_keys():
    chunks = list(kitty_chunks(b"x" * 10, image_id=7, cols=40, rows=20))
    assert "a=T" in chunks[0] and "f=100" in chunks[0]
    assert "i=7" in chunks[0] and "c=40" in chunks[0] and "r=20" in chunks[0]


def test_kitty_later_chunks_carry_only_the_continuation_flag():
    chunks = list(kitty_chunks(b"x" * 20000, image_id=1, cols=1, rows=1))
    assert len(chunks) > 1
    assert "a=T" not in chunks[1]
    assert chunks[1].startswith("\x1b_Gm=")


def test_kitty_final_chunk_sets_m_zero():
    chunks = list(kitty_chunks(b"x" * 20000, image_id=1, cols=1, rows=1))
    assert "m=0" in chunks[-1]
    assert all("m=1" in c for c in chunks[:-1])


def test_kitty_chunks_reassemble_to_the_original_payload():
    payload = bytes(range(256)) * 40
    chunks = list(kitty_chunks(payload, image_id=1, cols=1, rows=1))
    body = "".join(c.split(";", 1)[1].removesuffix("\x1b\\") for c in chunks)
    assert base64.b64decode(body) == payload


def test_kitty_chunk_payloads_respect_the_size_limit():
    chunks = list(kitty_chunks(b"x" * 50000, image_id=1, cols=1, rows=1))
    for c in chunks:
        assert len(c.split(";", 1)[1].removesuffix("\x1b\\")) <= 4096


def test_kitty_renderer_positions_before_drawing():
    out = io.StringIO()
    KittyRenderer(out, _caps()).draw(_rgba(), CellRect(row=3, col=5, rows=10, cols=20))
    assert "\x1b[4;6H" in out.getvalue()


def test_kitty_target_pixels_uses_the_window_pixel_size():
    renderer = KittyRenderer(io.StringIO(), _caps(rows=24, cols=80, xp=800, yp=480))
    # 24 rows tall window, asking for the 22-row plot area.
    width, height = renderer.target_pixels(rows=22, cols=80)
    assert width == 800
    assert height == pytest.approx(480 * 22 / 24, rel=0.02)


def test_kitty_falls_back_to_a_nominal_cell_size_when_unreported():
    from specterm1d.term.caps import TerminalCaps
    caps = TerminalCaps(True, False, False, True, 24, 80, None, None, True)
    width, height = KittyRenderer(io.StringIO(), caps).target_pixels(22, 80)
    assert width > 0 and height > 0


def test_kitty_teardown_deletes_the_placed_image():
    out = io.StringIO()
    renderer = KittyRenderer(out, _caps(), image_id=9)
    renderer.draw(_rgba(), CellRect(0, 0, 4, 4))
    out.truncate(0)
    out.seek(0)
    renderer.teardown()
    assert "a=d" in out.getvalue() and "i=9" in out.getvalue()


# ---- iTerm2 --------------------------------------------------------

def test_iterm2_emits_an_osc_1337_file_sequence():
    out = io.StringIO()
    ITerm2Renderer(out, _caps()).draw(_rgba(), CellRect(0, 0, 10, 20))
    text = out.getvalue()
    assert "\x1b]1337;File=" in text
    assert "inline=1" in text
    assert text.endswith("\x07") or "\x07" in text


def test_iterm2_payload_is_valid_base64_png():
    out = io.StringIO()
    ITerm2Renderer(out, _caps()).draw(_rgba(), CellRect(0, 0, 10, 20))
    body = re.search(r"\x1b]1337;File=[^:]*:([A-Za-z0-9+/=]+)\x07",
                     out.getvalue()).group(1)
    assert base64.b64decode(body).startswith(b"\x89PNG")


# ---- sixel ---------------------------------------------------------

def test_lut_covers_the_whole_rgb_cube():
    lut = build_lut(PALETTE)
    assert lut.shape == (32768,)
    assert lut.max() < len(PALETTE)


def test_quantize_maps_palette_colours_to_themselves():
    lut = build_lut(PALETTE)
    idx = quantize_palette(PALETTE.astype(np.uint8), lut)
    assert idx.tolist() == list(range(len(PALETTE)))


def test_encode_sixel_has_the_expected_envelope():
    indexed = np.zeros((12, 10), dtype=np.uint8)
    out = encode_sixel(indexed, PALETTE)
    assert out.startswith("\x1bPq")
    assert out.endswith("\x1b\\")
    assert '"1;1;10;12' in out


def test_encode_sixel_declares_every_palette_entry():
    out = encode_sixel(np.zeros((6, 6), dtype=np.uint8), PALETTE)
    for i in range(len(PALETTE)):
        assert f"#{i};2;" in out


def test_encode_sixel_emits_one_band_terminator_per_six_rows():
    out = encode_sixel(np.zeros((18, 4), dtype=np.uint8), PALETTE)
    assert out.count("-") == 3


def test_encode_sixel_run_length_encodes_long_runs():
    narrow = encode_sixel(np.zeros((6, 200), dtype=np.uint8), PALETTE)
    wide = encode_sixel(np.zeros((6, 2000), dtype=np.uint8), PALETTE)
    assert "!200~" in narrow and "!2000~" in wide
    assert "~~~~" not in narrow          # nothing was emitted literally
    # Ten times the pixels costs two characters, not eighteen hundred. The
    # rest of the sequence is the fixed palette preamble.
    assert len(wide) - len(narrow) <= 2


def test_encode_sixel_separates_colours_within_a_band():
    indexed = np.zeros((6, 10), dtype=np.uint8)
    indexed[:, 5:] = 1
    out = encode_sixel(indexed, PALETTE)
    assert "$" in out


def test_sixel_renderer_writes_a_complete_sequence():
    out = io.StringIO()
    SixelRenderer(out, _caps()).draw(_rgba(12, 10), CellRect(0, 0, 2, 10))
    text = out.getvalue()
    assert "\x1bPq" in text and text.rstrip().endswith("\x1b\\")


def test_all_three_backends_are_registered():
    import specterm1d.term  # noqa: F401
    from specterm1d.term.caps import _FACTORIES
    assert {"kitty", "iterm2", "sixel", "halfblock"} <= set(_FACTORIES)
