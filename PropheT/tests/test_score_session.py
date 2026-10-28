"""scripts/score_session.py without models: finding clips, the cut-offs from real_calib, the summary, installing."""
import csv
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import score_session as ss  # noqa: E402
from chimera import detector as det, voice  # noqa: E402


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    return path


def write_csv(path: Path, rows: list[dict]):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


@pytest.fixture
def session(tmp_path):
    s = tmp_path / "session"
    for i in range(12):
        touch(s / "real_calib" / f"calib_{i:02d}.mp4")
    for i in range(3):
        touch(s / "real_test" / f"test_{i}.mp4")
        touch(s / "swap" / f"swap_{i}.mp4")
        touch(s / "voice" / f"clone_{i}.wav")
    touch(s / "real_calib" / "Audio Record" / "calib_00_candidate.m4a")      # a separate track, not a clip
    touch(s / "real_test" / "audio_mixed_0.m4a")                             # Zoom's mixed audio beside a video
    write_csv(s / "log.csv", [{"file": "calib_00.mp4", "folder": "real_calib", "condition": "webcam mic, Original sound",
                               "audio": "real_calib/Audio Record/calib_00_candidate.m4a"},
                              {"file": "test_0.mp4", "folder": "real_test", "condition": "headset", "audio": ""}])
    return s


def test_clips_come_from_row_folders_and_separate_tracks_are_not_clips(session, monkeypatch):
    clips = ss.discover(session, {}, ss.read_log(session))
    rows = {r: sum(c["row"] == r for c in clips) for r in ("real_calib", "real_test", "swap", "voice")}
    assert rows == {"real_calib": 12, "real_test": 3, "swap": 3, "voice": 3} and len(clips) == 21
    first = next(c for c in clips if c["path"].endswith("calib_00.mp4"))
    assert first["audio"].endswith("calib_00_candidate.m4a") and first["condition"] == "webcam mic, Original sound"
    assert {c["kind"] for c in clips if c["row"] == "voice"} == {"audio"}
    extra = ss.discover(None, {"lipsync": str(session / "swap")}, {})
    assert {c["row"] for c in extra} == {"lipsync"}
    monkeypatch.chdir(session)                               # a relative folder finds the same clips, by full path
    relative = ss.discover(None, {"swap": "swap"}, {})
    assert [c["path"] for c in relative] == [c["path"] for c in clips if c["row"] == "swap"]


