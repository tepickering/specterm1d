"""Terminal capability detection and renderer selection.

Every probe is timeout-guarded and falls through on silence: a terminal that
ignores a query must never hang the tool. The branching logic takes injectable
query and size functions so it is testable without a pty.
"""
from __future__ import annotations

import fcntl
import os
import re
import select
import shutil
import struct
import subprocess
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import Callable

# A 1x1 transparent probe. kitty answers "OK"; everything else stays silent.
KITTY_QUERY = "\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\"
DA_QUERY = "\x1b[c"

# DECRQM for SGR-Pixels (DECSET 1016). Asking beats inferring: 1016 is an
# xterm invention rather than a kitty one, and the terminals that implement it
# - ghostty and the sixel terminals among them - cannot be told apart from the
# ones that do not by anything in the environment.
PIXEL_MOUSE_QUERY = "\x1b[?1016$p"

# Inside tmux, nothing the terminal answers describes the terminal. The
# Primary Device Attributes describe tmux - a build with --enable-sixel
# answers attribute 4 with no client attached at all - and tmux draws any
# sixel it cannot pass on to its client as a placeholder, "SIXEL IMAGE
# (134x44)" padded out with '+' until it fills the window. An APC fares worse
# still: tmux eats the introducer and prints the payload as text. So inside
# tmux the questions go to tmux, which does know what its client is.
TMUX_CLIENT_FEATURES = ("display", "-p", "#{client_termfeatures}")
TMUX_CLIENT_TERM = ("display", "-p", "#{client_termname}")
TMUX_PASSTHROUGH_OPTION = ("show", "-gv", "allow-passthrough")

# A terminal on the far side of an ssh connection cannot read a file this
# process writes, which is what rules out handing kitty a path instead of
# 700 KB of base64 per frame.
SSH_VARS = ("SSH_CONNECTION", "SSH_CLIENT", "SSH_TTY")

# Terminals whose kitty-graphics support can be recognised from the terminal
# name tmux reports for its client. WezTerm is missing on purpose: it usually
# presents as xterm-256color, which proves nothing.
_KITTY_CLIENT_TERMS = {"xterm-kitty", "xterm-ghostty"}

_DA_RE = re.compile(r"\x1b\[\?([0-9;]+)c")
_DECRQM_RE = re.compile(r"\x1b\[\?(\d+);(\d+)\$y")

# DECRPM states. 0 means the terminal has never heard of the mode and 4 that
# it is permanently reset; the rest all mean it knows the mode and will let us
# turn it on.
_DECRQM_SUPPORTED = {"1", "2", "3"}
_KITTY_TERMS = {"xterm-kitty"}
_KITTY_PROGRAMS = {"ghostty", "WezTerm"}

# Renderer preference order. Inline graphics win where they exist - one window
# beats two - then a real graphics window, and halfblock last: correct
# everywhere, comfortable nowhere. LEAKY_INLINE is the one exception; see
# choose_renderer.
PREFERENCE = ("kitty", "iterm2", "sixel", "gui", "halfblock")

# iTerm2 never frees an inline image. Every distinct frame costs it about a
# decoded bitmap of resident memory for the life of the session, so panning a
# spectrum grows the terminal by roughly a megabyte and a half per keystroke -
# measured at 1.67 MB/frame over 100 cursor moves on iTerm2 3.6.11, against
# 0.05 MB/frame for the same loop drawing text. kitty's protocol replaces a
# placement in situ through a stable image id and does not do this; iTerm2's
# OSC 1337 has neither an id nor a delete verb, and nothing we can send
# collects the images (2J, 3J, erasing the cells and the alternate screen were
# all measured to make no difference). Its sixel path leaks too, at 4 MB/frame.
# So on iTerm2 both inline backends step aside for a graphics window.
LEAKY_INLINE = ("iterm2", "sixel")

_FACTORIES: dict[str, Callable] = {}


@dataclass(frozen=True)
class TerminalCaps:
    kitty: bool
    iterm2: bool
    sixel: bool
    truecolor: bool
    rows: int
    cols: int
    pixel_width: int | None
    pixel_height: int | None
    is_tty: bool
    # Worth trying a graphics window. choose_renderer reads this by name
    # through the same getattr the protocol flags use.
    gui: bool = False
    # Native Kitty can report SGR mouse positions in pixels (DECSET 1016).
    pixel_mouse: bool = False
    # Running under tmux, so graphics escapes need the passthrough wrapper.
    tmux: bool = False
    # The terminal is on this machine, so it can read files we write.
    local: bool = True


