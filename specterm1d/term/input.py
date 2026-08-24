"""Raw-mode key reading.

``parse_keys`` is a pure function over bytes so the whole escape-sequence
grammar is testable without a terminal. ``KeyReader`` is the thin wrapper that
owns termios and SIGWINCH.
"""
from __future__ import annotations

import os
import select
import signal
import sys
import termios
import tty
from dataclasses import dataclass

_ARROWS = {"A": "up", "B": "down", "C": "right", "D": "left",
           "H": "home", "F": "end"}
_TILDE = {"1": "home", "3": "delete", "4": "end", "5": "pageup", "6": "pagedown"}
_MODS = {2: "shift", 3: "alt", 4: "shift-alt", 5: "ctrl", 6: "shift-ctrl"}
_CSI_FINAL = set(range(0x40, 0x7F))

# How long to wait before deciding a lone ESC really was the escape key.
ESCAPE_TIMEOUT = 0.05


@dataclass(frozen=True)
class Key:
    name: str          # 'char', 'up', 'shift-left', 'enter', 'mouse', 'resize', ...
    char: str = ""

    def __str__(self) -> str:
        return self.char if self.name == "char" else f"<{self.name}>"


def _utf8_len(first: int) -> int:
    if first < 0x80:
        return 1
    if first >= 0xF0:
        return 4
    if first >= 0xE0:
        return 3
    if first >= 0xC0:
        return 2
    return 1


def _csi_key(text: str) -> Key:
    final = text[-1]
    params = text[2:-1]

    if params.startswith("<") or final in ("M", "m"):
        return Key("mouse", char=text)

    if final in _ARROWS:
        name = _ARROWS[final]
        parts = params.split(";")
        if len(parts) >= 2 and parts[1].isdigit():
            modifier = _MODS.get(int(parts[1]))
            if modifier:
                name = f"{modifier}-{name}"
        return Key(name)

    if final == "~":
        return Key(_TILDE.get(params.split(";")[0], "unknown"))

    return Key("unknown", char=text)


def parse_keys(buf: bytes) -> tuple[list[Key], bytes]:
    """Parse as many keys as possible; return them plus the unconsumed tail."""
    keys: list[Key] = []
    i, n = 0, len(buf)

    while i < n:
        b = buf[i]

        if b == 0x1B:
            if i + 1 >= n:
                break                       # hold: might be a longer sequence
            nxt = buf[i + 1]
            if nxt == 0x5B:                 # '[' - CSI
                j = i + 2
                while j < n and buf[j] not in _CSI_FINAL:
                    j += 1
                if j >= n:
                    break                   # incomplete CSI
                keys.append(_csi_key(buf[i:j + 1].decode("latin-1")))
                i = j + 1
                continue
            if nxt == 0x4F:                 # 'O' - SS3
                if i + 2 >= n:
                    break
                final = chr(buf[i + 2])
                keys.append(Key(_ARROWS.get(final, "unknown")))
                i += 3
                continue
            keys.append(Key("escape"))
            i += 1
            continue

        if b in (0x0D, 0x0A):
            keys.append(Key("enter"))
            i += 1
            continue
        if b in (0x7F, 0x08):
            keys.append(Key("backspace"))
            i += 1
            continue
        if b == 0x09:
            keys.append(Key("tab"))
            i += 1
            continue
        if b < 0x20:
            keys.append(Key(f"ctrl-{chr(b + 96)}"))
            i += 1
            continue

        width = _utf8_len(b)
        if i + width > n:
            break                           # incomplete UTF-8
        try:
            char = buf[i:i + width].decode("utf-8")
        except UnicodeDecodeError:
            char = buf[i:i + 1].decode("latin-1")
            width = 1
        keys.append(Key("char", char=char))
        i += width

    return keys, buf[i:]


class KeyReader:
    """Puts the terminal in raw mode and yields Key events.

    Terminal resizes arrive as ``Key("resize")`` via a SIGWINCH self-pipe, so
    the main loop only ever selects on file descriptors.
    """

    def __init__(self, fd: int | None = None):
        self.fd = sys.stdin.fileno() if fd is None else fd
        self._buf = b""
        self._saved = None
        self._wake_r = self._wake_w = None
        self._prev_handler = None
        self._pending_escape_at: float | None = None

    def __enter__(self) -> "KeyReader":
        self._saved = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        self._wake_r, self._wake_w = os.pipe()
        os.set_blocking(self._wake_r, False)
        os.set_blocking(self._wake_w, False)
        self._prev_handler = signal.signal(signal.SIGWINCH, self._on_winch)
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _on_winch(self, *_args) -> None:
        try:
            os.write(self._wake_w, b"W")
        except OSError:
            pass

    def close(self) -> None:
        if self._prev_handler is not None:
            signal.signal(signal.SIGWINCH, self._prev_handler)
            self._prev_handler = None
        if self._saved is not None:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, self._saved)
            self._saved = None
        for fd in (self._wake_r, self._wake_w):
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
        self._wake_r = self._wake_w = None

    def read(self, timeout: float | None = None) -> list[Key]:
        watch = [self.fd]
        if self._wake_r is not None:
            watch.append(self._wake_r)

        ready, _, _ = select.select(watch, [], [], timeout)
        events: list[Key] = []

        if self._wake_r in ready:
            try:
                os.read(self._wake_r, 64)
            except OSError:
                pass
            events.append(Key("resize"))

        if self.fd in ready:
            chunk = os.read(self.fd, 1024)
            if not chunk:
                events.append(Key("eof"))
                return events
            self._buf += chunk

        keys, self._buf = parse_keys(self._buf)
        events.extend(keys)

        # A lone ESC that never grew into a sequence is the escape key.
        if self._buf == b"\x1b" and not ready:
            events.append(Key("escape"))
            self._buf = b""

        return events
