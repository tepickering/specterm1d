"""Display and navigation commands - splot's viewing keys."""
from __future__ import annotations

import numpy as np

from specterm1d.keymap import STATUS_HINTS, command
from specterm1d.plot import from_frac, to_frac

SHIFT_FRACTION = 0.25
ZOOM_FACTOR = 2.0


def _spec_and_pixel(session, x: float):
    spec = session.view.display_spec()
    pixel = int(np.clip(np.searchsorted(spec.wave, x), 0, spec.npix - 1))
    return spec, pixel


@command("display.report")
def report(session):
    """<space>: cursor position and the nearest pixel's value."""
    x = session.view.cursor_x
    if x is None:
        session.message("no cursor")
        return
    spec, pixel = _spec_and_pixel(session, x)
    session.message(
        f"x={x:.6g}  y={spec.flux[pixel]:.6g}  pix={pixel}  "
        f"wave={spec.wave[pixel]:.6g}"
    )


@command("display.expand")
def expand(session):
    """a: expand between two cursors; the same point twice autoscales all."""
    def done(sess, positions):
        xs = [x for x, _ in positions]
        lo, hi = min(xs), max(xs)
        if np.isclose(lo, hi):
            sess.view.reset_limits()
            sess.message("autoscaled the whole spectrum")
            return
        sess.view.xlim = (float(lo), float(hi))
        sess.view.rescale_y()
        sess.message(f"expanded to {lo:.6g} - {hi:.6g}")

    session.await_cursor(2, "mark two positions to expand between", done)


@command("display.zero_base")
def zero_base(session):
    if session.view.ylog:
        session.message("zero base has no meaning on a log y axis")
        return
    session.view.zero_base = not session.view.zero_base
    session.view.rescale_y()
    session.message(f"zero base {'on' if session.view.zero_base else 'off'}")


@command("display.clear")
def clear(session):
    session.view.markers.clear()
    session.view.fits.clear()
    session.overlay_specs.clear()
    session.view.reset_limits()
    session.message("cleared windowing")


@command("display.redraw")
def redraw(session):
    session.message("redrawn")


# Zooming and panning are written as fractions of the window rather than as
# arithmetic on the limits, so a log axis zooms by the same factor it does on
# screen and a pan cannot walk the lower limit down through zero.
@command("display.zoom")
def zoom(session):
    lo, hi = session.view.xlim
    log = session.view.xlog
    centre = 0.5 if session.view.cursor_x is None \
        else to_frac(session.view.cursor_x, lo, hi, log)
    half = 1.0 / (2 * ZOOM_FACTOR)
    session.view.xlim = (from_frac(centre - half, lo, hi, log),
                         from_frac(centre + half, lo, hi, log))
    session.view.rescale_y()
    session.message(f"zoomed to {session.view.xlim[0]:.6g} - "
                    f"{session.view.xlim[1]:.6g}")


def _shift(session, sign: float):
    lo, hi = session.view.xlim
    log = session.view.xlog
    step = SHIFT_FRACTION * sign
    session.view.xlim = (from_frac(step, lo, hi, log),
                         from_frac(1.0 + step, lo, hi, log))
    session.view.rescale_y()


@command("display.shift_left")
def shift_left(session):
    _shift(session, -1.0)
    session.message("shifted left")


@command("display.shift_right")
def shift_right(session):
    _shift(session, +1.0)
    session.message("shifted right")


def _goto(session, index: int):
    session.view.index = index
    session.view.variant = None
    session.view.markers.clear()
    session.view.fits.clear()
    if session.view.window_reset:
        session.view.reset_limits()
        session.view.cursor_x = float(np.mean(session.view.xlim))
        session.view.follow_flux()
    session.message(f"{session.view.entry.label} "
                    f"({index + 1}/{len(session.collection)})")


@command("display.prev")
def previous(session):
    if session.view.index == 0:
        session.message("already at the first spectrum")
        return
    _goto(session, session.view.index - 1)


@command("display.next")
def next_entry(session):
    if session.view.index >= len(session.collection) - 1:
        session.message("already at the last spectrum")
        return
    _goto(session, session.view.index + 1)


