"""Command-line entry point."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from specterm1d.io import registry
from specterm1d.plot import SpectrumPlot
from specterm1d.session import Session
from specterm1d.term import caps as caps_mod
import specterm1d.term  # noqa: F401  - registers renderer factories

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

    if args.units:
        import astropy.units as u
        session.view.set_axis(unit=u.Unit(args.units))

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
