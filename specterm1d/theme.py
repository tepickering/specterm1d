"""The colour palette, as named roles rather than loose constants.

splot ran in an xgterm, and xgterm's palette is not decoration: cyan box,
yellow numbers, green captions and a white spectrum is what a generation of
spectroscopists read fluxes off. It is the default here for the same reason
the keybindings are.

A role is what a colour *means* - the spine colour, the tick label colour -
so a theme can give two roles the same value (the dark theme paints spines,
numbers and captions alike) without the call sites having to know. The
active theme is module state, set once by the CLI, because that is the shape
the palette already had when it was a handful of constants and threading a
palette argument through every renderer buys nothing.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    """Every colour the viewer draws with, keyed by what it is for."""

    name: str
    figure: str        # around the axes: figure face, and the chrome's ground
    plot: str          # inside the axes
    spine: str         # spines and tick marks, and the chrome's box glyphs
    tick_label: str    # the numbers on the axes
    text: str          # title, axis labels, legend
    line: str          # the spectrum
    sigma: str         # the error band
    mask: str          # masked columns
    fit: str           # fitted profiles
    cursor: str        # crosshair and markers
    overlay: tuple[str, str, str]


# IRAF's stdgraph colour table on xgterm's DarkSlateGray ground: 1 white,
# 2 red, 5 yellow, 6 cyan, 7 magenta, 8 coral. Blue (4) would be the faithful
# choice for the sigma band, but pure blue under a 45% alpha is barely
# distinguishable from the black it sits on, so the band is lightened.
XGTERM = Theme(
    name="xgterm",
    figure="#2f4f4f",
    plot="#000000",
    spine="#00ffff",
    tick_label="#ffff00",
    text="#00ff00",
    line="#ffffff",
    sigma="#6080ff",
    mask="#ff0000",
    fit="#ff00ff",
    cursor="#ff0000",
    overlay=("#ffff00", "#ff7f50", "#ff00ff"),
)

# What specterm1d shipped before xgterm became the default: one foreground
# for the whole decoration, on a near-black ground.
DARK = Theme(
    name="dark",
    figure="#101418",
    plot="#101418",
    spine="#c8d2dc",
    tick_label="#c8d2dc",
    text="#c8d2dc",
    line="#4aa3ff",
    sigma="#2f5d8a",
    mask="#c8503c",
    fit="#c8503c",
    cursor="#c8d2dc",
    overlay=("#e0a030", "#50b070", "#a070d0"),
)

BUILTIN = {theme.name: theme for theme in (XGTERM, DARK)}
DEFAULT = XGTERM


def _rgb(color: str) -> tuple[float, float, float]:
    from matplotlib.colors import to_rgb

    return to_rgb(color)


def _hex(color) -> str:
    from matplotlib.colors import to_hex

    return to_hex(color)


def blend(color: str, ground: str, weight: float = 0.5) -> str:
    """``color`` mixed ``weight`` of the way toward ``ground``."""
    a, b = _rgb(color), _rgb(ground)
    return _hex(tuple(x + (y - x) * weight for x, y in zip(a, b, strict=True)))


def _reddest(colors: list[str]) -> str:
    """The entry that reads most as a warning, for masks and the cursor."""
    def warmth(color: str) -> float:
        r, g, b = _rgb(color)
        return r - (g + b) / 2

    return max(colors, key=warmth)


def _farthest(colors: list[str], *from_: str) -> str:
    """The entry least likely to be confused with any of ``from_``."""
    others = [_rgb(c) for c in from_]

    def spread(color: str) -> float:
        rgb = _rgb(color)
        return min(sum((x - y) ** 2 for x, y in zip(rgb, other, strict=True))
                   for other in others)

    return max(colors, key=spread)


def from_mpl_style(name: str) -> Theme:
    """Derive a theme from a matplotlib style's *colours*.

    Only the colours. A style also carries fonts, line widths and grid
    settings, and applying those would fight the chrome sizing, which is
    tuned against the terminal's pixel budget rather than a page. A style
    may set only a few parameters, so the defaults fill in the rest.
    """
    import matplotlib.style as mplstyle
    from matplotlib import rcParamsDefault

    if name not in mplstyle.library:
        raise KeyError(name)
    params = dict(rcParamsDefault)
    params.update(mplstyle.library[name])

    cycle = [_hex(c) for c in params["axes.prop_cycle"].by_key().get("color", ())]
    cycle = cycle or ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]

    plot = _hex(params["axes.facecolor"])
    line = cycle[0]
    overlay = (cycle[1:4] + cycle)[:3]
    tick_label = params["xtick.labelcolor"]
    if tick_label == "inherit":
        tick_label = params["xtick.color"]
    mask = _reddest(cycle)

    return Theme(
        name=name,
        figure=_hex(params["figure.facecolor"]),
        plot=plot,
        spine=_hex(params["axes.edgecolor"]),
        tick_label=_hex(tick_label),
        text=_hex(params["text.color"]),
        line=line,
        sigma=blend(line, plot),
        mask=mask,
        fit=_farthest(cycle, line, mask),
        cursor=mask,
        overlay=(overlay[0], overlay[1], overlay[2]),
    )


def names() -> tuple[str, ...]:
    """Every accepted --theme name: ours first, then matplotlib's."""
    import matplotlib.style as mplstyle

    return (*BUILTIN, *sorted(mplstyle.available))


def resolve(name: str | Theme) -> Theme:
    """A Theme from a name, ours or matplotlib's."""
    if isinstance(name, Theme):
        return name
    if name in BUILTIN:
        return BUILTIN[name]
    try:
        return from_mpl_style(name)
    except KeyError:
        raise ValueError(f"unknown theme: {name}") from None


_active = DEFAULT


def active() -> Theme:
    return _active


def use(theme: str | Theme) -> Theme:
    """Make ``theme`` current. Returns the one it replaced."""
    global _active
    previous, _active = _active, resolve(theme)
    return previous


@contextmanager
def using(theme: str | Theme):
    """Scope a theme change, so a test cannot leak one into the next."""
    previous = use(theme)
    try:
        yield active()
    finally:
        use(previous)
