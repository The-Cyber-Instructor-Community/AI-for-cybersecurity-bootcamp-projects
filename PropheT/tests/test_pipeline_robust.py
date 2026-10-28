"""One bad file must not stop the batch (Oct 23 review, finding 2).

A case with a resume that is not a PDF, an empty interview recording and a check that raises still gets its
evidence bundle: the broken check becomes an info line that says it failed, every other case is scored as
before, and summary.json lists them all. A case folder whose application.json cannot be read is skipped with a
printed line.
"""

import json
import subprocess
import sys
from pathlib import Path

from chimera import cli, voice

REPO = Path(__file__).resolve().parents[1]


def _batch(tmp_path):
    data, cases, out = tmp_path / "data", tmp_path / "cases", tmp_path / "out"
    subprocess.run([sys.executable, str(REPO / "synth" / "make_synthetic.py"), "--data", str(data),
                    "--cases", str(cases)], check=True, capture_output=True)
    return data, cases, out


def test_a_bad_resume_a_bad_recording_and_a_raising_check_cost_one_case_nothing_but_their_lines(tmp_path, monkeypatch, capsys):
    data, cases, out = _batch(tmp_path)
    bad = cases / "case_bad"
    bad.mkdir()
    (bad / "application.json").write_text(json.dumps({
        "case_id": "case_bad",
        "candidate": {"name": "Broken Files", "emails": ["broken@example.org"], "phones": [],
                      "claimed_location": {"city": "", "state": "", "country": "US"}},
        "application": {"submitted_at": "2026-10-23", "ip": "", "accounts": {}},
        "interview": {"recording": "interview.webm", "camera_refused": False},
    }), encoding="utf-8")
    (bad / "resume.pdf").write_bytes(b"%PDF-1.4 this is not a PDF at all")   # starts like one, parses as nothing
    (bad / "interview.webm").write_bytes(b"")                               # an upload that was cut off
    # The voice check raises on the empty file (ffmpeg has nothing to read); make that certain without ffmpeg.
    monkeypatch.setenv("CHIMERA_DETECTOR", "off")

    def broken_voice(case_dir, case):
        if Path(case_dir).name == "case_bad":
            raise subprocess.CalledProcessError(1, ["ffmpeg", "-i", "interview.webm"])
        return [voice.Signal("A1", "voice_not_configured", "info", "The voice-clone check is switched off (CHIMERA_VOICE=off).")]
    monkeypatch.setattr(voice, "analyze", broken_voice)
    # A case folder nobody can read is skipped, not fatal.
    unreadable = cases / "case_unreadable"
    unreadable.mkdir()
    (unreadable / "application.json").write_text("{not json", encoding="utf-8")

    cli.main(["run", "--cases", str(cases), "--watchlist", str(data / "watchlist_synthetic.xlsx"), "--out", str(out)])
    printed = capsys.readouterr().out
    assert "resume check failed on case_bad: PdfminerException" in printed
    assert "voice check failed: CalledProcessError" in printed
    assert "Skipping case_unreadable" in printed

    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    ids = {row["case_id"] for row in summary["cases"]}
    assert "case_bad" in ids and "case_unreadable" not in ids and len(ids) == 11
    evidence = json.loads((out / "case_bad" / "evidence.json").read_text(encoding="utf-8"))
    codes = {s["code"]: s for s in evidence["signals"]}
    assert codes["resume_check_failed"]["points"] == 0 and codes["resume_check_failed"]["family"] == "A2"
    assert codes["voice_check_failed"]["points"] == 0 and "CalledProcessError" in codes["voice_check_failed"]["text"]
    assert "\n" not in codes["voice_check_failed"]["text"] and '"' not in codes["voice_check_failed"]["text"]
    assert evidence["band"] == "Low"                      # failed checks carry no points
    # The other ten cases are untouched: same bands as the labels say.
    import csv
    with open(cases / "labels.csv", newline="", encoding="utf-8") as f:
        for lab in csv.DictReader(f):
            got = json.loads((out / lab["case_id"] / "evidence.json").read_text(encoding="utf-8"))
            assert got["band"] == lab["expected_band"], lab["case_id"]


def test_template_check_survives_resumes_with_no_words(tmp_path):
    from chimera import templates
    # Two resumes that scrub to nothing (numbers and links only) and one real one: no empty-vocabulary crash.
    reuse = templates.find_reuse({"a": "123 456 https://x.io", "b": "+1 415 555 0000", "c": "Backend engineer with Python"})
    assert reuse == {"a": [], "b": [], "c": []}
    assert cli.failed_signal("A2", "template check", ValueError("empty vocabulary")).code == "template_check_failed"
