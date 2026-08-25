# tests/test_plot.py
import numpy as np
import pytest

from specterm1d.plot import (
    PlotRequest,
    SpectrumPlot,
    autoscale,
    decimate,
    masked_flux,
)
from specterm1d.spec import build_spec


def test_masked_flux_puts_nan_at_bad_pixels():
    spec = build_spec([1.0, 2, 3], [10.0, 20, 30],
                      mask=np.array([True, False, True]))
    y = masked_flux(spec)
    assert y[0] == 10.0 and np.isnan(y[1]) and y[2] == 30.0


def test_masked_flux_does_not_mutate_the_spec():
    spec = build_spec([1.0, 2], [10.0, 20], mask=np.array([True, False]))
    masked_flux(spec)
    assert spec.flux.tolist() == [10.0, 20.0]


def test_decimate_returns_data_unchanged_below_threshold():
    x = np.linspace(0, 1, 100)
    y = x.copy()
    xd, _ = decimate(x, y, 0.0, 1.0, ncols=50, threshold=4)
    assert xd.size == 100


def test_decimate_reduces_to_two_vertices_per_column():
    x = np.linspace(0, 1, 100_000)
    y = np.sin(x * 500)
    xd, yd = decimate(x, y, 0.0, 1.0, ncols=1200)
    assert yd.size == 2 * 1200
    assert xd.size == yd.size


def test_decimate_preserves_the_envelope_exactly():
    rng = np.random.default_rng(0)
    x = np.linspace(0, 1, 100_000)
    y = np.sin(x * 500) + 0.01 * rng.standard_normal(x.size)
    _, yd = decimate(x, y, 0.0, 1.0, ncols=1200)
    assert np.isclose(np.nanmin(yd), y.min())
    assert np.isclose(np.nanmax(yd), y.max())


def test_decimate_skips_nans_within_a_bin():
    y = np.arange(100.0)
    y[5] = np.nan            # one bad pixel among many good ones
    x = np.linspace(0, 1, 100)
    _, yd = decimate(x, y, 0.0, 1.0, ncols=10, threshold=0)
    assert not np.isnan(yd[0])   # the bin survives its single nan


def test_decimate_yields_nan_for_an_all_nan_bin():
    y = np.arange(100.0)
    y[0:10] = np.nan         # the entire first bin is masked
    x = np.linspace(0, 1, 100)
    _, yd = decimate(x, y, 0.0, 1.0, ncols=10, threshold=0)
    assert np.isnan(yd[0]) and np.isnan(yd[1])


def test_decimate_clips_to_the_requested_range():
    x = np.linspace(0.0, 100.0, 1001)
    y = x.copy()
    xd, _ = decimate(x, y, 40.0, 60.0, ncols=10, threshold=1000)
    assert xd.min() <= 40.0 and xd.max() >= 60.0
    assert xd.min() > 30.0 and xd.max() < 70.0


def test_decimate_handles_an_empty_range():
    x = np.linspace(0.0, 10.0, 11)
    xd, yd = decimate(x, x, 100.0, 200.0, ncols=10)
    assert xd.size == 0 and yd.size == 0


def test_autoscale_ignores_masked_pixels():
    # The masked pixel is a huge spike; it must not set the limits.
    spec = build_spec([1.0, 2, 3, 4], [1.0, 1e6, 2.0, 1.5],
                      mask=np.array([True, False, True, True]))
    _, hi = autoscale(spec, (0.0, 10.0), pad=0.0)
    assert hi < 10.0


def test_autoscale_ignores_pixels_outside_the_range():
    spec = build_spec([1.0, 2, 3, 4], [1.0, 1.0, 100.0, 100.0])
    lo, hi = autoscale(spec, (0.5, 2.5), pad=0.0)
    assert lo == pytest.approx(1.0)
    assert hi < 10.0          # the 100.0 pixels are outside the range


def test_autoscale_zero_base_pins_the_bottom_at_zero():
    spec = build_spec([1.0, 2, 3], [5.0, 6.0, 7.0])
    lo, _ = autoscale(spec, (0.0, 10.0), zero_base=True)
    assert lo == 0.0


def test_autoscale_survives_an_entirely_masked_range():
    spec = build_spec([1.0, 2], [1.0, 2.0], mask=np.array([False, False]))
    lo, hi = autoscale(spec, (0.0, 10.0))
    assert np.isfinite(lo) and np.isfinite(hi) and hi > lo


def test_render_returns_an_rgba_array_of_the_requested_size():
    spec = build_spec(np.linspace(4000, 9000, 500), np.ones(500))
    plot = SpectrumPlot(640, 400)
    rgba = plot.render(PlotRequest(spec=spec, xlim=(4000, 9000), ylim=(0, 2)))
    assert rgba.shape == (400, 640, 4)
    assert rgba.dtype == np.uint8


def test_resize_changes_the_output_size():
    spec = build_spec(np.linspace(4000, 9000, 500), np.ones(500))
    plot = SpectrumPlot(640, 400)
    plot.resize(800, 300)
    rgba = plot.render(PlotRequest(spec=spec, xlim=(4000, 9000), ylim=(0, 2)))
    assert rgba.shape == (300, 800, 4)


