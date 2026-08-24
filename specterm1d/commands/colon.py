"""Colon commands.

splot's set is reproduced except :dispaxis and :nsum, which are 2D-image
concerns - this tool ingests 1D. New commands cover the toggles splot had no
concept of: overlays, the sigma band, the mask, and the variant.
"""
from __future__ import annotations

import astropy.units as u

from specterm1d.keymap import command

_TRUE = {"yes", "y", "true", "on", "1", "+"}
_FALSE = {"no", "n", "false", "off", "0", "-"}


def parse_colon(text: str) -> tuple[str, list[str]]:
    stripped = text.strip()
    if not stripped:
        return ("", [])
    if stripped.startswith("#"):
        return ("#", [stripped[1:].strip()])
    head, _, tail = stripped.partition(" ")
    return (head, tail.split() if tail.strip() else [])


def _boolean(args: list[str], current: bool) -> bool:
    if not args:
        return not current
    value = args[0].lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return not current


def _view_toggle(field: str, label: str):
    def handler(session, args):
        current = getattr(session.view, field)
        new = _boolean(args, current)
        setattr(session.view, field, new)
        if field in ("zero_base",):
            session.view.rescale_y()
        session.message(f"{label} {'on' if new else 'off'}")
    return handler


def _overlay_toggle(name: str):
    def handler(session, args):
        if name in session.view.overlays:
            session.view.overlays.discard(name)
            session.message(f"{name} overlay off")
        else:
            session.view.overlays.add(name)
            available = session.view.current_spec().overlays
            if name not in available:
                session.message(f"{name} overlay on (not present in this file)")
            else:
                session.message(f"{name} overlay on")
    return handler


def _cmd_log(session, args):
    session.log.enable()
    session.message(f"logging to {session.log.path}")


def _cmd_nolog(session, args):
    session.log.disable()
    session.message("logging disabled")


def _cmd_show(session, args):
    session.showing_log = not session.showing_log
    session.message(f"{len(session.log.lines)} log lines"
                    if session.showing_log else "")


def _cmd_units(session, args):
    if not args:
        session.message(f"units {session.view.axis.unit.to_string()}")
        return
    try:
        unit = u.Unit(args[0])
    except ValueError:
        session.message(f"unknown unit: {args[0]}")
        return
    try:
        session.view.set_axis(mode="wave", unit=unit)
    except u.UnitConversionError:
        session.message(f"cannot express the dispersion in {args[0]}")
        return
    session.view.rescale_y()
    session.message(f"units {unit.to_string()}")


def _cmd_comment(session, args):
    session.log.comment(args[0] if args else "")
    session.message("comment added to the log")


def _cmd_variant(session, args):
    keys = session.view.entry.variant_keys()
    if not args:
        session.message("variants: " + "  ".join(keys))
        return
    if args[0] not in keys:
        session.message(f"no variant {args[0]!r}; have: {'  '.join(keys)}")
        return
    session.view.variant = args[0]
    session.view.rescale_y()
    session.message(f"variant {args[0]}")


def _cmd_renderer(session, args):
    session.message(f"renderer {session.renderer.name} "
                    "(change with --renderer at startup)")


def _cmd_mouse(session, args):
    session.set_mouse(_boolean(args, session.mouse_enabled))


def _cmd_not_applicable(name: str):
    def handler(session, args):
        session.message(f":{name} applies to 2D images; specterm1d ingests 1D")
    return handler


COLON_COMMANDS = {
    "log": _cmd_log,
    "nolog": _cmd_nolog,
    "show": _cmd_show,
    "units": _cmd_units,
    "#": _cmd_comment,
    "variant": _cmd_variant,
    "renderer": _cmd_renderer,
    "mouse": _cmd_mouse,
    "zero": _view_toggle("zero_base", "zero base"),
    "hist": _view_toggle("histogram", "histogram"),
    "flip": _view_toggle("flip", "flipped coordinates"),
    "wreset": _view_toggle("window_reset", "window reset"),
    "overplot": _view_toggle("overplot_next", "overplot"),
    "sigma": _view_toggle("show_sigma", "sigma band"),
    "mask": _view_toggle("show_mask", "mask highlight"),
    "sky": _overlay_toggle("sky"),
    "telluric": _overlay_toggle("telluric"),
    "model": _overlay_toggle("obj_model"),
    "dispaxis": _cmd_not_applicable("dispaxis"),
    "nsum": _cmd_not_applicable("nsum"),
}
# splot accepts these but they are no-ops here: we always draw our own frame.
COLON_COMMANDS["auto"] = _view_toggle("window_reset", "autodraw")
COLON_COMMANDS["nosysid"] = lambda s, a: s.message("nosysid has no effect here")


@command("colon.prompt")
def colon_prompt(session):
    def submitted(sess, text):
        if text is None:
            sess.message("cancelled")
            return
        name, args = parse_colon(text)
        if not name:
            return
        handler = COLON_COMMANDS.get(name)
        if handler is None:
            sess.message(f"unknown colon command: {name}")
            return
        handler(sess, args)

    session.await_line(":", submitted)
