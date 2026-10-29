"""The PDF report (chimera/report_pdf.py) and the evidence pictures in the Console API (Oct 25). Synthetic cases and flat
test arrays only: no face, recording or real applicant is involved."""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
import pytest
from fastapi.testclient import TestClient

from chimera import evidence_frames as ef
from chimera import report_pdf
from chimera.api import Settings, create_app

REPO = Path(__file__).resolve().parents[1]
FACE = np.full((256, 256, 3), 128, np.uint8)
FRAME = np.full((360, 640, 3), 64, np.uint8)


def pdf_text(data: bytes) -> str:
    doc = pdfium.PdfDocument(data)
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def wait(client, job_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


@pytest.fixture(scope="module")
def console(tmp_path_factory):
    root = tmp_path_factory.mktemp("console_pdf")
    data, cases = root / "data", root / "cases"
    subprocess.run([sys.executable, str(REPO / "synth" / "make_synthetic.py"), "--data", str(data), "--cases", str(cases)],
                   check=True, capture_output=True)
    settings = Settings(cases_dir=cases, out_dir=root / "out", watchlist=data / "watchlist_synthetic.csv",
                        live_logs=root / "live_logs", langflow_url="", langflow_flow_id="", langflow_api_key="",
                        langflow_timeout=5, mock_flow=True)
    client = TestClient(create_app(settings), base_url="http://127.0.0.1:8420")
    assert wait(client, client.post("/api/run").json()["id"])["status"] == "done"
    assert wait(client, client.post("/api/cases/case_005/analyze").json()["id"])["status"] == "done"
    return client, settings


def recording_frames(settings, case_id="case_005"):
    top = ef.TopFrames(meta={"kind": "recording", "source": "interview.mp4", "cutoffs": {"moderate": 0.18, "strong": 0.21}})
    for t, s in ((3, 0.9), (9, 0.95), (15, 0.4)):
        top.offer(t, s, FACE, FRAME, (320, 180, 120), extra={"models": {"Run 3": 0.2, "Run 5z": 0.9, "GenD": 0.8}})
    return top.save(settings.out_dir / case_id / "evidence_frames")


def live_session(settings, name="camera0_20261025-190000"):
    settings.live_logs.mkdir(parents=True, exist_ok=True)
    (settings.live_logs / f"{name}.csv").write_text("seconds,face_found\n0.5,True\n")
    top = ef.TopFrames(settings.live_logs / f"{name}_frames", meta={"kind": "live", "cutoff": 0.46, "log": f"{name}.csv"},
                       autosave=True)
    top.offer(12.5, 0.97, FACE, FRAME, (320, 180, 120), extra={"average": 0.61, "verdict": "LIKELY FAKE"})
    return name


def test_case_detail_lists_the_recordings_pictures_and_serves_only_them(console):
    client, settings = console
    assert client.get("/api/cases/case_005").json()["frames"] == {"recording": None, "live": None}
    recording_frames(settings)
    frames = client.get("/api/cases/case_005").json()["frames"]
    moments = frames["recording"]["moments"]
    assert [m["t"] for m in moments] == [9.0, 3.0, 15.0] and frames["live"] is None
    face = client.get(f"/api/cases/case_005/frames/recording/{moments[0]['face']}")
    assert face.status_code == 200 and face.headers["content-type"] == "image/png"
    assert client.get(f"/api/cases/case_005/frames/recording/{moments[0]['frame']}").headers["content-type"] == "image/jpeg"
    for bad in ("manifest.json", "..%2Fevidence.json", "m000090_face.gif", "m999999_face.png"):
        assert client.get(f"/api/cases/case_005/frames/recording/{bad}").status_code == 404
    assert client.get("/api/cases/case_005/frames/other/x.png").status_code == 404


def test_a_live_sessions_pictures_can_be_attached_to_a_case_and_removed(console):
    client, settings = console
    assert client.post("/api/cases/case_001/live-frames").status_code == 409        # no live check has run
    log = live_session(settings)
    live = client.get("/api/live/frames").json()
    assert live["log"] == log and live["manifest"]["moments"][0]["verdict"] == "LIKELY FAKE"
    name = live["manifest"]["moments"][0]["frame"]
    assert client.get(f"/api/live/frames/{log}/{name}").status_code == 200
    assert client.get(f"/api/live/frames/{log}/notes.txt").status_code == 404
    assert client.get(f"/api/live/frames/..%5C..%5Cx/{name}").status_code in (400, 404)
    assert client.post("/api/cases/case_001/live-frames", json={"log": "../etc"}).status_code == 404
    assert client.post("/api/cases/case_001/live-frames", content=b"{not json").status_code == 400
    attached = client.post("/api/cases/case_001/live-frames").json()
    assert attached["attached_to"] == "case_001" and attached["from_log"] == log
    detail = client.get("/api/cases/case_001").json()
    assert detail["frames"]["live"]["moments"][0]["t"] == 12.5
    saved_name = detail["frames"]["live"]["moments"][0]["frame"]          # the case's copy has names of its own
    assert saved_name != name and client.get(f"/api/cases/case_001/frames/live/{saved_name}").status_code == 200
    # A page from another site cannot attach pictures (the Console's cross-site guard covers the new routes too).
    assert client.post("/api/cases/case_001/live-frames", headers={"Origin": "http://evil.example"}).status_code == 403
    assert client.delete("/api/cases/case_001/live-frames").status_code == 200
    assert client.get("/api/cases/case_001").json()["frames"]["live"] is None


def test_the_report_downloads_as_a_pdf_with_its_pictures(console):
    client, settings = console
    recording_frames(settings)
    resp = client.get("/api/cases/case_005/report.pdf")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/pdf"
    assert 'filename="case_005_report.pdf"' in resp.headers["content-disposition"]
    assert resp.content.startswith(b"%PDF")
    text = pdf_text(resp.content)
    name = client.get("/api/cases/case_005").json()["name"]
    for needed in (name, "case_005", "High risk", "Written by the mock flow", "What code checked", "Evidence Check",
                   "Most suspicious moments in the recording", "#1 at 0:09", "Decision support only",
                   "for the hiring team only, never for the candidate"):
        assert needed in text, needed


def test_no_pdf_before_the_case_is_checked(console, tmp_path):
    client, settings = console
    (settings.out_dir / "case_010" / "evidence.json").rename(tmp_path / "evidence.json")
    try:
        assert client.get("/api/cases/case_010/report.pdf").status_code == 409
    finally:
        (tmp_path / "evidence.json").rename(settings.out_dir / "case_010" / "evidence.json")


def test_pdf_builder_keeps_unicode_and_says_when_a_report_is_out_of_date(tmp_path):
    folder = tmp_path / "live_frames"
    top = ef.TopFrames(folder, meta={"kind": "live", "cutoff": 0.46, "log": "camera0.csv"}, autosave=True)
    top.offer(61, 0.88, FACE, FRAME, extra={"average": 0.52, "verdict": "LIKELY FAKE", "models": {"run5": 0.93}})
    manifest = {**ef.read_manifest(folder), "attached_at": "2026-10-25T19:00:00", "from_log": "camera0_20261025"}
    detail = {"case_id": "demo_x", "name": "Zoë Núñez-Ødegård", "submitted_at": "2026-10-20",
              "location": {"city": "Ciudad Juárez", "country": "MX"},
              "evidence": {"band": "Review", "score": 4, "critical_line": "MOST CRITICAL FINDING: E1.1 “quoted” – x"},
              "report": "MOST CRITICAL FINDING: E1.1 x\n\n## [A1] Video\n\n- A finding with **bold**.\n\n"
                        "  Evidence: E1.1 \"quote <script>\" [A1]\n\nDecision support only. A person makes the final call.",
              "evidence_check": "EVIDENCE CHECK (code)\n\n- Evidence citations in report: 1; verified: 1\n\n"
                                "EVIDENCE PROBLEMS\n- E1.1 [A1]: quote does not appear verbatim.\n",
              "bundle_check": None, "flow_meta": {"mode": "langflow", "ran_at": "2026-10-24T21:00:00"},
              "report_stale": True, "report_stale_why": "changed"}
    data = report_pdf.build(detail, {"live": (folder, manifest)}, now=datetime(2026, 10, 25, 19, 30))
    text = pdf_text(data)
    for needed in ("Zoë Núñez-Ødegård", "Ciudad Juárez", "Out of date.", "The evidence changed after this report",
                   "Written by the LangFlow agents on 24 Oct 2026", "quote <script>", "1 problem; 1 of 1 quotes verified",
                   "Bundle Check: not run", "Most suspicious moments in the live face check", "camera0_20261025",
                   "#1 at 1:01 into the session", "LIKELY FAKE"):
        assert needed in text, needed
    assert text.count("Decision support only") >= 2                 # the verdict box and every page's footer
    assert "<b>" not in text                                         # markup became formatting, not text


def test_a_live_log_named_after_a_file_with_spaces_can_be_served(console):
    # Oct 26 review: live_check.py names a file's log after the file, so it can hold spaces; a fixed pattern refused
    # every request for its pictures. Now the name only has to be a log that is there.
    client, settings = console
    log = live_session(settings, "my clip 2_20261025-210000")
    listed = client.get("/api/live/frames").json()
    assert listed["log"] == log
    name = listed["manifest"]["moments"][0]["face"]
    assert client.get(f"/api/live/frames/{log}/{name}").status_code == 200
    assert client.post("/api/cases/case_002/live-frames", json={"log": log}).json()["from_log"] == log


def test_replacing_or_removing_a_recording_removes_its_pictures(console):
    client, settings = console
    recording_frames(settings, "case_003")
    assert client.get("/api/cases/case_003").json()["frames"]["recording"]
    assert client.post("/api/cases/case_003/interview", json={"clear_recording": True}).status_code == 200
    assert client.get("/api/cases/case_003").json()["frames"]["recording"] is None


@pytest.mark.parametrize("line,last_word", [
    ("- A finding with `code **inside` and ** after.", "after"),
    ("- **Bold with `code** across` it.", "across"),
    ("- Unbalanced < and & and ** and ` everywhere", "everywhere"),
])
def test_report_text_that_crosses_bold_and_code_still_makes_a_pdf(line, last_word):
    # Oct 26 review: crossed **bold** and `code` spans made misnested markup and the PDF failed with a 500; and an
    # impossible date (2026-02-30) failed it too.
    detail = {"case_id": "x", "name": "N", "evidence": {"band": "Low", "score": 0, "critical_line": line},
              "report": f"## [A2] Resume\n\n{line}\n", "submitted_at": "2026-02-30"}
    text = pdf_text(report_pdf.build(detail))
    assert "an unknown date" in text and last_word in text


def test_attaching_says_so_when_no_picture_could_be_copied(console):
    # Second Oct 26 review: the route answered 200 with null, and the page showed a JavaScript error.
    client, settings = console
    log = live_session(settings, "camera1_20261026-090000")
    folder = settings.live_logs / f"{log}_frames"
    for p in folder.glob("m*_*"):
        p.unlink()                                                      # listed in the manifest, gone from disk
    resp = client.post("/api/cases/case_004/live-frames", json={"log": log})
    assert resp.status_code == 409 and "try again" in resp.json()["error"]
