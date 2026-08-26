# tests/test_transcript.py
import io

from specterm1d.transcript import Transcript


def test_line_appends_a_finished_line():
    out = io.StringIO()
    Transcript(out).line("center = 5001.2")
    assert out.getvalue() == "center = 5001.2\n"


def test_consecutive_lines_scroll():
    out = io.StringIO()
    transcript = Transcript(out)
    transcript.line("one")
    transcript.line("two")
    assert out.getvalue() == "one\ntwo\n"


def test_prompt_redraws_in_place_and_does_not_end_the_line():
    out = io.StringIO()
    Transcript(out).prompt(": show")
    assert out.getvalue() == "\r: show\x1b[K"


def test_consecutive_prompts_do_not_accumulate_lines():
    # AwaitLine echoes on every keystroke. Without in-place redraw a
    # 30-character colon command would leave 30 lines of transcript.
    out = io.StringIO()
    transcript = Transcript(out)
    for text in (":", ":s", ":sh", ":sho", ":show"):
        transcript.prompt(text)
    assert out.getvalue().count("\n") == 0
    assert out.getvalue().endswith("\r:show\x1b[K")


def test_a_line_after_a_prompt_terminates_the_prompt_first():
    out = io.StringIO()
    transcript = Transcript(out)
    transcript.prompt(":show")
    transcript.line("no measurements recorded yet")
    assert out.getvalue() == "\r:show\x1b[K\nno measurements recorded yet\n"


def test_a_line_after_a_finished_line_does_not_add_a_blank():
    out = io.StringIO()
    transcript = Transcript(out)
    transcript.line("one")
    transcript.line("two")
    assert "\n\n" not in out.getvalue()


def test_output_is_flushed_so_prompts_appear_before_the_next_keystroke():
    class Recorder(io.StringIO):
        flushes = 0

        def flush(self):
            type(self).flushes += 1

    out = Recorder()
    transcript = Transcript(out)
    transcript.prompt("x")
    transcript.line("y")
    assert Recorder.flushes >= 2
