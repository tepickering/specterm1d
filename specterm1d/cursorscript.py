"""Batch cursor scripts.

splot takes a `cursor` parameter naming a file of cursor commands. The same
idea here gives batch plotting and, more usefully, end-to-end tests that never
touch a terminal.
"""
from __future__ import annotations

from dataclasses import dataclass

from specterm1d.term.input import Key

_NAMED = {
    "<space>": " ",
    "<enter>": "\n",
    "<return>": "\n",
    "<escape>": "\x1b",
    "<esc>": "\x1b",
    "<tab>": "\t",
}


@dataclass
class ScriptStep:
    x: float | None
    y: float | None
    keys: list[str]


def _coordinate(token: str, lineno: int) -> float | None:
    if token == "-":
        return None
    try:
        return float(token)
    except ValueError:
        raise ValueError(
            f"line {lineno}: {token!r} is not a number or '-'"
        ) from None


def parse_script(text: str) -> list[ScriptStep]:
    steps: list[ScriptStep] = []

    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith(":"):
            steps.append(ScriptStep(None, None,
                                    [":", *line[1:], "\n"]))
            continue

        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"line {lineno}: expected '<x> <y> <key> [text]'")

        x = _coordinate(parts[0], lineno)
        y = _coordinate(parts[1], lineno)

        token = parts[2]
        if token in _NAMED:
            keys = [_NAMED[token]]
        elif len(token) == 1:
            keys = [token]
        else:
            raise ValueError(f"line {lineno}: {token!r} is not a single key")

        if len(parts) > 3:
            keys.extend(list(" ".join(parts[3:])))
            keys.append("\n")

        steps.append(ScriptStep(x, y, keys))

    return steps


def _as_key(char: str) -> Key:
    if char == "\n":
        return Key("enter")
    if char == "\x1b":
        return Key("escape")
    return Key("char", char)


def run_script(session, steps: list[ScriptStep]) -> None:
    for step in steps:
        if session.finished:
            return
        if step.x is not None:
            session.view.cursor_x = step.x
        if step.y is not None:
            session.view.cursor_y = step.y
        for char in step.keys:
            if session.handle(_as_key(char)) is False:
                session.finished = True
                return
