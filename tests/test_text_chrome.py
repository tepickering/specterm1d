# tests/test_text_chrome.py
"""Axis decoration drawn as terminal text rather than into the figure.

At block-glyph resolution a 116x43 terminal gives a 232x86 pixel figure,
where a tick label is a 5.6 px smear across three cells. The terminal draws the same
digits as crisp native glyphs, so in this mode the figure carries only data.
"""
import numpy as np
import pytest

from specterm1d.plot import tick_values
from specterm1d.term.base import CellRect
from specterm1d.term.chrome import ChromeLayout, layout_for, render_chrome

# ---- tick_values -------------------------------------------------------

def test_tick_values_lie_inside_the_range():
    values, labels = tick_values(6660.0, 6780.0, 4)
    assert len(values) == len(labels) > 1
    assert all(6660.0 <= v <= 6780.0 for v in values)


def test_tick_values_are_round_numbers():
    values, _ = tick_values(0.0, 100.0, 5)
    assert all(v == pytest.approx(round(v)) for v in values)


def test_tick_labels_are_formatted_strings():
    _, labels = tick_values(6660.0, 6780.0, 4)
    assert all(isinstance(text, str) and text.strip() for text in labels)
    assert any("6" in text for text in labels)


def test_tick_values_survive_a_degenerate_range():
    # An empty spectrum can autoscale to a zero-width range; a locator that
    # raises here would take the whole render down.
    values, labels = tick_values(5.0, 5.0, 4)
    assert len(values) == len(labels)


def test_tick_labels_stay_short_for_large_numbers():
    # Six digits of wavelength in a six-column gutter is the whole budget;
    # matplotlib's offset notation is what keeps it inside.
    _, labels = tick_values(1234560.0, 1234600.0, 4)
    assert max(len(text) for text in labels) <= 8


# ---- layout ------------------------------------------------------------

def test_layout_reserves_a_gutter_and_an_axis_row():
    outer = CellRect(row=0, col=0, rows=41, cols=116)
    layout = layout_for(outer, ["100", "200", "300"], title=True)
    assert layout.plot.cols < outer.cols
    assert layout.plot.rows < outer.rows
    assert layout.plot.col > 0            # gutter on the left
    assert layout.plot.row > 0            # title row on top


def test_gutter_fits_the_widest_y_label():
    outer = CellRect(row=0, col=0, rows=41, cols=116)
    narrow = layout_for(outer, ["0", "1"], title=True)
    wide = layout_for(outer, ["-1.234e5", "0"], title=True)
    assert wide.plot.col > narrow.plot.col


def test_layout_degrades_rather_than_going_negative():
    # A pathologically small window must still produce a drawable rect.
    outer = CellRect(row=0, col=0, rows=2, cols=4)
    layout = layout_for(outer, ["-1.234e5"], title=True)
    assert layout.plot.rows >= 1 and layout.plot.cols >= 1


def test_layout_at_tims_terminal_gives_the_curve_more_pixels_than_before():
    # 116x43 leaves 41 rows for the plot. The matplotlib chrome it replaces
    # spent 17% of the width and 17% of the height on margins.
    outer = CellRect(row=0, col=0, rows=41, cols=116)
    layout = layout_for(outer, ["0", "180", "360"], title=True)
    assert layout.plot.cols >= 106
    assert layout.plot.rows * 2 >= 76


# ---- rendering ---------------------------------------------------------

def make_layout(rows=41, cols=116, labels=("0", "180", "360")):
    return layout_for(CellRect(row=0, col=0, rows=rows, cols=cols),
                      list(labels), title=True)


def test_render_chrome_writes_the_y_labels_into_the_gutter():
    layout = make_layout()
    text = render_chrome(layout, (0.0, 100.0), (0.0, 360.0),
                         xticks=([50.0], ["50"]),
                         yticks=([0.0, 180.0, 360.0], ["0", "180", "360"]),
                         title="")
    assert "180" in text and "360" in text


def test_render_chrome_writes_the_x_labels_on_the_axis_row():
    layout = make_layout()
    text = render_chrome(layout, (6660.0, 6780.0), (0.0, 1.0),
                         xticks=([6700.0], ["6700"]),
                         yticks=([0.0], ["0"]), title="")
    assert "6700" in text


