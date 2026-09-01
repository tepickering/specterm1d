# tests/test_text.py
import io
import itertools

import numpy as np

from specterm1d.term.base import CellRect
from specterm1d.term.text import (
    GLYPHS,
    TextRenderer,
    cells_from_rgba,
    quantize_256,
    render_cells,
)


def _cell(tl, tr, bl, br):
    """One cell's four subpixels, as greyscale levels."""
    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    for (row, col), value in zip(((0, 0), (0, 1), (1, 0), (1, 1)),
                                 (tl, tr, bl, br), strict=True):
        rgba[row, col, :3] = value
    return cells_from_rgba(rgba)[0, 0]


def _glyph(cell):
    return GLYPHS[int(cell[6])]


def test_cells_pack_a_2x2_pixel_block_into_one_cell():
    rgba = np.zeros((8, 6, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    assert cells_from_rgba(rgba).shape == (4, 3, 7)


def test_odd_pixel_dimensions_are_truncated_to_whole_cells():
    rgba = np.zeros((9, 7, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    assert cells_from_rgba(rgba).shape == (4, 3, 7)


def test_a_flat_cell_becomes_a_blank_with_no_foreground_of_its_own():
    cell = _cell(90, 90, 90, 90)
    assert _glyph(cell) == " "
    # Foreground tracks the background so a run of blanks emits no colour churn.
    assert cell[:3].tolist() == cell[3:6].tolist() == [90, 90, 90]


def test_each_two_way_split_picks_its_own_glyph():
    # Foreground is the bright group in every case; the two diagonals share a
    # glyph because one is the other with the colours swapped.
    assert _glyph(_cell(255, 0, 0, 0)) == "▘"
    assert _glyph(_cell(0, 255, 0, 0)) == "▝"
    assert _glyph(_cell(255, 255, 0, 0)) == "▀"
    assert _glyph(_cell(0, 0, 255, 0)) == "▖"
    assert _glyph(_cell(255, 0, 255, 0)) == "▌"
    assert _glyph(_cell(0, 255, 255, 0)) == "▞"
    assert _glyph(_cell(255, 255, 255, 0)) == "▛"
    assert _glyph(_cell(255, 0, 0, 255)) == "▞"


def test_the_lower_right_subpixel_is_always_the_background():
    # Which is what makes eight glyphs enough: the other eight masks are these
    # with foreground and background exchanged.
    cell = _cell(0, 0, 0, 255)
    assert _glyph(cell) == "▛"
    assert cell[:3].tolist() == [0, 0, 0]
    assert cell[3:6].tolist() == [255, 255, 255]


def test_a_two_colour_cell_is_reproduced_exactly():
    cell = _cell(200, 200, 30, 30)
    assert _glyph(cell) == "▀"
    assert cell[:3].tolist() == [200, 200, 200]
    assert cell[3:6].tolist() == [30, 30, 30]


def test_a_group_of_unequal_subpixels_takes_their_mean():
    cell = _cell(200, 210, 30, 30)
    assert _glyph(cell) == "▀"
    assert cell[:3].tolist() == [205, 205, 205]


def _best_error(subpixels):
    """Smallest squared error any two-colour split of a cell can achieve."""
    best = None
    for mask in range(16):
        groups = [[p for i, p in enumerate(subpixels) if (mask >> i & 1) == bit]
                  for bit in (1, 0)]
        error = sum(float(np.square(np.array(g) - np.mean(g, axis=0)).sum())
                    for g in groups if g)
        best = error if best is None else min(best, error)
    return best


def test_the_chosen_split_is_the_best_of_all_sixteen():
    rng = np.random.default_rng(20260901)
    rgba = np.zeros((20, 20, 4), dtype=np.uint8)
    rgba[..., :3] = rng.integers(0, 256, size=(20, 20, 3), dtype=np.uint8)
    rgba[..., 3] = 255
    cells = cells_from_rgba(rgba)

    for row, col in itertools.product(range(10), range(10)):
        block = rgba[2 * row:2 * row + 2, 2 * col:2 * col + 2, :3].astype(float)
        subpixels = [block[0, 0], block[0, 1], block[1, 0], block[1, 1]]
        cell = cells[row, col].astype(float)
        fg, bg = cell[:3], cell[3:6]
        mask = int(cell[6])
        chosen = sum(
            float(np.square(sub - (fg if mask >> i & 1 else bg)).sum())
            for i, sub in enumerate(subpixels)
        )
        # Rounding the means to whole bytes costs at most half a level per
        # channel per subpixel, so the chosen split may miss by a little.
        assert chosen <= _best_error(subpixels) + 4 * 3 * 0.25


def test_render_cells_draws_the_glyph_named_by_the_seventh_channel():
    cells = np.zeros((1, 3, 7), dtype=np.uint8)
    cells[0, :, 6] = [0, 3, 7]
    out = render_cells(cells, glyphs=GLYPHS)
    assert out.endswith(" ▀▛\x1b[0m")


def test_a_glyph_change_alone_redraws_the_cell():
    prev = np.zeros((2, 2, 7), dtype=np.uint8)
    cells = prev.copy()
    cells[1, 1, 6] = 5
    out = render_cells(cells, prev=prev, glyphs=GLYPHS)
    assert "\x1b[2;2H" in out
    assert "▌" in out


def test_the_indexed_colour_path_ignores_the_glyph_channel():
    # quantize_256 reshapes the colour channels, so a seventh one must not
    # reach it.
    cells = np.zeros((1, 1, 7), dtype=np.uint8)
    cells[0, 0] = [255, 255, 255, 0, 0, 0, 3]
    out = render_cells(cells, truecolor=False, glyphs=GLYPHS)
    assert "\x1b[38;5;231m" in out
    assert "\x1b[48;5;16m" in out
    assert out.endswith("▀\x1b[0m")


def test_target_pixels_is_two_per_cell_in_both_directions():
    renderer = TextRenderer(out=io.StringIO())
    assert renderer.target_pixels(rows=43, cols=116) == (232, 86)


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


def test_render_cells_positions_with_one_based_coordinates():
    out = render_cells(np.zeros((1, 1, 7), dtype=np.uint8), origin=(5, 9))
    assert "\x1b[5;9H" in out


def test_frame_diffing_shrinks_the_payload_by_orders_of_magnitude():
    prev = np.zeros((50, 200, 7), dtype=np.uint8)
    cells = prev.copy()
    cells[10, 10] = [255, 255, 255, 0, 0, 0, 3]
    full = len(render_cells(cells))
    diffed = len(render_cells(cells, prev=prev))
    assert diffed < full / 100


def test_shape_change_forces_a_full_redraw():
    prev = np.zeros((4, 8, 7), dtype=np.uint8)
    cells = np.zeros((4, 9, 7), dtype=np.uint8)
    cells[..., 6] = 3
    assert render_cells(cells, prev=prev).count("▀") == 36


def _checkerboard(rows_px, cols_px):
    rgba = np.zeros((rows_px, cols_px, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    rgba[0::2, 0::2, :3] = 255
    return rgba


def test_draw_crops_to_the_cell_rect():
    stream = io.StringIO()
    TextRenderer(out=stream).draw(_checkerboard(20, 30),
                                      CellRect(row=0, col=0, rows=4, cols=5))
    assert stream.getvalue().count("▘") == 20


def test_a_second_identical_draw_emits_nothing():
    stream = io.StringIO()
    renderer = TextRenderer(out=stream)
    rect = CellRect(row=0, col=0, rows=10, cols=15)
    renderer.draw(_checkerboard(20, 30), rect)
    stream.truncate(0)
    stream.seek(0)
    renderer.draw(_checkerboard(20, 30), rect)
    assert "▘" not in stream.getvalue()


def test_teardown_forces_the_next_draw_to_be_full():
    stream = io.StringIO()
    renderer = TextRenderer(out=stream)
    rect = CellRect(row=0, col=0, rows=10, cols=15)
    renderer.draw(_checkerboard(20, 30), rect)
    renderer.teardown()
    stream.truncate(0)
    stream.seek(0)
    renderer.draw(_checkerboard(20, 30), rect)
    assert stream.getvalue().count("▘") == 150


def test_the_renderer_asks_for_text_chrome():
    # The pixel budget is still far too small for matplotlib's own labels.
    assert TextRenderer(out=io.StringIO()).text_chrome is True
