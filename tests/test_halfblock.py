# tests/test_halfblock.py
import io

import numpy as np

from specterm1d.term.base import CellRect
from specterm1d.term.halfblock import (
    HalfblockRenderer,
    cells_from_rgba,
    quantize_256,
    render_cells,
)

UPPER_HALF = "▀"


def _rgba(rows_px, cols_px, fill=0):
    a = np.full((rows_px, cols_px, 4), fill, dtype=np.uint8)
    a[..., 3] = 255
    return a


def test_cells_pack_two_pixel_rows_into_one_cell():
    rgba = _rgba(4, 3)
    rgba[0::2, :, :3] = 10      # top pixels of each cell
    rgba[1::2, :, :3] = 200     # bottom pixels
    cells = cells_from_rgba(rgba)
    assert cells.shape == (2, 3, 6)
    assert cells[0, 0, :3].tolist() == [10, 10, 10]     # foreground
    assert cells[0, 0, 3:].tolist() == [200, 200, 200]  # background


def test_odd_pixel_height_is_truncated_to_whole_cells():
    cells = cells_from_rgba(_rgba(5, 3))
    assert cells.shape == (2, 3, 6)


def test_quantize_256_maps_black_and_white_to_cube_ends():
    codes = quantize_256(np.array([[0, 0, 0], [255, 255, 255]], dtype=np.uint8))
    assert codes[0] == 16
    assert codes[1] == 231


def test_quantize_256_prefers_the_grey_ramp_for_neutral_colours():
    # 128,128,128 is closer to a grey-ramp entry than to any 6x6x6 cube entry.
    code = quantize_256(np.array([128, 128, 128], dtype=np.uint8))
    assert 232 <= int(code) <= 255


def test_quantize_256_preserves_input_shape():
    codes = quantize_256(np.zeros((4, 5, 2, 3), dtype=np.uint8))
    assert codes.shape == (4, 5, 2)


def test_render_cells_emits_one_glyph_per_cell():
    cells = np.zeros((2, 3, 6), dtype=np.uint8)
    out = render_cells(cells)
    assert out.count(UPPER_HALF) == 6


def test_render_cells_uses_truecolor_sequences():
    cells = np.zeros((1, 1, 6), dtype=np.uint8)
    cells[0, 0] = [10, 20, 30, 40, 50, 60]
    out = render_cells(cells, truecolor=True)
    assert "\x1b[38;2;10;20;30m" in out
    assert "\x1b[48;2;40;50;60m" in out


def test_render_cells_uses_indexed_sequences_when_not_truecolor():
    cells = np.zeros((1, 1, 6), dtype=np.uint8)
    out = render_cells(cells, truecolor=False)
    assert "\x1b[38;5;" in out
    assert "\x1b[48;2;" not in out


def test_render_cells_positions_with_one_based_coordinates():
    cells = np.zeros((1, 1, 6), dtype=np.uint8)
    out = render_cells(cells, origin=(5, 9))
    assert "\x1b[5;9H" in out


def test_unchanged_frame_emits_no_glyphs():
    cells = np.zeros((4, 8, 6), dtype=np.uint8)
    out = render_cells(cells, prev=cells.copy())
    assert UPPER_HALF not in out


def test_single_changed_cell_emits_only_that_cell():
    prev = np.zeros((4, 8, 6), dtype=np.uint8)
    cells = prev.copy()
    cells[2, 5] = [1, 2, 3, 4, 5, 6]
    out = render_cells(cells, prev=prev)
    assert out.count(UPPER_HALF) == 1
    assert "\x1b[3;6H" in out


def test_frame_diffing_shrinks_the_payload_by_orders_of_magnitude():
    prev = np.zeros((50, 200, 6), dtype=np.uint8)
    cells = prev.copy()
    cells[10, 10] = [255, 255, 255, 0, 0, 0]
    full = len(render_cells(cells))
    diffed = len(render_cells(cells, prev=prev))
    assert diffed < full / 100


def test_shape_change_forces_a_full_redraw():
    prev = np.zeros((4, 8, 6), dtype=np.uint8)
    cells = np.zeros((4, 9, 6), dtype=np.uint8)
    out = render_cells(cells, prev=prev)
    assert out.count(UPPER_HALF) == 36


def test_renderer_target_pixels_is_two_per_cell_row():
    renderer = HalfblockRenderer(out=io.StringIO())
    assert renderer.target_pixels(rows=50, cols=200) == (200, 100)


def test_renderer_draw_writes_to_its_stream():
    stream = io.StringIO()
    renderer = HalfblockRenderer(out=stream)
    renderer.draw(_rgba(20, 30), CellRect(row=0, col=0, rows=10, cols=30))
    assert UPPER_HALF in stream.getvalue()


def test_renderer_draw_crops_to_the_cell_rect():
    stream = io.StringIO()
    renderer = HalfblockRenderer(out=stream)
    renderer.draw(_rgba(20, 30), CellRect(row=0, col=0, rows=4, cols=5))
    assert stream.getvalue().count(UPPER_HALF) == 20


def test_second_identical_draw_emits_almost_nothing():
    stream = io.StringIO()
    renderer = HalfblockRenderer(out=stream)
    rect = CellRect(row=0, col=0, rows=10, cols=30)
    renderer.draw(_rgba(20, 30), rect)
    stream.truncate(0)
    stream.seek(0)
    renderer.draw(_rgba(20, 30), rect)
    assert UPPER_HALF not in stream.getvalue()


def test_teardown_forces_the_next_draw_to_be_full():
    stream = io.StringIO()
    renderer = HalfblockRenderer(out=stream)
    rect = CellRect(row=0, col=0, rows=10, cols=30)
    renderer.draw(_rgba(20, 30), rect)
    renderer.teardown()
    stream.truncate(0)
    stream.seek(0)
    renderer.draw(_rgba(20, 30), rect)
    assert stream.getvalue().count(UPPER_HALF) == 300
