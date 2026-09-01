# tests/test_theme.py
import io

import numpy as np
import pytest

from specterm1d import theme
from specterm1d.cli import build_parser, main
from specterm1d.plot import PlotRequest, SpectrumPlot
from specterm1d.spec import build_spec
from specterm1d.term.base import CellRect
from specterm1d.term.chrome import layout_for, render_chrome
from specterm1d.term.sixel import build_lut, palette_for, quantize_palette

# ---- the theme registry ---------------------------------------------

def test_xgterm_is_the_default():
    assert theme.DEFAULT is theme.XGTERM
    assert theme.active().name == "xgterm"


def test_xgterm_carries_the_iraf_colours():
    t = theme.XGTERM
    assert (t.figure, t.plot) == ("#2f4f4f", "#000000")
    assert (t.spine, t.tick_label, t.text) == ("#00ffff", "#ffff00", "#00ff00")
    assert t.line == "#ffffff"


def test_dark_paints_the_whole_decoration_one_colour():
    t = theme.DARK
    assert t.spine == t.tick_label == t.text == "#c8d2dc"
    assert t.figure == t.plot


def test_resolve_takes_builtins_matplotlib_styles_and_themes():
    assert theme.resolve("dark") is theme.DARK
    assert theme.resolve(theme.XGTERM) is theme.XGTERM
    assert theme.resolve("ggplot").name == "ggplot"


def test_resolve_rejects_an_unknown_name():
    with pytest.raises(ValueError, match="unknown theme"):
        theme.resolve("no-such-theme")


def test_names_lists_ours_first_then_matplotlibs():
    names = theme.names()
    assert names[:2] == ("xgterm", "dark")
    assert "ggplot" in names and "dark_background" in names


def test_using_restores_the_previous_theme():
    with theme.using("dark"):
        assert theme.active() is theme.DARK
    assert theme.active() is theme.XGTERM


# ---- deriving a theme from a matplotlib style ------------------------

def test_mpl_style_supplies_the_grounds_and_the_text():
    t = theme.from_mpl_style("dark_background")
    assert t.figure == "#000000"
    assert t.plot == "#000000"
    assert t.text == "#ffffff"


def test_mpl_style_takes_the_line_and_overlays_from_the_prop_cycle():
    import matplotlib.style as mplstyle
    from matplotlib.colors import to_hex

    cycle = [to_hex(c) for c in
             mplstyle.library["ggplot"]["axes.prop_cycle"].by_key()["color"]]
    t = theme.from_mpl_style("ggplot")
    assert t.line == cycle[0]
    assert list(t.overlay) == cycle[1:4]


def test_mpl_sigma_is_the_line_blended_into_the_plot():
    t = theme.from_mpl_style("ggplot")
    assert t.sigma == theme.blend(t.line, t.plot)


def test_mpl_mask_is_the_warmest_colour_in_the_cycle():
    t = theme.from_mpl_style("tableau-colorblind10")
    from matplotlib.colors import to_rgb

    r, g, b = to_rgb(t.mask)
    assert r > g and r > b


def test_a_style_that_sets_almost_nothing_still_yields_every_role():
    # 'fast' only touches path simplification, so every colour comes from the
    # defaults; a partial style must not leave a role empty.
    t = theme.from_mpl_style("fast")
    for value in (t.figure, t.plot, t.spine, t.tick_label, t.text, t.line,
                  t.sigma, t.mask, t.fit, t.cursor, *t.overlay):
        assert value.startswith("#") and len(value) == 7


def test_every_theme_resolves_to_a_complete_palette():
    for name in theme.names():
        t = theme.resolve(name)
        assert len(t.overlay) == 3
        assert t.name == name


def test_blend_is_a_midpoint():
    assert theme.blend("#000000", "#ffffff") == "#808080"
    assert theme.blend("#000000", "#ffffff", 0.0) == "#000000"


# ---- the figure follows the active theme -----------------------------

def _request():
    spec = build_spec(np.linspace(4000, 9000, 500), np.ones(500))
    return PlotRequest(spec=spec, xlim=(4000.0, 9000.0), ylim=(0.0, 2.0))


def test_figure_and_axes_take_their_grounds_from_the_theme():
    with theme.using("xgterm"):
        plot = SpectrumPlot(640, 400)
        plot.draw(_request())
        assert plot.fig.get_facecolor()[:3] == pytest.approx(
            (0x2f / 255, 0x4f / 255, 0x4f / 255), abs=1 / 255)
        assert plot.ax.get_facecolor()[:3] == (0.0, 0.0, 0.0)


def test_tick_marks_and_tick_labels_can_differ():
    with theme.using("xgterm"):
        plot = SpectrumPlot(640, 400)
        plot.draw(_request())
        assert plot.ax.get_xticklabels()[0].get_color() == "#ffff00"
        assert plot.ax.xaxis.get_ticklines()[0].get_color() == "#00ffff"
        assert plot.ax.title.get_color() == "#00ff00"


def test_switching_theme_repaints_a_live_figure():
    plot = SpectrumPlot(320, 200)
    with theme.using("dark"):
        plot.draw(_request())
        dark = plot.fig.get_facecolor()
    with theme.using("xgterm"):
        plot.draw(_request())
        assert plot.fig.get_facecolor() != dark