def test_cutoffs_come_from_real_calib_and_the_summary_reads_against_real_test(session, tmp_path, monkeypatch):
    ref = tmp_path / "detector_reference.json"
    lists = {m: list(np.linspace(0.0, 1.0, 101)) for m in ("run3", "run5", "gend")}   # percentile ~ the score
    ref.write_text(json.dumps({"scores": lists, "cutoffs": {"moderate": 0.87, "strong": 0.95},
                               "sources": {"public": 101}}), encoding="utf-8")
    monkeypatch.setattr(det, "REFERENCE", ref)
    clips = ss.discover(session, {}, ss.read_log(session))
    out = tmp_path / "out"
    out.mkdir()
    level = {"real_calib": 0.10, "real_test": 0.12, "swap": 0.60}
    video, live, vo = [], [], []
    for k, c in enumerate(clips):
        if c["kind"] == "video":
            v = level[c["row"]] + 0.001 * (k % 5)
            video.append({"row": c["row"], "path": c["path"], "frames": 60, "faces": 60, "run3": 0.0, "run5": v, "gend": v})
            for t in range(10):
                live.append({"row": c["row"], "path": c["path"], "seconds": t / 2, "face_found": True, "face_score": v,
                             "average": v + (0.05 if c["row"] == "real_calib" and t == 9 else 0.0), "decided": t >= 7})
        for key in ss.VOICE_MODELS:
            score = 9.0 + 0.1 * (k % 7) if c["row"] != "voice" else 14.0
            vo.append({"row": c["row"], "path": c["path"], "audio": c["audio"], "model": key, "score": score,
                       "windows": 10, "speech_s": 30, "median": score})
    write_csv(out / "video.csv", video)
    write_csv(out / "live.csv", live)
    write_csv(out / "voice.csv", vo)

    result = ss.build(clips, out, min_calib=10, name="test")
    cut = result["cut"]
    grid = np.asarray(lists["run5"])
    calib_r5g = [ss.percentile(grid, 0.10 + 0.001 * (k % 5)) for k, c in enumerate(clips) if c["row"] == "real_calib"]
    # Oct 24: split conformal over the 12 calibration calls. Moderate targets 10%: k = ceil(13 * 0.9) = 12, so the
    # cut-off goes just above the highest real call and guarantees 1/13 (7.7%). Strong targets 5%, which 12 calls
    # can't certify (it needs 19): the same cut-off, marked not certified.
    from chimera import calibration as cal
    assert cut["r5g"]["moderate"] == cal.strictly_above(max(calib_r5g)) and cut["r5g"]["n"] == 12
    assert cut["r5g"]["bound_moderate"] == pytest.approx(1 / 13, abs=1e-4) and cut["r5g"]["strong"] == cut["r5g"]["moderate"]
    assert cut["live"]["cutoff"] == pytest.approx(0.16) and cut["live"]["highest_real"] == pytest.approx(0.154)
    assert cut["live"]["calls"] == 12 and cut["live"]["bound"] == pytest.approx(1 / 13, abs=1e-4)
    assert cut["dfarena500m"]["n"] == 12 and cut["spectra0"]["strong"] == pytest.approx(9.6001)
    card = json.loads((out / "calibration_card.json").read_text(encoding="utf-8"))
    face = card["detectors"]["face_r5g"]["levels"]
    assert face["moderate"]["certified"] and not face["strong"]["certified"]
    # The fixture's real_test calls sit above every calibration call (0.12 against 0.10): a shifted channel breaks
    # exchangeability, and the card's held-out count is what shows it.
    assert face["moderate"]["leave_one_out"]["n"] == 12 and face["moderate"]["held_out_flagged"] == {"flagged": 3, "n": 3}
    assert card["identity"]["voice"]["spectra0"].startswith("lab260/spectra_0@") and card["unit"] == cal.UNIT
    saved = json.loads((out / "detector_reference.json").read_text(encoding="utf-8"))
    assert saved["scores"] == lists                                   # the percentile scale is unchanged
    assert saved["live_cutoff"] == pytest.approx(0.16) and saved["cutoffs_from"]["real_calib"] == 12
    assert saved["card"]["n"] == 12 and saved["card"]["moderate"]["certified"] and "strong" in saved["card"]
    assert det.Reference.load(out / "detector_reference.json").card["moderate"]["bound"] == pytest.approx(1 / 13, abs=1e-4)
    assert det.Reference.load(out / "detector_reference.json").live_cutoff == pytest.approx(0.16)
    spectra = json.loads((out / "voice_reference_spectra0.json").read_text(encoding="utf-8"))
    assert spectra["model"].startswith("lab260/spectra_0@") and len(spectra["scores"]) == 12
    assert voice.Reference.load(out / "voice_reference_spectra0.json").made_with("spectra0")
    assert voice.Reference.load(out / "voice_reference_spectra0.json").card["n"] == 12

    lines = ss.summarize(result["clips"], cut)
    text = "\n".join(lines)
    assert "a genuine call reaches moderate at most 7.7%" in text
    card_text = "\n".join(ss.card_lines(result["card"]))
    assert "face_r5g" in card_text and "not certifiable with 12 calls (needs 19)" in card_text and "real_test 3 of 3" in card_text
    swap_line = next(l for l in lines if l.startswith("swap "))
    assert "3 (3) of 3" in swap_line and "AUC 1.00" in swap_line and "med 100%, any 3 of 3" in swap_line
    test_line = next(l for l in lines if l.startswith("real_test "))
    assert "any 0 of 3" in test_line                                   # no live false alarm on the held-out reals
    voice_line = next(l for l in lines if l.startswith("voice "))
    assert voice_line.count("3 (3) of 3") == 2 and "AUC 1.00" in voice_line
    assert "webcam mic, Original sound (1)" in text and "against real_test" in text
    ss.write_clips(result["clips"], out, cut)
    rows = list(csv.DictReader(open(out / "clips.csv", encoding="utf-8")))
    assert len(rows) == 21 and {r["live_share_flagged"] for r in rows if r["row"] == "swap"} == {"1.0"}


