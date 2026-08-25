"""Command-line entry point."""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

import specterm1d.commands
import specterm1d.term  # noqa: F401  - registers renderer factories
from specterm1d.io import registry
from specterm1d.logfile import SplotLog
from specterm1d.plot import SpectrumPlot
from specterm1d.session import Session
from specterm1d.term import caps as caps_mod

RENDERERS = ("kitty", "iterm2", "sixel", "halfblock")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="specterm1d",
        description="Terminal 1D spectrum viewer with IRAF splot keybindings",
    )
    parser.add_argument("files", nargs="*", type=Path, help="FITS spectra to view")
    parser.add_argument("--renderer", choices=RENDERERS,
                        help="force a renderer instead of probing the terminal")
    parser.add_argument("--format", help="force a loader instead of sniffing")
    parser.add_argument("--units", help="initial dispersion units, e.g. nm, um, GHz")
    parser.add_argument("--mouse", action="store_true",
                        help="enable mouse cursor positioning (hijacks selection)")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if not args.files:
        build_parser().print_help()
        return 2

    try:
        collection = registry.load(args.files[0], format=args.format)
    except registry.LoaderError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    # Headless: --dump and --cursor must work with no tty at all, so this
    # branches before the tty check.
    if args.dump or args.cursor:
        from specterm1d.cursorscript import parse_script, run_script
        from specterm1d.term.halfblock import HalfblockRenderer

        width, height = (int(v) for v in args.dump_size.lower().split("x"))
        caps = caps_mod.TerminalCaps(
            kitty=False, iterm2=False, sixel=False, truecolor=True,
            rows=height // 2, cols=width, pixel_width=width,
            pixel_height=height, is_tty=False,
        )
        session = Session(collection, HalfblockRenderer(out=io.StringIO()),
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

    caps = caps_mod.detect(is_tty=sys.stdout.isatty())
    if not caps.is_tty:
        print("specterm1d needs a terminal; stdout is not a tty.", file=sys.stderr)
        return 1

    renderer = caps_mod.choose_renderer(caps, override=args.renderer,
                                        out=sys.stdout)
    width, height = renderer.target_pixels(caps.rows - 2, caps.cols)
    session = Session(collection, renderer, SpectrumPlot(width, height),
                      out=sys.stdout, caps=caps)
    session.debug = args.debug

    if args.log:
        session.log = SplotLog(args.log)

    if args.units:
        import astropy.units as u
        session.view.set_axis(unit=u.Unit(args.units))

    if args.mouse:
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
