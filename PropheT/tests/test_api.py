"""Chimera Console API: cases, the pipeline job, the mock flow and the checks, uploads, and the live feed."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from chimera.api import Settings, create_app

REPO = Path(__file__).resolve().parents[1]


def wait(client, job_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] != "running":
            return job
        time.sleep(0.2)
    raise AssertionError("job did not finish")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    root = tmp_path_factory.mktemp("console")
    data, cases = root / "data", root / "cases"
    subprocess.run([sys.executable, str(REPO / "synth" / "make_synthetic.py"), "--data", str(data), "--cases", str(cases)],
                   check=True, capture_output=True)
    settings = Settings(cases_dir=cases, out_dir=root / "out", watchlist=data / "watchlist_synthetic.csv",
                        live_logs=root / "live_logs", langflow_url="", langflow_flow_id="", langflow_api_key="",
                        langflow_timeout=5, mock_flow=True)
    # The Console answers only its own host names (Oct 23), so the test client speaks as the browser on this machine.
    return TestClient(create_app(settings), base_url="http://127.0.0.1:8420")


def test_health_and_case_list_before_scoring(client):
    health = client.get("/api/health").json()
    assert health["ok"] and health["cases"] == 10 and health["agents"]["mode"] == "mock"
    cases = client.get("/api/cases").json()
    assert len(cases) == 10 and all(c["score"] is None for c in cases)
    assert client.get("/api/cases/nope").status_code == 404
    assert client.get("/api/cases/bad id!").status_code == 400


def test_pipeline_job_scores_every_case(client):
    job = client.post("/api/run").json()
    done = wait(client, job["id"])
    assert done["status"] == "done", done["log"][-5:]
    cases = client.get("/api/cases").json()
    assert all(c["score"] is not None for c in cases)
    assert {c["band"] for c in cases} <= {"Low", "Review", "High"}
    detail = client.get("/api/cases/case_005").json()
    assert detail["evidence"]["band"] == "High" and "## [A3] Application" in detail["evidence_md"]
    # The case list carries the most critical evidence line's code and data, for the Simple view's tiles.
    crit = next(c for c in cases if c["case_id"] == "case_005")["critical_signal"]
    assert crit["evidence_id"] == detail["evidence"]["most_critical"]
    assert crit["code"] == "watchlist_match" and crit["data"]["field"] == "email"
    events = client.get(f"/api/jobs/{job['id']}/events").text
    assert "event: status" in events


def test_mock_flow_passes_both_checks_for_every_case(client):
    for case in client.get("/api/cases").json():
        job = client.post(f"/api/cases/{case['case_id']}/analyze").json()
        done = wait(client, job["id"])
        assert done["status"] == "done", done["log"]
        assert done["result"] == {"mode": "mock", "bundle_problems": False, "evidence_problems": False}, case["case_id"]
    detail = client.get("/api/cases/case_005").json()
    assert detail["report"].startswith("MOST CRITICAL FINDING:")
    assert "Mock flow" in detail["report"] and detail["flow_meta"]["mode"] == "mock"
    assert "- none" in detail["bundle_check"] and "- none" in detail["evidence_check"]


def test_report_goes_out_of_date_when_the_evidence_changes(client):
    # Oct 19: a report and its checks describe the evidence the agents were given. flow_meta.json keeps a
    # fingerprint of it, and the case says when the evidence on file now is different.
    out = Path(client.get("/api/settings").json()["out_dir"]) / "case_005"
    fresh = client.get("/api/cases/case_005").json()
    assert fresh["report_stale"] is False and len(fresh["flow_meta"]["evidence_sha256"]) == 64
    # Collecting the evidence again rewrites evidence.md; the same lines keep the report up to date.
    assert wait(client, client.post("/api/run").json()["id"])["status"] == "done"
    assert client.get("/api/cases/case_005").json()["report_stale"] is False
    original = (out / "evidence.md").read_text(encoding="utf-8")
    (out / "evidence.md").write_text(original + "- E3.9 (strong, 3 pts) a line the agents never saw\n", encoding="utf-8")
    stale = client.get("/api/cases/case_005").json()
    assert stale["report_stale"] is True and stale["report_stale_why"] == "changed"
    listed = next(c for c in client.get("/api/cases").json() if c["case_id"] == "case_005")
    assert listed["report_stale"] is True
    # A report from before Oct 19 has no fingerprint: a newer evidence.md is the only sign.
    (out / "evidence.md").write_text(original, encoding="utf-8")
    meta = json.loads((out / "flow_meta.json").read_text(encoding="utf-8"))
    del meta["evidence_sha256"]
    (out / "flow_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    written = (out / "report.md").stat().st_mtime
    os.utime(out / "evidence.md", (written + 60, written + 60))
    old = client.get("/api/cases/case_005").json()
    assert old["report_stale"] is True and old["report_stale_why"] == "collected_again"
    os.utime(out / "evidence.md", (written - 60, written - 60))
    assert client.get("/api/cases/case_005").json()["report_stale"] is False
    # Running the analysts again brings it up to date; a case without a report has no answer.
    assert wait(client, client.post("/api/cases/case_005/analyze").json()["id"])["status"] == "done"
    again = client.get("/api/cases/case_005").json()
    assert again["report_stale"] is False and again["flow_meta"]["evidence_sha256"] == fresh["flow_meta"]["evidence_sha256"]
    created = client.post("/api/cases", data={"name": "No Report Yet", "case_id": "case_norep"}).json()
    assert created["report_stale"] is None
    assert client.delete("/api/cases/case_norep").json() == {"deleted": "case_norep"}

def test_analyze_needs_evidence_first(client):
    created = client.post("/api/cases", data={"name": "Needs Evidence", "case_id": "case_noev"}).json()
    assert created["case_id"] == "case_noev"
    assert client.post("/api/cases/case_noev/analyze").status_code == 409
    assert client.delete("/api/cases/case_noev").json() == {"deleted": "case_noev"}


def test_create_case_with_resume_and_score_it(client, tmp_path):
    from reportlab.pdfgen import canvas
    pdf = tmp_path / "resume.pdf"            # pytest's own temporary folder, so it works on Windows too
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 720, "Jane Example. Backend engineer, 6 years of Python.")
    c.save()
    with pdf.open("rb") as f:
        created = client.post("/api/cases", data={
            "name": "Jane Example", "emails": "jane@example.org", "phones": "+14155550123",
            "country": "US", "ip": "203.0.113.9", "ip_country": "US", "asn": "14061", "asn_org": "DigitalOcean",
            "line_type": "nonFixedVoip", "carrier": "Example VoIP", "camera_refused": "true",
        }, files={"resume": ("resume.pdf", f, "application/pdf")}).json()
    cid = created["case_id"]
    assert cid.startswith("case_") and created["has_resume"]
    assert client.post("/api/cases", data={"name": "dup", "case_id": cid}).status_code == 409
    done = wait(client, client.post("/api/run").json()["id"])
    assert done["status"] == "done"
    detail = client.get(f"/api/cases/{cid}").json()
    codes = {s["code"] for s in detail["evidence"]["signals"]}
    assert {"hosting_ip", "voip_phone", "camera_refused"} <= codes
    # A1 (camera refused, 2) and A3 (hosting IP + VoIP, 4) are two families with 2+ points, so High.
    points = detail["evidence"]["family_points"]
    assert points["A1"] == 2 and points["A3"] >= 4 and detail["evidence"]["band"] == "High"
    assert client.get(f"/api/cases/{cid}/files/resume.pdf").status_code == 200
    assert client.get(f"/api/cases/{cid}/files/../application.json").status_code in (404, 400)


def test_recording_chunks_and_liveness_window(client):
    cid = "case_001"
    for seq, chunk in enumerate([b"\x1aE\xdf\xa3first", b"second", b"third"]):
        r = client.post(f"/api/cases/{cid}/recording?seq={seq}", content=chunk).json()
    assert r["bytes"] == len(b"\x1aE\xdf\xa3first" + b"second" + b"third")
    iv = client.post(f"/api/cases/{cid}/interview", json={"recording_saved": True, "liveness_step": {"start_s": 40, "end_s": 70}}).json()
    assert iv["recording"] == "interview.webm" and iv["liveness_step"]["end_s"] == 70
    assert client.get("/api/cases").json()[0]["has_recording"]
    iv = client.post(f"/api/cases/{cid}/interview", json={"clear_recording": True}).json()
    assert iv["recording"] is None and not client.get("/api/cases").json()[0]["has_recording"]


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is not installed")
def test_a_meeting_recording_and_the_candidates_track_can_be_added(client, tmp_path):
    # Oct 19: a recording made in Zoom comes in as files: the video, and the candidate's own audio track.
    cid = "case_002"
    video, track = tmp_path / "zoom.mp4", tmp_path / "audioCandidate.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10", "-f", "lavfi",
                    "-i", "sine=frequency=300", "-t", "1", "-shortest", "-pix_fmt", "yuv420p", str(video)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=300", "-t", "1", str(track)], check=True)
    url = f"/api/cases/{cid}/recording/file"
    with video.open("rb") as v:
        assert client.post(url, files={"video": ("zoom.mp4", v, "video/mp4")}).status_code == 400      # no consent
    assert client.post(url, data={"consent": "true"}).status_code == 400                             # no file
    assert client.post(url, data={"consent": "true"}, files={"video": ("notes.txt", b"hi", "text/plain")}).status_code == 400
    with track.open("rb") as t:                                                                       # sound only
        assert client.post(url, data={"consent": "true"}, files={"video": ("zoom.mp4", t, "video/mp4")}).status_code == 400
    with video.open("rb") as v, track.open("rb") as t:
        iv = client.post(url, data={"consent": "true"}, files={"video": ("zoom.mp4", v, "video/mp4"),
                                                               "audio": ("audioCandidate.m4a", t, "audio/mp4")}).json()
    assert iv["recording"] == "interview.mp4" and iv["audio"] == "interview_audio.m4a" and iv["recording_source"] == "file"
    assert client.get(f"/api/cases/{cid}/files/interview.mp4").status_code == 200
    assert client.get(f"/api/cases/{cid}/files/interview_audio.m4a").status_code == 200
    assert next(c for c in client.get("/api/cases").json() if c["case_id"] == cid)["has_recording"]
    # A tab capture replaces it, and its sound is the meeting's mixed audio, so the old track goes too.
    client.post(f"/api/cases/{cid}/recording?seq=0", content=b"\x1aE\xdf\xa3webm")
    iv = client.post(f"/api/cases/{cid}/interview", json={"recording_saved": True}).json()
    assert iv["recording"] == "interview.webm" and iv["audio"] is None and iv["recording_source"] == "tab capture"
    assert client.get(f"/api/cases/{cid}/files/interview.mp4").status_code == 404
    assert client.get(f"/api/cases/{cid}/files/interview_audio.m4a").status_code == 404
    iv = client.post(f"/api/cases/{cid}/interview", json={"clear_recording": True}).json()
    assert iv["recording"] is None and client.get(f"/api/cases/{cid}/files/interview.webm").status_code == 404

def test_live_feed_tails_the_newest_log(client):
    logs = Path(client.get("/api/settings").json()["live_logs"])
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "camera0_x.csv").write_text("seconds,face_found,face_score,average_last_8,verdict\n0.0,True,0.9,0.9,checking 1/8\n", encoding="utf-8")
    body = client.get("/api/live/events?max_seconds=1").text
    assert "camera0_x.csv" in body and '"face_score": "0.9"' in body
    assert '"cutoff": "0.601"' in body          # a log from before Oct 19 has no cut-off column: Run 3's line


def test_live_feed_passes_on_the_logs_cutoff(client):
    logs = Path(client.get("/api/settings").json()["live_logs"])
    logs.mkdir(parents=True, exist_ok=True)
    newer = logs / "camera0_y.csv"
    newer.write_text("seconds,face_found,face_score,average_last_8,verdict,cutoff\n"
                     "4.0,True,0.31,0.28,LIKELY FAKE,0.25\n", encoding="utf-8")
    later = time.time() + 60
    os.utime(newer, (later, later))             # the feed follows the newest file
    body = client.get("/api/live/events?max_seconds=1").text
    assert "camera0_y.csv" in body and '"cutoff": "0.25"' in body and '"verdict": "LIKELY FAKE"' in body


def test_one_job_at_a_time(client):
    # Oct 23 review, finding 6: a second run would write out/ at once, or evict the agents' model mid-answer.
    first = client.post("/api/run").json()
    second = client.post("/api/run")
    assert second.status_code == 409
    assert "already running" in second.json()["error"] and second.json()["running"]["id"] == first["id"]
    assert client.post("/api/cases/case_001/analyze").status_code == 409
    assert wait(client, first["id"])["status"] == "done"
    again = client.post("/api/cases/case_001/analyze")                      # free again
    assert again.status_code == 200 and wait(client, again.json()["id"])["status"] == "done"


def test_consent_is_written_into_the_case(client):
    # Oct 23 review, finding 10: consent was a form field and never kept, so `python -m chimera lookup` skipped
    # every console-created case. Now the New case form's box and the recording consent land in application.json.
    created = client.post("/api/cases", data={"name": "Consenting Person", "case_id": "case_consent",
                                              "identity_consent": "true"}).json()
    cases = Path(client.get("/api/settings").json()["cases_dir"])
    app_json = json.loads((cases / "case_consent" / "application.json").read_text(encoding="utf-8"))
    assert app_json["consent"]["identity_checks"] is True and app_json["consent"]["recorded_by"] == "console"
    assert len(app_json["consent"]["recorded_at"]) == 19
    client.post("/api/cases/case_consent/recording?seq=0", content=b"\x1aE\xdf\xa3webm")
    client.post("/api/cases/case_consent/interview", json={"recording_saved": True, "consent": True})
    app_json = json.loads((cases / "case_consent" / "application.json").read_text(encoding="utf-8"))
    assert app_json["consent"]["recording"]["recorded_by"] == "console capture" and app_json["consent"]["identity_checks"]
    no = client.post("/api/cases", data={"name": "No Consent", "case_id": "case_noconsent"}).json()
    assert "consent" not in json.loads((cases / "case_noconsent" / "application.json").read_text(encoding="utf-8"))
    for cid in ("case_consent", "case_noconsent"):
        assert client.delete(f"/api/cases/{cid}").status_code == 200


def test_resume_upload_is_capped_and_must_be_pdf_or_text(client):
    # Oct 23 review, finding 12: the whole file was read before the 10 MB check, and any bytes became resume.txt.
    cases = Path(client.get("/api/settings").json()["cases_dir"])
    docx_like = b"PK\x03\x04" + b"\x00" * 64 + b"word/document.xml"
    r = client.post("/api/cases", data={"name": "Docx", "case_id": "case_docx"},
                    files={"resume": ("resume.docx", docx_like, "application/octet-stream")})
    assert r.status_code == 400 and "PDF or a plain-text" in r.json()["error"]
    assert not (cases / "case_docx").exists()                        # nothing half-made
    r = client.post("/api/cases", data={"name": "Text", "case_id": "case_text"},
                    files={"resume": ("resume.txt", "Plain text resume, 6 years of Go.".encode(), "text/plain")})
    assert r.status_code == 200 and (cases / "case_text" / "resume.txt").is_file()
    big = b"%PDF-1.4\n" + b"0" * (10 * 1024 * 1024)
    r = client.post("/api/cases", data={"name": "Big", "case_id": "case_big"},
                    files={"resume": ("resume.pdf", big, "application/pdf")})
    assert r.status_code == 413 and not (cases / "case_big").exists()
    assert client.delete("/api/cases/case_text").status_code == 200


def test_create_case_with_an_id_document_and_the_face_match_consent(client, tmp_path):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import make_specimen_id as spec
    page = tmp_path / "id.png"
    spec.render(page, "Example", "Jane")
    with page.open("rb") as f:
        created = client.post("/api/cases", data={"name": "Jane Example", "id_face_consent": "true"},
                              files={"id_document": ("passport.png", f, "image/png")}).json()
    cid = created["case_id"]
    assert created["has_id_document"]
    case = client.get(f"/api/cases/{cid}/files/application.json").json()
    assert case["id_document"] == "id_document.png" and case["consent"]["id_face_match"]["recorded_by"] == "console"
    assert client.get(f"/api/cases/{cid}/files/id_document.png").status_code == 200
    # Not an image: refused before anything is written.
    bad = client.post("/api/cases", data={"name": "X", "case_id": "case_badid"},
                      files={"id_document": ("id.png", b"%PDF-1.7 not an image", "image/png")})
    assert bad.status_code == 400 and "JPEG or PNG" in bad.json()["error"]
    assert client.get("/api/cases/case_badid").status_code == 404
