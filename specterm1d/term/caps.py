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
import struct
import sys
import termios
import time
import tty
from dataclasses import dataclass
from typing import Callable

# A 1x1 transparent probe. kitty answers "OK"; everything else stays silent.
KITTY_QUERY = "\x1b_Gi=31,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\"
DA_QUERY = "\x1b[c"

_DA_RE = re.compile(r"\x1b\[\?([0-9;]+)c")
_KITTY_TERMS = {"xterm-kitty"}
_KITTY_PROGRAMS = {"ghostty", "WezTerm"}

# Renderer preference order. halfblock is always last and always available.
PREFERENCE = ("kitty", "iterm2", "sixel", "halfblock")

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
            if buf.endswith(b"c") or buf.endswith(b"\x1b\\"):
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


def detect(env: dict | None = None, query_fn: Callable | None = None,
           size_fn: Callable | None = None, is_tty: bool = True) -> TerminalCaps:
    env = os.environ if env is None else env

    if not is_tty:
        return TerminalCaps(False, False, False, False, 24, 80, None, None, False)

    size_fn = size_fn or window_size
    rows, cols, xpixel, ypixel = size_fn()
    # 0 means "not reported", not "zero pixels wide". Terminal.app reports 0,
    # and so may any injected size_fn, so normalize here rather than only in
    # the window_size shim.
    xpixel = xpixel or None
    ypixel = ypixel or None

    truecolor = env.get("COLORTERM", "").lower() in ("truecolor", "24bit")
    in_tmux = bool(env.get("TMUX"))

    kitty = False
    if not in_tmux:
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

    return TerminalCaps(
        kitty=kitty, iterm2=iterm2, sixel=sixel, truecolor=truecolor,
        rows=rows, cols=cols, pixel_width=xpixel, pixel_height=ypixel,
        is_tty=True,
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
        if name == "halfblock" or getattr(caps, name, False):
            return _FACTORIES[name](caps, out)
    raise RuntimeError("no renderer available")