# ---- the terminal chrome follows it too ------------------------------

def _chrome(truecolor=True):
    outer = CellRect(row=0, col=0, rows=12, cols=40)
    layout = layout_for(outer, ["2500", "2000"])
    return render_chrome(
        layout, (4000.0, 9000.0), (0.0, 2500.0),
        xticks=([5000.0, 8000.0], ["5000", "8000"]),
        yticks=([2000.0], ["2000"]),
        title="m51", truecolor=truecolor,
    )


def test_chrome_inks_the_box_and_the_numbers_differently():
    with theme.using("xgterm"):
        text = _chrome()
    # cyan box glyphs, yellow numbers, green title, all on the slate ground.
    assert "\x1b[38;2;0;255;255m\x1b[48;2;47;79;79m" in text
    assert "\x1b[38;2;255;255;0m\x1b[48;2;47;79;79m" in text
    assert "\x1b[38;2;0;255;0m\x1b[48;2;47;79;79m" in text


def test_chrome_grounds_itself_on_the_figure_not_the_plot():
    # xgterm's plot is black and its figure slate; the decoration sits outside
    # the box, so it must carry the slate.
    with theme.using("xgterm"):
        assert "48;2;0;0;0m" not in _chrome()


def test_chrome_paints_gutter_rows_that_carry_no_label():
    """Otherwise the terminal's own background shows through beside the box."""
    with theme.using("xgterm"):
        text = _chrome()
    assert "\x1b[38;2;255;255;0m\x1b[48;2;47;79;79m    " in text


def test_chrome_without_truecolor_falls_back_to_256_colours():
    with theme.using("xgterm"):
        text = _chrome(truecolor=False)
    assert "38;5;" in text and "38;2;" not in text


# ---- the sixel palette follows it as well ----------------------------

@pytest.mark.parametrize("name", ["xgterm", "dark", "ggplot",
                                  "dark_background", "grayscale"])
def test_every_palette_entry_survives_its_own_lookup_table(name):
    palette = palette_for(theme.resolve(name))
    assert len(palette) <= 32
    lut = build_lut(palette)
    idx = quantize_palette(palette.astype(np.uint8), lut)
    assert idx.tolist() == list(range(len(palette)))


def test_palette_leads_with_the_grounds_and_holds_every_role():
    palette = palette_for(theme.XGTERM)
    listed = {tuple(row) for row in palette.tolist()}
    assert palette[0].tolist() == [0, 0, 0]          # plot
    assert palette[1].tolist() == [0x2f, 0x4f, 0x4f]  # figure
    for hexcolor in ("#ffffff", "#00ffff", "#ffff00", "#00ff00", "#ff0000"):
        rgb = tuple(int(hexcolor[i:i + 2], 16) for i in (1, 3, 5))
        assert rgb in listed


def test_palette_drops_colours_the_lookup_table_cannot_tell_apart():
    # dark's sigma band and its line blended into the background land in one
    # five-bit cell; carrying both would cost an encode pass for nothing.
    palette = palette_for(theme.DARK)
    cells = [tuple(v >> 3 for v in row) for row in palette.tolist()]
    assert len(cells) == len(set(cells))


def test_the_lookup_table_is_built_once_per_theme():
    from specterm1d.term import sixel

    first = sixel.palette_and_lut(theme.XGTERM)
    assert sixel.palette_and_lut(theme.XGTERM)[1] is first[1]


# ---- the command line ------------------------------------------------

def test_theme_option_defaults_to_xgterm():
    assert build_parser().parse_args(["a.fits"]).theme == "xgterm"


def test_theme_option_rejects_an_unknown_name(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["a.fits", "--theme", "no-such-theme"])
    assert "no-such-theme" in capsys.readouterr().err


def test_theme_option_is_applied_before_anything_draws(tabular_fits, tmp_path):
    out = tmp_path / "frame.png"
    main([str(tabular_fits), "--theme", "dark", "--dump", str(out),
          "--dump-size", "160x100"])
    assert theme.active() is theme.DARK

    from PIL import Image

    pixels = np.asarray(Image.open(out).convert("RGB"))
    assert (pixels == [0x10, 0x14, 0x18]).all(axis=-1).any()


def test_a_matplotlib_style_name_works_end_to_end(tabular_fits, tmp_path):
    out = tmp_path / "frame.png"
    main([str(tabular_fits), "--theme", "grayscale", "--dump", str(out),
          "--dump-size", "160x100"])
    assert theme.active().name == "grayscale"
    assert out.exists()


def test_sixel_renderer_encodes_with_the_active_theme():
    from specterm1d.term.caps import TerminalCaps
    from specterm1d.term.sixel import SixelRenderer

    rgba = np.zeros((12, 12, 4), dtype=np.uint8)
    rgba[..., 3] = 255
    rgba[..., :3] = [0x2f, 0x4f, 0x4f]
    caps = TerminalCaps(False, False, True, True, 24, 80, None, None, True)
    buffer = io.StringIO()
    with theme.using("xgterm"):
        SixelRenderer(buffer, caps).draw(rgba, CellRect(0, 0, 1, 1))
    # 0x2f4f4f is xgterm's figure ground: 18;30;30 on sixel's 0-100 scale.
    assert "#1;2;18;30;30" in buffer.getvalue()
