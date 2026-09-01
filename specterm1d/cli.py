"""Command-line entry point."""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import specterm1d.commands
import specterm1d.term  # noqa: F401  - registers renderer factories
from specterm1d import theme
from specterm1d.io import registry
from specterm1d.logfile import SplotLog
from specterm1d.plot import SpectrumPlot
from specterm1d.session import Session
from specterm1d.term import caps as caps_mod

RENDERERS = ("kitty", "iterm2", "sixel", "gui", "text")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="specterm1d",
        description="Terminal 1D spectrum viewer with IRAF splot keybindings",
    )
    parser.add_argument("files", nargs="*", type=Path, help="FITS spectra to view")
    parser.add_argument("--renderer", choices=RENDERERS,
                        help="force a renderer instead of probing the terminal")
    parser.add_argument("--gui", action="store_true",
                        help="shortcut for --renderer gui (a matplotlib window)")
    # choices without a metavar would print all thirty-odd names in --help;
    # argparse still lists them when one is misspelled, which is where a user
    # actually wants to see the set.
    parser.add_argument("--theme", metavar="NAME", choices=theme.names(),
                        help="colour theme: xgterm (default; dark under the "
                             "text backend), or any valid matplotlib style")
    parser.add_argument("--format", help="force a loader instead of sniffing")
    parser.add_argument("--units", help="initial dispersion units, e.g. nm, um, GHz")
    parser.add_argument(
        "--mouse", action=argparse.BooleanOptionalAction, default=None,
        help="toggle mouse positioning (default: on for inline graphics)",
    )
    parser.add_argument("--log", default="splot.log", help="measurement log file")
    parser.add_argument("--debug", action="store_true",
                        help="show full tracebacks instead of one-line errors")
    parser.add_argument("--cursor", type=Path,
                        help="run a cursor script instead of reading the keyboard")
    parser.add_argument("--dump", type=Path,
                        help="render one frame to a PNG and exit (no tty needed)")
    parser.add_argument("--dump-size", default="1200x700",
                        help="pixel size for --dump, as WxH")
    return parser


# The text backend draws its own decoration in terminal text over a plot of
# 2x2 block glyphs, and xgterm's palette asks more of that than it can give:
# three inks around a box, and a slate surround meeting a black plot on a seam
# the quantizer has to resolve. dark is one foreground on one ground, which is
# the same simplification the backend already is. An explicit --theme wins.
DEFAULT_THEME = {"text": "dark"}


def default_theme_for(renderer_name: str) -> str:
    return DEFAULT_THEME.get(renderer_name, theme.DEFAULT.name)


def resolve_renderer_choice(args) -> str | None:
    """--gui is a shortcut; an explicit --renderer always wins."""
    if args.renderer:
        return args.renderer
    return "gui" if args.gui else None


def attach_or_fall_back(renderer, plot, caps, out):
    """Open the renderer's window, or warn once and fall back to the terminal.

    A viewer that refuses to start over a missing window is worse than one
    that draws coarsely, so this is never fatal - even for an explicit
    --renderer gui. Terminal backends have no attach() and pass straight
    through.
    """
    from specterm1d.term.gui import GuiUnavailable
    from specterm1d.term.text import TextRenderer

    attach = getattr(renderer, "attach", None)
    if attach is None:
        return renderer
    try:
        attach(plot)
    except GuiUnavailable as exc:
        print(f"graphics window unavailable ({exc}); drawing in the terminal",
              file=sys.stderr)
        return TextRenderer(out=out, truecolor=caps.truecolor)
    return renderer


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.files:
        build_parser().print_help()
        return 2

    # Before anything builds a figure: the palette is module state, and a
    # figure created under the wrong one would carry it until the next resize.
    # Without --theme the default waits until the renderer is known, below;
    # --dump and --cursor keep xgterm, since what they produce is a full
    # matplotlib figure however the renderer they borrow draws on a screen.
    if args.theme:
        theme.use(args.theme)

    try:
        collection = registry.load(args.files[0], format=args.format)
    except registry.LoaderError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Headless: --dump and --cursor must work with no tty at all, so this
    # branches before the tty check.
    if args.dump or args.cursor:
        from specterm1d.cursorscript import parse_script, run_script
        from specterm1d.term.text import TextRenderer

        width, height = (int(v) for v in args.dump_size.lower().split("x"))
        caps = caps_mod.TerminalCaps(
            kitty=False, iterm2=False, sixel=False, truecolor=True,
            rows=height // 2, cols=width, pixel_width=width,
            pixel_height=height, is_tty=False,
        )
        session = Session(collection, TextRenderer(out=io.StringIO()),
                          SpectrumPlot(width, height), out=io.StringIO(),
                          caps=caps)
        session.debug = args.debug
        session.log = SplotLog(args.log)
        if args.units:
            import astropy.units as u
            session.view.set_axis(unit=u.Unit(args.units))
        if args.cursor:
            run_script(session, parse_script(args.cursor.read_text()))
        if args.dump:
            session.dump_png(args.dump, size=(width, height))
        return 0

    choice = resolve_renderer_choice(args)
    caps = caps_mod.detect(is_tty=sys.stdout.isatty(),
                           probe_graphics=choice is None)
    if not caps.is_tty:
        print("specterm1d needs a terminal; stdout is not a tty.", file=sys.stderr)
        return 1

    renderer = caps_mod.choose_renderer(caps, override=choice, out=sys.stdout)
    width, height = renderer.target_pixels(caps.rows - 2, caps.cols)
    plot = SpectrumPlot(width, height)
    renderer = attach_or_fall_back(renderer, plot, caps, out=sys.stdout)
    # After the fallback, not before: a window that refused to open leaves the
    # text backend drawing, and that is what the palette should answer to.
    # The figure restyles itself on the next draw, so this is not too late.
    if not args.theme:
        theme.use(default_theme_for(renderer.name))
    session = Session(collection, renderer, plot, out=sys.stdout, caps=caps)
    session.debug = args.debug

    if args.log:
        session.log = SplotLog(args.log)

    if args.units:
        import astropy.units as u
        session.view.set_axis(unit=u.Unit(args.units))

    mouse_enabled = args.mouse
    if mouse_enabled is None:
        mouse_enabled = bool(getattr(renderer, "inline_graphics", False))
    if mouse_enabled:
        session.set_mouse(True)

    try:
        session.run()
    except Exception as exc:
        session.teardown()
        if args.debug:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