@command("display.goto")
def goto(session):
    def done(sess, text):
        if not text:
            sess.message("cancelled")
            return
        key = int(text) - 1 if text.strip().lstrip("-").isdigit() else text.strip()
        try:
            sess_index = sess.collection.find(key)
        except KeyError:
            sess.message(f"no spectrum matching {text!r}")
            return
        _goto(sess, sess_index)

    session.await_line(f"spectrum (1-{len(session.collection)} or name): ", done)


@command("display.variant")
def variant(session):
    keys = session.view.entry.variant_keys()
    if len(keys) < 2:
        session.message(f"only one variant available: {keys[0]}")
        return
    current = session.view.variant or session.view.entry.default
    nxt = keys[(keys.index(current) + 1) % len(keys)]
    session.view.variant = nxt
    if session.view.window_reset:
        session.view.rescale_y()
    session.message(f"variant {nxt}")


@command("display.pixel_coords")
def pixel_coords(session):
    mode = "wave" if session.view.axis.mode == "pixel" else "pixel"
    session.view.set_axis(mode=mode)
    session.view.rescale_y()
    session.message(f"{mode} coordinates")


@command("display.velocity")
def velocity(session):
    if session.view.axis.mode == "velocity":
        session.view.set_axis(mode="wave")
        session.message("wavelength scale")
        return
    x = session.view.cursor_x
    spec = session.view.current_spec()
    origin = float(session.view.axis.to_wave(spec, np.array([x]))[0])
    session.view.set_axis(mode="velocity", velocity_origin=origin)
    session.message(f"velocity scale about {origin:.6g}")


@command("display.overplot")
def overplot(session):
    session.view.overplot_next = True
    session.message("the next spectrum will overplot")


@command("display.get")
def get_spectrum(session):
    def done(sess, text):
        if not text:
            sess.message("cancelled")
            return
        sess.load_path(text.strip())

    session.await_line("file: ", done)


@command("display.quit")
def quit_command(session):
    if session.file_index + 1 < len(session.files):
        session.file_index += 1
        session.load_path(session.files[session.file_index])
        return True
    return False


@command("display.interrupt")
def interrupt(session):
    return False


@command("help.page")
def help_page(session):
    session.showing_help = not session.showing_help
    session.page_index = 0
    if not session.showing_help:
        session._close_text_page()


@command("help.cycle")
def help_cycle(session):
    session.hint_index = (session.hint_index + 1) % len(STATUS_HINTS)
    session.message(STATUS_HINTS[session.hint_index])


# ---- w: the gtools window submode -----------------------------------
#
# Transcribed from IRAF pkg/xtools/gtools/gtwindow.x and lib/scr/gtools.key,
# so every key keeps the meaning a splot user already has in their fingers.
# Shifts move 0.75 of the window, zooms are cursor +/- d/4 (a factor of two),
# and 'p' pans to cursor +/- d, which doubles the window - all as gt_window1
# does it. 'e' takes two cursors and, following gt_window2, applies each axis
# only if the two marks differ by more than 0.001 of that axis's span.

SHIFT_WINDOW = 0.75
EXPAND_TOLERANCE = 0.001


