"""scripts/live_check.py's verdict rule and its file path, with the models and the face finder swapped out."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import live_check  # noqa: E402


class FakeScorer:
    """Each model's "P(fake)" is the face picture's mean brightness / 255; the percentile scale is the identity."""
    models = ("run5", "gend")

    def __init__(self):
        self.calls = 0

    def score(self, face_bgr):
        self.calls += 1
        v = float(np.asarray(face_bgr).mean()) / 255
        return {"run5": v, "gend": v}

    def combined(self, by_model):
        return float(np.mean(list(by_model.values())))


def grey(level):
    return np.full((256, 256, 3), level, dtype=np.uint8)


def test_running_check_waits_for_eight_faces_then_flags_at_the_cutoff():
    check = live_check.RunningCheck(FakeScorer(), cutoff=0.5)
    for i in range(7):
        score, average, verdict = check.update(grey(204))          # 0.8 each
        assert verdict == f"checking {i + 1}/8" and score == pytest.approx(0.8)
    assert check.update(None) == (None, pytest.approx(0.8), "checking 7/8")   # no face: nothing added
    assert check.update(grey(204))[2] == "LIKELY FAKE"
    for _ in range(8):
        score, average, verdict = check.update(grey(51))            # 0.2: the window fills with real-looking faces
    assert verdict == "looks real" and average == pytest.approx(0.2)


def write_clip(path, frames):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (64, 64))
    for frame in frames:
        writer.write(frame)
    writer.release()


def noisy(level, rng):
    """A bright frame with camera-like noise, so no two frames are the same picture."""
    return np.clip(level + rng.integers(-12, 13, size=(64, 64, 3)), 0, 255).astype(np.uint8)


def test_check_video_scores_a_file_on_the_live_timing(tmp_path):
    rng = np.random.default_rng(0)
    path = tmp_path / "clip.avi"
    write_clip(path, [noisy(230, rng) for _ in range(50)])          # 5 s at 10 frames/s
    seen = []
    finder = lambda frame: seen.append(frame.shape) or (32, 32, 20, 0.9 if len(seen) != 3 else 0.4)
    rows = []
    out = live_check.check_video(path, FakeScorer(), finder, cutoff=0.5, on_row=rows.append)
    assert out == rows and [r["seconds"] for r in rows] == [0.5 * k for k in range(10)]   # twice a second
    assert len(seen) == 10                                          # faces looked for only on checked frames
    assert rows[2]["face_found"] is False and rows[2]["face_px"] is None   # under the finder's confidence floor
    assert rows[0]["face_px"] == 20 and rows[0]["frame"] == "64x64"       # Oct 23: face size and capture size logged
    assert [r["verdict"] for r in rows[:8]] == [f"checking {n}/8" for n in (1, 2, 2, 3, 4, 5, 6, 7)]
    assert [r["verdict"] for r in rows[8:]] == ["LIKELY FAKE"] * 2 and rows[9]["average"] > 0.8   # 8 faces held


def test_a_paused_player_is_logged_as_paused_and_not_scored_again(tmp_path):
    # Oct 23: a paused video (or a frozen feed) repeats one decoded frame; before, every check scored the same face
    # again and the window filled with one score. Frames 2.0-4.5 s are one frame repeated.
    rng = np.random.default_rng(1)
    path = tmp_path / "paused.avi"
    frozen = noisy(230, rng)
    write_clip(path, [noisy(230, rng) for _ in range(20)] + [frozen] * 30 + [noisy(230, rng) for _ in range(10)])
    scorer = FakeScorer()
    rows = live_check.check_video(path, scorer, lambda frame: (32, 32, 20, 0.9), cutoff=0.5)
    verdicts = [r["verdict"] for r in rows]
    assert verdicts[:4] == ["checking 1/8", "checking 2/8", "checking 3/8", "checking 4/8"]
    assert verdicts[4] != "paused"                                  # 2.0 s: the first frozen frame is new
    assert verdicts[5:10] == ["paused"] * 5 and all(r["face_score"] is None and r["average"] is None for r in rows[5:10])
    assert verdicts[10:] == ["checking 6/8", "checking 7/8"]        # the window went on where it left off
    assert scorer.calls == 7                                        # 12 checks, 5 of them paused


def test_the_most_suspicious_moments_are_kept_as_pictures(tmp_path):
    # Oct 25: frames at 1, 4 and 7 s are bright, so the stand-in scorer finds their "faces" most fake-looking.
    from chimera.evidence_frames import TopFrames
    rng = np.random.default_rng(2)
    path = tmp_path / "bright.avi"
    write_clip(path, [noisy(240 if n in (10, 40, 70) else 100, rng) for n in range(100)])     # 10 s
    frames = TopFrames(tmp_path / "bright_frames", keep=3, autosave=True, meta={"kind": "live", "cutoff": 0.5})
    live_check.check_video(path, FakeScorer(), lambda frame: (32, 32, 20, 0.9), cutoff=0.5, frames=frames)
    manifest = json.loads((tmp_path / "bright_frames" / "manifest.json").read_text())
    assert {m["t"] for m in manifest["moments"]} == {1.0, 4.0, 7.0}
    for m in manifest["moments"]:
        from chimera.detector import SHOWN
        assert m["score"] > 0.85 and set(m["models"]) == {SHOWN["run5"], "GenD"} and m["verdict"]
        assert (tmp_path / "bright_frames" / m["face"]).is_file() and (tmp_path / "bright_frames" / m["frame"]).is_file()
    assert cv2.imread(str(tmp_path / "bright_frames" / manifest["moments"][0]["frame"])).shape == (64, 64, 3)


def test_cutoff_names():
    class Ref:
        live_cutoff, moderate = None, 0.8713
    assert live_check.resolve_cutoff(None, Ref()) == (0.25, "webcam through the meeting app (Oct 19 test set, provisional)")
    assert live_check.resolve_cutoff("public", Ref())[0] == 0.8713 and "public" in live_check.resolve_cutoff("public", Ref())[1]
    assert live_check.resolve_cutoff("0.3", Ref()) == (0.3, "set by hand")
    Ref.live_cutoff = 0.31
    assert live_check.resolve_cutoff("live", Ref())[0] == 0.31
    assert live_check.is_paused(np.zeros((72, 128), np.float32), np.zeros((72, 128), np.float32))
    assert not live_check.is_paused(np.zeros((72, 128), np.float32), np.full((72, 128), 0.5, np.float32))
    assert not live_check.is_paused(np.zeros((72, 128), np.float32), None)
