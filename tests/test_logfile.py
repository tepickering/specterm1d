# tests/test_logfile.py
import re

from specterm1d.logfile import COLUMN_HEADER, SplotLog


def test_column_header_matches_iraf_widths():
    # anshdr.x: "%10s%10s%10s%10s%10s%10s%10s"
    assert (
        f"{'center':>10}{'cont':>10}{'flux':>10}"
        f"{'eqw':>10}{'core':>10}{'gfwhm':>10}{'lfwhm':>10}"
    ) == COLUMN_HEADER
    assert len(COLUMN_HEADER) == 70


def test_image_header_matches_iraf_shape(tmp_path):
    log = SplotLog(tmp_path / "splot.log")
    log.image_header("spec1d_test.fits", "NGC 7662")
    text = (tmp_path / "splot.log").read_text()
    assert re.search(r"\n.* \[spec1d_test\.fits\]: NGC 7662\n", text)


def test_eqw_row_has_four_fields(tmp_path):
    log = SplotLog(tmp_path / "splot.log")
    log.record("e", center=5183.6, cont=1.234, flux=-0.456, eqw=0.37)
    row = log.lines[-1]
    assert row == f" {5183.6:9.7g} {1.234:9.7g} {-0.456:9.6g} {0.37:9.4g}"


def test_profile_row_has_seven_fields(tmp_path):
    log = SplotLog(tmp_path / "splot.log")
    log.record("k", center=5183.6, cont=1.0, flux=-0.5, eqw=0.5,
               peak=-0.9, gfwhm=2.1, lfwhm=0.0)
    row = log.lines[-1]
    assert len(row.split()) == 7


def test_column_header_is_written_once_per_key_change(tmp_path):
    log = SplotLog(tmp_path / "splot.log")
    log.record("e", center=1.0, cont=1.0, flux=1.0, eqw=1.0)
    log.record("e", center=2.0, cont=1.0, flux=1.0, eqw=1.0)
    assert log.lines.count(COLUMN_HEADER) == 1
    log.record("k", center=3.0, cont=1.0, flux=1.0, eqw=1.0,
               peak=1.0, gfwhm=1.0, lfwhm=1.0)
    assert log.lines.count(COLUMN_HEADER) == 2


def test_m_key_suppresses_the_column_header(tmp_path):
    # anshdr.x guards the header with: if (key != 'm')
    log = SplotLog(tmp_path / "splot.log")
    log.record("m", avg=1.0, rms=0.1, snr=10.0)
    assert COLUMN_HEADER not in log.lines


def test_m_row_matches_avgsnr_format(tmp_path):
    log = SplotLog(tmp_path / "splot.log")
    log.record("m", avg=1.5, rms=0.25, snr=6.0)
    assert log.lines[-1] == f"avg: {1.5:10.4g}  rms: {0.25:10.4g}   snr: {6.0:8.2f}"


def test_disabled_log_writes_nothing(tmp_path):
    path = tmp_path / "splot.log"
    log = SplotLog(path, enabled=False)
    log.record("e", center=1.0, cont=1.0, flux=1.0, eqw=1.0)
    assert not path.exists()


def test_reenabling_resumes_writing(tmp_path):
    path = tmp_path / "splot.log"
    log = SplotLog(path, enabled=False)
    log.record("e", center=1.0, cont=1.0, flux=1.0, eqw=1.0)
    log.enable()
    log.record("e", center=2.0, cont=1.0, flux=1.0, eqw=1.0)
    assert path.exists()
    assert "2" in path.read_text()


def test_log_appends_across_sessions(tmp_path):
    path = tmp_path / "splot.log"
    SplotLog(path).record("e", center=1.0, cont=1.0, flux=1.0, eqw=1.0)
    SplotLog(path).record("e", center=2.0, cont=1.0, flux=1.0, eqw=1.0)
    text = path.read_text()
    assert text.count("center") == 2


def test_comment_is_prefixed(tmp_path):
    log = SplotLog(tmp_path / "splot.log")
    log.comment("night 2 standard")
    assert log.lines[-1] == "# night 2 standard"
