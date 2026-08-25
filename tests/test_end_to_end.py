# tests/test_end_to_end.py
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from specterm1d.cli import main


@pytest.fixture
def script(tmp_path):
    def write(text):
        path = tmp_path / "script.txt"
        path.write_text(text)
        return path
    return write


def test_dump_writes_a_png(tabular_fits, tmp_path):
    out = tmp_path / "frame.png"
    assert main([str(tabular_fits), "--dump", str(out),
                 "--dump-size", "640x400"]) == 0
    assert out.exists()
    assert Image.open(out).size == (640, 400)


def test_dump_works_without_a_tty(tabular_fits, tmp_path, monkeypatch):
    monkeypatch.setattr("sys.stdout.isatty", lambda: False, raising=False)
    assert main([str(tabular_fits), "--dump", str(tmp_path / "f.png")]) == 0


def test_cursor_script_drives_a_measurement(tabular_fits, tmp_path, script):
    log = tmp_path / "splot.log"
    # 'e' arms the measurement; each continuum point takes its own <space>.
    path = script("5000 1.0 e\n5000 1.0 <space>\n9000 1.0 <space>\n")
    assert main([str(tabular_fits), "--cursor", str(path),
                 "--log", str(log), "--dump", str(tmp_path / "f.png")]) == 0
    assert "center" in log.read_text()


def test_cursor_script_runs_colon_commands(tabular_fits, tmp_path, script):
    log = tmp_path / "splot.log"
    path = script(":# driven from a script\n")
    main([str(tabular_fits), "--cursor", str(path), "--log", str(log),
          "--dump", str(tmp_path / "f.png")])
    assert "driven from a script" in log.read_text()


def test_units_flag_changes_the_axis_label(tabular_fits, tmp_path):
    nm = tmp_path / "nm.png"
    ang = tmp_path / "ang.png"
    main([str(tabular_fits), "--units", "nm", "--dump", str(nm)])
    main([str(tabular_fits), "--dump", str(ang)])
    assert np.any(np.array(Image.open(nm)) != np.array(Image.open(ang)))


def test_zoom_script_changes_the_rendered_frame(tabular_fits, tmp_path, script):
    wide = tmp_path / "wide.png"
    zoomed = tmp_path / "zoomed.png"
    main([str(tabular_fits), "--dump", str(wide)])
    path = script("6000 1.0 z\n- - z\n")
    main([str(tabular_fits), "--cursor", str(path), "--dump", str(zoomed)])
    assert np.any(np.array(Image.open(wide)) != np.array(Image.open(zoomed)))


def test_bad_file_reports_and_exits_nonzero(tmp_path, capsys):
    junk = tmp_path / "junk.fits"
    junk.write_bytes(b"nope")
    assert main([str(junk)]) == 1
    assert "could not load" in capsys.readouterr().err


def test_no_arguments_prints_help(capsys):
    assert main([]) == 2


# ---- golden image --------------------------------------------------

# Anchored to this file, not the working directory: the isolate_cwd fixture
# runs every test from its own tmp_path.
GOLDEN = Path(__file__).parent / "golden" / "tabular_default.png"


def test_default_render_matches_the_golden_image(tabular_fits, tmp_path):
    """Guards against silent plot regressions.

    Regenerate deliberately with SPECTERM1D_REGEN_GOLDEN=1, then LOOK at the
    new image before committing it.
    """
    import os

    out = tmp_path / "frame.png"
    main([str(tabular_fits), "--dump", str(out), "--dump-size", "640x400"])

    golden = GOLDEN
    if os.environ.get("SPECTERM1D_REGEN_GOLDEN"):
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(out.read_bytes())
        pytest.skip("regenerated the golden image")

    if not golden.exists():
        pytest.skip(f"no golden image; create it with "
                    f"SPECTERM1D_REGEN_GOLDEN=1 pytest {__file__}")

    produced = np.asarray(Image.open(out).convert("RGB"), dtype=float)
    expected = np.asarray(Image.open(golden).convert("RGB"), dtype=float)
    assert produced.shape == expected.shape
    # Tolerant of font-hinting differences between matplotlib patch releases.
    assert np.abs(produced - expected).mean() < 2.0
