"""Display and navigation commands - splot's viewing keys."""
from __future__ import annotations

import numpy as np

from specterm1d.keymap import STATUS_HINTS, command

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


@command("display.zoom")
def zoom(session):
    lo, hi = session.view.xlim
    centre = session.view.cursor_x if session.view.cursor_x is not None \
        else (lo + hi) / 2
    half = (hi - lo) / (2 * ZOOM_FACTOR)
    session.view.xlim = (float(centre - half), float(centre + half))
    session.view.rescale_y()
    session.message(f"zoomed to {session.view.xlim[0]:.6g} - "
                    f"{session.view.xlim[1]:.6g}")


def _shift(session, sign: float):
    lo, hi = session.view.xlim
    step = (hi - lo) * SHIFT_FRACTION * sign
    session.view.xlim = (float(lo + step), float(hi + step))
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
    session.message("help" if session.showing_help else "")


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


def _window_action(session, char):        # noqa: C901 - a flat key table
    view = session.view
    x1, x2 = view.xlim
    y1, y2 = view.ylim
    dx, dy = x2 - x1, y2 - y1
    cx = view.cursor_x if view.cursor_x is not None else (x1 + x2) / 2
    cy = view.cursor_y if view.cursor_y is not None else (y1 + y2) / 2

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
        view.xlim = (float(cx - dx / 2), float(cx + dx / 2))
        view.ylim = (float(cy - dy / 2), float(cy + dy / 2))
        session.message("centred at cursor")
    elif char == "d":
        view.ylim = (float(y1 - SHIFT_WINDOW * dy), float(y2 - SHIFT_WINDOW * dy))
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
        view.xlim = (float(x1 - SHIFT_WINDOW * dx), float(x2 - SHIFT_WINDOW * dx))
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
        view.xlim = (float(cx - dx), float(cx + dx))
        view.ylim = (float(cy - dy), float(cy + dy))
        session.message("panned about cursor")
    elif char == "r":
        view.xlim = (float(x1 + SHIFT_WINDOW * dx), float(x2 + SHIFT_WINDOW * dx))
        session.message("shifted right")
    elif char == "t":
        view.ylim = (float(y1), float(cy))
        session.message(f"top edge {cy:.6g}")
    elif char == "u":
        view.ylim = (float(y1 + SHIFT_WINDOW * dy), float(y2 + SHIFT_WINDOW * dy))
        session.message("shifted up")
    elif char == "x":
        view.xlim = (float(cx - dx / 4), float(cx + dx / 4))
        session.message("zoomed x")
    elif char == "y":
        view.ylim = (float(cy - dy / 4), float(cy + dy / 4))
        session.message("zoomed y")
    elif char == "z":
        view.xlim = (float(cx - dx / 4), float(cx + dx / 4))
        view.ylim = (float(cy - dy / 4), float(cy + dy / 4))
        session.message("zoomed x and y")
    else:
        session.message(f"window: {char!r} is not a window key")


def _window_expand(session):
    """gtools 'e': mark two corners; each axis moves only if the marks differ."""
    x1, x2 = session.view.xlim
    y1, y2 = session.view.ylim
    dx, dy = x2 - x1, y2 - y1

    def done(sess, positions):
        (mx1, my1), (mx2, my2) = positions
        moved = []
        if abs(mx2 - mx1) > EXPAND_TOLERANCE * abs(dx):
            sess.view.xlim = (float(min(mx1, mx2)), float(max(mx1, mx2)))
            moved.append("x")
        if abs(my2 - my1) > EXPAND_TOLERANCE * abs(dy):
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