def _window_action(session, char):
    view = session.view
    x1, x2 = view.xlim
    y1, y2 = view.ylim

    def fx(frac):
        return from_frac(frac, x1, x2, view.xlog)

    def fy(frac):
        return from_frac(frac, y1, y2, view.ylog)

    # The cursor as a fraction of each axis; every shift, zoom and pan below
    # is expressed against these, so the log and linear cases are one path.
    # Without a cursor the middle of the window is the middle on screen,
    # which on a log axis is the geometric mean rather than the arithmetic.
    cxf = 0.5 if view.cursor_x is None else to_frac(view.cursor_x, x1, x2,
                                                   view.xlog)
    cyf = 0.5 if view.cursor_y is None else to_frac(view.cursor_y, y1, y2,
                                                   view.ylog)
    cx, cy = fx(cxf), fy(cyf)

    if char == "?":
        session.showing_help = True
        session.message("window keys")
    elif char == "a":
        view.reset_limits()
        session.message("autoscaled x and y")
    elif char == "b":
        view.ylim = (float(cy), float(y2))
        session.message(f"bottom edge {cy:.6g}")
    elif char == "c":
        view.xlim = (fx(cxf - 0.5), fx(cxf + 0.5))
        view.ylim = (fy(cyf - 0.5), fy(cyf + 0.5))
        session.message("centred at cursor")
    elif char == "d":
        view.ylim = (fy(-SHIFT_WINDOW), fy(1.0 - SHIFT_WINDOW))
        session.message("shifted down")
    elif char == "f":
        view.flip = not view.flip
        session.message(f"x axis flip {'on' if view.flip else 'off'}")
    elif char == "g":
        view.flip_y = not view.flip_y
        session.message(f"y axis flip {'on' if view.flip_y else 'off'}")
    elif char == "j":
        view.xlim = (float(cx), float(x2))
        session.message(f"left edge {cx:.6g}")
    elif char == "k":
        view.xlim = (float(x1), float(cx))
        session.message(f"right edge {cx:.6g}")
    elif char == "l":
        view.xlim = (fx(-SHIFT_WINDOW), fx(1.0 - SHIFT_WINDOW))
        session.message("shifted left")
    elif char == "m":
        spec = view.display_spec()
        good = spec.wave[spec.good]
        if good.size:
            view.xlim = (float(good.min()), float(good.max()))
        session.message("autoscaled x")
    elif char == "n":
        view.rescale_y()
        session.message("autoscaled y")
    elif char == "p":
        view.xlim = (fx(cxf - 1.0), fx(cxf + 1.0))
        view.ylim = (fy(cyf - 1.0), fy(cyf + 1.0))
        session.message("panned about cursor")
    elif char == "r":
        view.xlim = (fx(SHIFT_WINDOW), fx(1.0 + SHIFT_WINDOW))
        session.message("shifted right")
    elif char == "t":
        view.ylim = (float(y1), float(cy))
        session.message(f"top edge {cy:.6g}")
    elif char == "u":
        view.ylim = (fy(SHIFT_WINDOW), fy(1.0 + SHIFT_WINDOW))
        session.message("shifted up")
    elif char == "x":
        view.xlim = (fx(cxf - 0.25), fx(cxf + 0.25))
        session.message("zoomed x")
    elif char == "y":
        view.ylim = (fy(cyf - 0.25), fy(cyf + 0.25))
        session.message("zoomed y")
    elif char == "z":
        view.xlim = (fx(cxf - 0.25), fx(cxf + 0.25))
        view.ylim = (fy(cyf - 0.25), fy(cyf + 0.25))
        session.message("zoomed x and y")
    else:
        session.message(f"window: {char!r} is not a window key")


def _window_expand(session):
    """gtools 'e': mark two corners; each axis moves only if the marks differ.

    "Differ" is measured across the axis rather than in data units: near the
    bottom of a log decade two marks a third of the window apart are a
    vanishing difference in flux, and would be rejected as the same point.
    """
    x1, x2 = session.view.xlim
    y1, y2 = session.view.ylim
    xlog, ylog = session.view.xlog, session.view.ylog

    def done(sess, positions):
        (mx1, my1), (mx2, my2) = positions
        moved = []
        if abs(to_frac(mx2, x1, x2, xlog)
               - to_frac(mx1, x1, x2, xlog)) > EXPAND_TOLERANCE:
            sess.view.xlim = (float(min(mx1, mx2)), float(max(mx1, mx2)))
            moved.append("x")
        if abs(to_frac(my2, y1, y2, ylog)
               - to_frac(my1, y1, y2, ylog)) > EXPAND_TOLERANCE:
            sess.view.ylim = (float(min(my1, my2)), float(max(my1, my2)))
            moved.append("y")
        sess.message(f"expanded {' and '.join(moved)}" if moved
                     else "marks too close; window unchanged")

    session.await_cursor(2, "mark two corners of the new window", done)


@command("display.window")
def window(session):
    def chosen(sess, char):
        if char == "e":
            _window_expand(sess)
        elif char == "I":
            sess.message("cancelled")
        else:
            _window_action(sess, char)

    session.await_key(
        "window: a b c d e f g j k l m n p r t u x y z, ? for help", chosen, {})