def test_install_keeps_a_backup_and_writes_each_models_reference(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    old = data / "detector_reference.json"
    old.write_text('{"old": true}', encoding="utf-8")
    monkeypatch.setattr(det, "REFERENCE", old)
    monkeypatch.setattr(voice, "REFERENCE", data / "voice_reference.json")
    monkeypatch.setattr(voice, "ROOT", tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "detector_reference.json").write_text('{"new": true}', encoding="utf-8")
    (out / "voice_reference_spectra0.json").write_text('{"spectra": true}', encoding="utf-8")
    ss.install(out)
    assert json.loads(old.read_text()) == {"new": True}
    assert [p.name for p in data.glob("detector_reference_before_*.json")] and \
        json.loads(next(data.glob("detector_reference_before_*.json")).read_text()) == {"old": True}
    assert json.loads((data / "voice_reference_spectra0.json").read_text()) == {"spectra": True}
    assert not (data / "voice_reference.json").exists()               # no DF Arena reference was made


def test_install_refuses_a_session_scored_with_another_adapter(tmp_path, monkeypatch):
    # Oct 24: Run 5z became the default. A session whose card says it was scored with Run 5 must not put Run 5's
    # cut-offs on Run 5z's scale; one scored with the pipeline's adapter installs, and every replaced file is kept.
    data = tmp_path / "data"
    data.mkdir()
    ref = data / "detector_reference_v5z.json"
    ref.write_text('{"old": true}', encoding="utf-8")
    monkeypatch.setattr(det, "REFERENCE", ref)
    monkeypatch.setattr(det, "MODELS", {**det.MODELS, "run5": tmp_path / "models" / "qwen3vl-deepfake-v5z"})
    monkeypatch.setattr(voice, "REFERENCE", data / "voice_reference.json")
    monkeypatch.setattr(voice, "ROOT", tmp_path)
    (data / "voice_reference_spectra0.json").write_text('{"old spectra": true}', encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "detector_reference.json").write_text('{"new": true}', encoding="utf-8")
    (out / "voice_reference_spectra0.json").write_text('{"spectra": true}', encoding="utf-8")
    card = {"identity": {"run5": {"adapter": "qwen3vl-deepfake-v5"}, "reference": "detector_reference.json"}}
    (out / "calibration_card.json").write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(SystemExit, match="qwen3vl-deepfake-v5 against detector_reference.json"):
        ss.install(out)
    assert json.loads(ref.read_text()) == {"old": True}                       # nothing was replaced
    assert json.loads((data / "voice_reference_spectra0.json").read_text()) == {"old spectra": True}
    card["identity"] = {"run5": {"adapter": "qwen3vl-deepfake-v5z"}, "reference": "detector_reference_v5z.json"}
    (out / "calibration_card.json").write_text(json.dumps(card), encoding="utf-8")
    ss.install(out)
    assert json.loads(ref.read_text()) == {"new": True}
    assert json.loads(next(data.glob("detector_reference_v5z_before_*.json")).read_text()) == {"old": True}
    assert json.loads(next(data.glob("voice_reference_spectra0_before_*.json")).read_text()) == {"old spectra": True}
    assert json.loads((data / "voice_reference_spectra0.json").read_text()) == {"spectra": True}
    installed = json.loads((data / "calibration_card.json").read_text())
    assert installed["identity"]["run5"]["adapter"] == "qwen3vl-deepfake-v5z"
