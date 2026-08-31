"""splot.log-compatible measurement log.

Formats are taken verbatim from IRAF's noao/onedspec/splot sources so that
existing log-parsing scripts keep working:

  anshdr.x   image header  "\\n%s [%s%s]: %s\\n"
             column header "%10s%10s%10s%10s%10s%10s%10s\\n", omitted for 'm'
  eqwidth.x  e  " %9.7g %9.7g %9.6g %9.4g\\n"
  gfit.x     k  " %9.7g %9.7g %9.6g %9.4g %9.6g %9.4g %9.4g\\n"
  avgsnr.x   m  "avg: %10.4g  rms: %10.4g   snr: %8.2f\\n"
"""
from __future__ import annotations

import time
from pathlib import Path

COLUMN_HEADER = (
    f"{'center':>10}{'cont':>10}{'flux':>10}"
    f"{'eqw':>10}{'core':>10}{'gfwhm':>10}{'lfwhm':>10}"
)

# Keys that share the seven-column layout.
_PROFILE_KINDS = {"k", "h", "d"}


class SplotLog:
    def __init__(self, path="splot.log", enabled: bool = True):
        self.path = Path(path)
        self.enabled = enabled
        self.lines: list[str] = []
        self._last_kind: str | None = None

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def _write(self, line: str) -> None:
        self.lines.append(line)
        if not self.enabled:
            return
        with self.path.open("a") as handle:
            handle.write(line + "\n")

    def image_header(self, name: str, title: str = "", section: str = "") -> None:
        stamp = time.strftime("%a %H:%M:%S %d-%b-%Y")
        self._write("")
        self._write(f"{stamp} [{name}{section}]: {title}")
        self._last_kind = None

    def comment(self, text: str) -> None:
        self._write(f"# {text}")

    def record(self, kind: str, **values) -> None:
        if kind != "m" and kind != self._last_kind:
            self._write(COLUMN_HEADER)
        self._last_kind = kind

        if kind == "m":
            self._write(
                f"avg: {values['avg']:10.4g}  rms: {values['rms']:10.4g}"
                f"   snr: {values['snr']:8.2f}"
            )
            return

        if kind in _PROFILE_KINDS:
            self._write(
                f" {values['center']:9.7g} {values['cont']:9.7g}"
                f" {values['flux']:9.6g} {values['eqw']:9.4g}"
                f" {values['peak']:9.6g} {values['gfwhm']:9.4g}"
                f" {values['lfwhm']:9.4g}"
            )
            return

        self._write(
            f" {values['center']:9.7g} {values['cont']:9.7g}"
            f" {values['flux']:9.6g} {values['eqw']:9.4g}"
        )