def test_render_chrome_draws_the_axis_frame():
    layout = make_layout()
    text = render_chrome(layout, (0.0, 1.0), (0.0, 1.0),
                         xticks=([0.5], ["0.5"]), yticks=([0.5], ["0.5"]),
                         title="")
    assert "│" in text          # left spine
    assert "└" in text          # corner
    assert "─" in text          # bottom spine


def test_render_chrome_elides_a_title_too_wide_for_the_terminal():
    layout = make_layout(cols=40)
    title = "spec1d_UVES.2001-08-11T02:37:04.577-OBJECT_VLT_UVES_red.fits  OBJ0042"
    text = render_chrome(layout, (0.0, 1.0), (0.0, 1.0), xticks=([], []),
                         yticks=([], []), title=title)
    assert title not in text
    assert "…" in text


def test_render_chrome_drops_labels_that_would_not_fit():
    # Ticks crowd together at small widths; a label that would overlap its
    # neighbour is dropped rather than printed on top of it.
    layout = make_layout(cols=30)
    values = list(np.linspace(0.0, 1.0, 12))
    labels = [f"{v:.3f}" for v in values]
    text = render_chrome(layout, (0.0, 1.0), (0.0, 1.0),
                         xticks=(values, labels), yticks=([], []), title="")
    assert sum(text.count(text_label) for text_label in labels) < len(labels)


def test_render_chrome_stays_inside_its_rect():
    # Every cursor-position escape must land inside the terminal, or the
    # chrome scribbles over the status line.
    import re

    rows, cols = 41, 116
    layout = make_layout(rows=rows, cols=cols)
    text = render_chrome(layout, (6660.0, 6780.0), (0.0, 360.0),
                         xticks=([6660.0, 6720.0, 6780.0],
                                 ["6660", "6720", "6780"]),
                         yticks=([0.0, 180.0, 360.0], ["0", "180", "360"]),
                         title="a title")
    positions = re.findall(r"\x1b\[(\d+);(\d+)H", text)
    assert positions
    for row, col in positions:
        assert 1 <= int(row) <= rows
        assert 1 <= int(col) <= cols


def test_layout_is_a_dataclass_carrying_its_outer_rect():
    layout = make_layout()
    assert isinstance(layout, ChromeLayout)
    assert layout.outer.cols == 116


# ---- axis labels -------------------------------------------------------

def test_axis_labels_are_placed_when_they_fit():
    layout = make_layout()
    text = render_chrome(layout, (6660.0, 6780.0), (0.0, 360.0),
                         xticks=([6700.0], ["6700"]),
                         yticks=([180.0], ["180"]), title="obj",
                         xlabel="Angstrom", ylabel="Flux (counts)")
    assert "Angstrom" in text
    assert "Flux (counts)" in text


def test_axis_labels_are_dropped_rather_than_overlapping():
    # A narrow window spends every column on tick labels; the axis label is
    # the first thing to go, because a collision would corrupt both.
    layout = make_layout(cols=26)
    values = [6660.0, 6700.0, 6740.0, 6780.0]
    text = render_chrome(layout, (6660.0, 6780.0), (0.0, 360.0),
                         xticks=(values, [f"{v:.0f}" for v in values]),
                         yticks=([180.0], ["180"]),
                         title="a very long title indeed",
                         xlabel="Angstrom", ylabel="Flux (counts)")
    assert "Angstrom" not in text
    assert "Flux (counts)" not in text


def test_the_legend_takes_precedence_over_the_y_axis_label():
    layout = make_layout()
    text = render_chrome(layout, (0.0, 1.0), (0.0, 1.0), xticks=([], []),
                         yticks=([], []), title="obj",
                         legend=[("sigma", "#e0a030")], ylabel="Flux (counts)")
    assert "sigma" in text
    assert "Flux (counts)" not in text


# ---- the image and the drawn axis must agree ---------------------------

def test_a_click_lands_where_the_drawn_axis_says_it_does():
    """The chrome and the cursor must share one mapping.

    The gutter shifts the image right by ``plot.col`` columns. If the cursor
    mapping kept using the full-width rect, every measurement would be offset
    by the gutter width without anything looking wrong on screen.
    """
    from specterm1d.term.chrome import _cell_for
    from tests.test_session import make_session

    session, _ = make_session()
    if not session.text_chrome:
        pytest.skip("renderer draws its own chrome")

    layout = session.chrome_layout()
    xlo, xhi = session.view.xlim
    values, _ = session.x_ticks(layout.plot.cols)

    for value in values:
        col = _cell_for(value, xlo, xhi, layout.plot.col, layout.plot.cols)
        session.view.cursor_x = None
        session.on_mouse(col=col + 1, row=layout.plot.row + 2)
        assert session.view.cursor_x is not None
        # One cell of the visible range is the resolution the user has.
        assert abs(session.view.cursor_x - value) <= (xhi - xlo) / layout.plot.cols


