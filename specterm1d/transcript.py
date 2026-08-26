"""Scrolling text output for the terminal half of two-window mode.

Not a layout. In GUI mode the terminal is what it was under ``xgterm``: a
transcript that scrolls past while the graphics window holds the plot. Two
operations, because an in-progress prompt and a finished line behave
differently - the prompt is overwritten in place, the line is appended.
"""
from __future__ import annotations

ERASE_EOL = "\x1b[K"


class Transcript:
    def __init__(self, out):
        self.out = out
        self._open_prompt = False

    def line(self, text: str) -> None:
        """A finished line. Terminates any open prompt first."""
        if self._open_prompt:
            self.out.write("\n")
            self._open_prompt = False
        self.out.write(text + "\n")
        self.out.flush()

    def prompt(self, text: str) -> None:
        """Redraw an in-progress prompt in place, with no newline.

        AwaitLine echoes on every keystroke; without this a 30-character colon
        command would leave 30 lines of transcript. Erase-to-EOL covers the
        backspace case, where the new text is shorter than what it replaces.
        """
        self.out.write("\r" + text + ERASE_EOL)
        self.out.flush()
        self._open_prompt = True