def register_renderer(name: str, factory: Callable) -> None:
    """Backends register here so caps.py never imports them (no cycle)."""
    _FACTORIES[name] = factory


def window_size(fd: int | None = None) -> tuple[int, int, int | None, int | None]:
    """(rows, cols, xpixel, ypixel). Pixel values are None when unreported."""
    fd = sys.stdout.fileno() if fd is None else fd
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, xp, yp = struct.unpack("HHHH", packed)
    except Exception:
        return (24, 80, None, None)
    return (rows or 24, cols or 80, xp or None, yp or None)


def query(request: str, timeout: float = 0.1, fd_in: int | None = None,
          fd_out: int | None = None) -> str | None:
    """Write a query and read whatever comes back before the deadline."""
    fd_in = sys.stdin.fileno() if fd_in is None else fd_in
    fd_out = sys.stdout.fileno() if fd_out is None else fd_out
    if not os.isatty(fd_in):
        return None

    saved = termios.tcgetattr(fd_in)
    try:
        tty.setraw(fd_in)
        os.write(fd_out, request.encode())
        buf = b""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            ready, _, _ = select.select([fd_in], [], [], remaining)
            if not ready:
                break
            chunk = os.read(fd_in, 64)
            if not chunk:
                break
            buf += chunk
            if buf.endswith(b"c") or buf.endswith(b"\x1b\\") \
                    or buf.endswith(b"$y"):
                break
    except Exception:
        return None
    finally:
        termios.tcsetattr(fd_in, termios.TCSADRAIN, saved)
    return buf.decode("latin-1") if buf else None


def _da_has_sixel(response: str | None) -> bool:
    """Sixel is advertised as attribute 4 in the Primary Device Attributes."""
    if not response:
        return False
    match = _DA_RE.search(response)
    if not match:
        return False
    return "4" in match.group(1).split(";")


def terminal_is_local(env: dict | None = None) -> bool:
    """Whether the terminal is running on this machine.

    An ssh session is the case where it is not, and the standard tell is the
    environment ssh sets. Wrong only in exotic setups, and wrong in the
    harmless direction: a false negative just means the slower transport.
    """
    env = os.environ if env is None else env
    return not any(env.get(name) for name in SSH_VARS)


def tmux_query(*args: str) -> str:
    """Run a tmux command and return its output, or "" if it cannot be run.

    Empty on anything unexpected - no tmux binary, a server that has gone
    away, a tmux too old for the format string - and every caller reads empty
    as "no", the safe direction. An explicit --renderer still forces the issue.
    """
    if shutil.which("tmux") is None:
        return ""
    try:
        done = subprocess.run(("tmux", *args), capture_output=True, text=True,
                              timeout=1.0, check=False)
    except Exception:
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def tmux_passthrough(sequence: str) -> str:
    """Wrap a terminal escape so tmux hands it to the terminal outside.

    tmux consumes an APC introducer and prints what follows as text - the
    kitty backend's own teardown turning up in the status line as
    "Ga=d,d=i,i=1,q=2;" is what this is for. Every ESC inside has to be
    doubled, because the wrapper is a DCS string and ends at the first ST.

    Inert unless the tmux server has `allow-passthrough` on; with it off tmux
    discards the sequence silently, which is at least not visible garbage.
    """
    return "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"


def _decrqm_supported(response: str | None, mode: int) -> bool:
    """Whether a DECRQM reply says the terminal implements ``mode``."""
    if not response:
        return False
    match = _DECRQM_RE.search(response)
    if match is None or match.group(1) != str(mode):
        return False
    return match.group(2) in _DECRQM_SUPPORTED