def test_render_reuses_the_same_figure_object():
    # The figure is persistent; rebuilding it per keystroke is the slow path.
    spec = build_spec(np.linspace(4000, 9000, 500), np.ones(500))
    plot = SpectrumPlot(320, 200)
    first = plot.fig
    plot.render(PlotRequest(spec=spec, xlim=(4000, 9000), ylim=(0, 2)))
    plot.render(PlotRequest(spec=spec, xlim=(5000, 6000), ylim=(0, 2)))
    assert plot.fig is first


def test_sigma_band_is_drawn_only_when_requested():
    spec = build_spec(np.linspace(4000, 5000, 100), np.ones(100),
                      sigma=np.full(100, 0.1))
    plot = SpectrumPlot(320, 200)
    plain = plot.render(PlotRequest(spec=spec, xlim=(4000, 5000), ylim=(0, 2)))
    banded = plot.render(PlotRequest(spec=spec, xlim=(4000, 5000), ylim=(0, 2),
                                     show_sigma=True))
    assert not np.array_equal(plain, banded)


def test_overlay_is_drawn_only_when_requested():
    spec = build_spec(np.linspace(4000, 5000, 100), np.ones(100),
                      overlays={"sky": np.full(100, 0.5)})
    plot = SpectrumPlot(320, 200)
    plain = plot.render(PlotRequest(spec=spec, xlim=(4000, 5000), ylim=(0, 2)))
    with_sky = plot.render(PlotRequest(spec=spec, xlim=(4000, 5000), ylim=(0, 2),
                                       overlays=("sky",)))
    assert not np.array_equal(plain, with_sky)


def test_unknown_overlay_name_is_ignored_not_fatal():
    spec = build_spec(np.linspace(4000, 5000, 100), np.ones(100))
    plot = SpectrumPlot(320, 200)
    rgba = plot.render(PlotRequest(spec=spec, xlim=(4000, 5000), ylim=(0, 2),
                                   overlays=("nonexistent",)))
    assert rgba.shape == (200, 320, 4)


def test_render_stays_within_the_redraw_budget():
    import time

    spec = build_spec(np.linspace(4000, 9000, 4097),
                      np.random.default_rng(0).standard_normal(4097))
    plot = SpectrumPlot(1200, 700)
    plot.render(PlotRequest(spec=spec, xlim=(4000, 9000), ylim=(-4, 4)))  # warm up
    start = time.perf_counter()
    for _ in range(5):
        plot.render(PlotRequest(spec=spec, xlim=(4500, 8500), ylim=(-4, 4)))
    elapsed = (time.perf_counter() - start) / 5
    assert elapsed < 0.10, f"redraw took {elapsed * 1000:.0f} ms"


def test_long_title_is_elided_to_fit_the_figure():
    # pypeit spec1d basenames overrun the axes and get clipped, taking the
    # object label with them. The tail is favoured so the label survives.
    plot = SpectrumPlot(640, 400)
    title = ("spec1d_UVES.2009-04-20T01:35:52.269-SDSS-J0935+0924_"
             "VLT_UVES_red_20090420T013552.269.fits  OBJ0497-MSC01-ORDER0108")
    fitted = plot.fit_title(title)
    assert len(fitted) < len(title)
    assert "…" in fitted
    assert fitted.endswith("ORDER0108")


def test_short_title_is_left_alone():
    plot = SpectrumPlot(640, 400)
    assert plot.fit_title("tabular.fits  tabular") == "tabular.fits  tabular"


def test_empty_title_is_left_alone():
    assert SpectrumPlot(320, 200).fit_title("") == ""


def test_chrome_shrinks_with_the_figure():
    from specterm1d.plot import chrome_for

    # An 80-column terminal asks halfblock for an 80x44 figure. Default 9pt
    # labels are a quarter of that height and collide into mush.
    tiny = chrome_for(80, 44)
    small = chrome_for(200, 96)
    full = chrome_for(1200, 700)
    assert tiny.fontsize < small.fontsize < full.fontsize
    assert tiny.ticks == 3 and small.ticks == 4 and full.ticks is None


def test_tiny_chrome_drops_the_labels_that_do_not_fit():
    from specterm1d.plot import chrome_for

    tiny = chrome_for(80, 44)
    assert not (tiny.title or tiny.xlabel or tiny.ylabel)
    # The y label goes first at small sizes: horizontal pixels are scarcest.
    assert chrome_for(200, 96).xlabel and not chrome_for(200, 96).ylabel


def test_small_figures_render_without_colliding_labels():
    spec = build_spec(np.linspace(5670, 5698, 500), np.ones(500))
    for width, height in ((80, 44), (200, 96)):
        plot = SpectrumPlot(width, height)
        rgba = plot.render(PlotRequest(spec=spec, xlim=(5670, 5698), ylim=(0, 2),
                                       title="spec1d_long_name.fits  ORDER0108",
                                       xlabel="Wavelength (Angstrom)",
                                       ylabel="Flux"))
        assert rgba.shape == (height, width, 4)
        # The axes must not have been squeezed out of existence by the chrome.
        box = plot.ax.get_position()
        assert box.width > 0.5 and box.height > 0.3