# ---- log axes ----------------------------------------------------------

def test_log_tick_values_are_decades():
    values, labels = tick_values(1e-19, 1.2e-13, 4, log=True)
    assert len(values) >= 2
    assert all(np.log10(v) == pytest.approx(round(np.log10(v))) for v in values)
    assert labels[0] == "1e-19"


def test_log_tick_values_fall_back_inside_a_single_decade():
    # No whole decade lies in 3e-14 .. 9e-14, and a locator that returned
    # nothing would leave the terminal's y gutter blank.
    values, labels = tick_values(3e-14, 9e-14, 4, log=True)
    assert len(values) >= 2
    assert len(values) <= 5
    assert all("e-14" in text for text in labels)


def test_log_tick_values_lie_inside_the_range():
    values, _ = tick_values(2e-17, 5e-14, 4, log=True)
    assert all(2e-17 <= v <= 5e-14 for v in values)


def test_log_tick_values_survive_a_non_positive_lower_limit():
    values, _ = tick_values(0.0, 100.0, 4, log=True)
    assert all(v > 0 for v in values)


def test_a_log_tick_lands_at_the_cell_the_curve_occupies():
    from specterm1d.term.chrome import _cell_for

    # A decade halfway up a two-decade window belongs in the middle row, not
    # a hundredth of the way from the top where a linear map would put it.
    row = _cell_for(10.0, 1.0, 100.0, start=0, size=21, invert=True, log=True)
    assert row == 10
    assert _cell_for(10.0, 1.0, 100.0, start=0, size=21, invert=True) == 18


def _placements(text):
    """(row, col, payload) for each positioned write in a chrome string."""
    import re

    return [(int(m.group(1)) - 1, int(m.group(2)) - 1, m.group(3))
            for m in re.finditer(
                r"\x1b\[(\d+);(\d+)H(?:\x1b\[[0-9;]*m)*([^\x1b]*)", text)]


def test_render_chrome_places_log_labels_by_decade():
    layout = layout_for(CellRect(row=0, col=0, rows=22, cols=80), ["1e-19"])
    text = render_chrome(layout, (1.0, 100.0), (1e-19, 1e-13),
                         xticks=([1.0, 10.0, 100.0], ["1", "10", "100"]),
                         yticks=([1e-19, 1e-16, 1e-13],
                                 ["1e-19", "1e-16", "1e-13"]),
                         xlog=True, ylog=True)
    rows = sorted(row for row, _, payload in _placements(text)
                  if payload.strip() in ("1e-19", "1e-16", "1e-13"))
    # Three decades evenly spaced apart is what three evenly spaced decades
    # should look like; on a linear map they would pile up at one end.
    assert len(rows) == 3
    assert (rows[1] - rows[0]) == (rows[2] - rows[1]) > 0


def test_render_chrome_spaces_log_x_labels_by_decade():
    layout = layout_for(CellRect(row=0, col=0, rows=22, cols=80), ["1"])
    text = render_chrome(layout, (1.0, 100.0), (0.0, 1.0),
                         xticks=([1.0, 10.0, 100.0], ["1", "10", "100"]),
                         yticks=([0.0, 1.0], ["0", "1"]),
                         xlog=True)
    cols = sorted(col for row, col, payload in _placements(text)
                  if row == layout.label_row and payload.strip()
                  in ("1", "10", "100"))
    assert len(cols) == 3
    # "10" sits in the middle of the axis, give or take its own half-width.
    assert abs((cols[1] - cols[0]) - (cols[2] - cols[1])) <= 2


def test_log_tick_labels_do_not_mix_plain_and_exponent_forms():
    # %g crosses over partway up a wide range, putting 100000 and 1e+06 in
    # the same gutter - ragged, and a column wider than either style alone.
    _, labels = tick_values(1e2, 1e7, 6, log=True)
    assert all("e" in text for text in labels), labels
    assert max(len(text) for text in labels) <= 5


def test_log_tick_labels_stay_plain_where_they_can():
    _, labels = tick_values(1.0, 100.0, 4, log=True)
    assert "1" in labels and "100" in labels