def detect(env: dict | None = None, query_fn: Callable | None = None,
           size_fn: Callable | None = None, is_tty: bool = True,
           tmux_fn: Callable | None = None) -> TerminalCaps:
    # Local: term/__init__ imports caps before gui, and probing is not on any
    # hot path.
    from specterm1d.term import gui as gui_backend

    env = os.environ if env is None else env

    if not is_tty:
        return TerminalCaps(False, False, False, False, 24, 80, None, None, False)

    # Default to really asking the terminal. cli calls detect() with neither
    # function injected, so a None default means every probed capability reads
    # False in production while the tests, which always inject, stay green.
    query_fn = query_fn or query
    size_fn = size_fn or window_size
    tmux_fn = tmux_fn or tmux_query
    rows, cols, xpixel, ypixel = size_fn()
    # 0 means "not reported", not "zero pixels wide". Terminal.app reports 0,
    # and so may any injected size_fn, so normalize here rather than only in
    # the window_size shim.
    xpixel = xpixel or None
    ypixel = ypixel or None

    truecolor = env.get("COLORTERM", "").lower() in ("truecolor", "24bit")
    in_tmux = bool(env.get("TMUX"))

    kitty = False
    if in_tmux:
        # Probe through the same wrapper the drawing will use, so a reply
        # proves both that the terminal outside speaks the protocol and that
        # tmux is letting sequences through. Silence is not a no, though:
        # tmux need not hand the terminal's reply back to the pane. So fall
        # back on asking tmux who its client is - and whether passthrough is
        # on at all, since without it the wrapped sequences go nowhere and
        # the pane would just stay black.
        response = query_fn(tmux_passthrough(KITTY_QUERY)) if query_fn else None
        kitty = bool(response and "OK" in response)
        if not kitty:
            allowed = tmux_fn(*TMUX_PASSTHROUGH_OPTION) in ("on", "all")
            kitty = allowed and tmux_fn(*TMUX_CLIENT_TERM) in _KITTY_CLIENT_TERMS
    else:
        response = query_fn(KITTY_QUERY) if query_fn else None
        kitty = bool(response and "OK" in response)
        if not kitty:
            kitty = (
                env.get("TERM") in _KITTY_TERMS
                or env.get("TERM_PROGRAM") in _KITTY_PROGRAMS
                or bool(env.get("KITTY_WINDOW_ID"))
            )

    iterm2 = (env.get("TERM_PROGRAM") == "iTerm.app"
              or env.get("LC_TERMINAL") == "iTerm2")

    sixel = _da_has_sixel(query_fn(DA_QUERY) if query_fn else None)
    if sixel and in_tmux:
        # The attribute came from tmux, so check it against what tmux says its
        # client can display.
        sixel = "sixel" in tmux_fn(*TMUX_CLIENT_FEATURES).split(",")

    # Pixel mouse positions are a property of the terminal, not of whichever
    # graphics protocol it also happens to speak, so ask about the mode rather
    # than guess from the vendor. Pixel geometry is needed to map the reports;
    # tmux does not pass 1016 through.
    pixel_mouse = bool(
        not in_tmux and xpixel and ypixel
        and _decrqm_supported(
            query_fn(PIXEL_MOUSE_QUERY) if query_fn else None, 1016)
    )

    return TerminalCaps(
        kitty=kitty, iterm2=iterm2, sixel=sixel, truecolor=truecolor,
        rows=rows, cols=cols, pixel_width=xpixel, pixel_height=ypixel,
        is_tty=True, gui=gui_backend.available(env), pixel_mouse=pixel_mouse,
        tmux=in_tmux, local=terminal_is_local(env),
    )


def choose_renderer(caps: TerminalCaps, override: str | None = None, out=None):
    """Pick a backend. An explicit override skips probing entirely, so a
    terminal that supports a protocol without advertising it can still be
    driven."""
    if override is not None:
        if override not in _FACTORIES:
            known = ", ".join(sorted(_FACTORIES)) or "(none registered)"
            raise ValueError(f"unknown renderer {override!r}; known: {known}")
        return _FACTORIES[override](caps, out)

    for name in PREFERENCE:
        if name not in _FACTORIES:
            continue
        # A leaking plot still beats no plot, so this only applies where there
        # is a window to fall back to.
        if caps.iterm2 and caps.gui and name in LEAKY_INLINE:
            continue
        if name == "halfblock" or getattr(caps, name, False):
            return _FACTORIES[name](caps, out)
    raise RuntimeError("no renderer available")
