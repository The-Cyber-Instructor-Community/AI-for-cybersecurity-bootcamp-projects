"""chimera/detector.py and the A1 signals in chimera/video.py, with the models swapped out.

Real video files and the real frame sampling, cutting and percentile maths get exercised; only the three models
and the MediaPipe face finder are stand-ins (video_helpers.py), so the tests run without a GPU.
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from video_helpers import STEADY, square_finder, write_clip

from chimera import detector as det
from chimera import video

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def reference(moderate=0.95, strong=0.99, n=100):
    """Each model's reference real videos score 0.00 .. 0.99 (n evenly spaced values)."""
    ref = np.linspace(0, 0.99, n)
    return det.Reference({"run3": ref, "run5": ref, "gend": ref}, moderate, strong, {"test": n})


class FakeDetector:
    """Stand-in for the three models: every face gets the same P(fake) per model, except the faces at the times
    listed in `spikes`, which get 0.999 from all three."""

    def __init__(self, levels, spikes=()):
        self.levels, self.spikes = levels, set(spikes)
        self.find_face = square_finder

    def score(self, faces):
        return {m: np.array([0.999 if f.t in self.spikes else p for f in faces]) for m, p in self.levels.items()}


# --- frames and faces ------------------------------------------------------------------------------

def test_two_frames_per_second_in_time_order(tmp_path):
    clip = write_clip(tmp_path / "a.mp4", frames=45, fps=15)                # 3 seconds
    times = [t for t, _ in det.sampled_frames(clip, fps=2)]
    assert 5 <= len(times) <= 7
    assert all(b - a >= 0.45 for a, b in zip(times, times[1:]))


def test_cut_faces_drops_stray_and_unsure_faces(tmp_path):
    x, y, side, gray = STEADY
    def face(n):
        if n == 15:
            return (10, 10, 30, gray)               # one stray "face" far from the speaker
        if n == 30:
            return (x, y, side, 100)                # one the finder is unsure of (confidence about 0.4)
        return STEADY
    clip = write_clip(tmp_path / "b.mp4", frames=45, fps=15, face=face)
    faces, frames = det.cut_faces(clip, square_finder, fps=15 / 5)   # every 5th frame: 0, 5, ..., 40
    assert frames == 9
    kept = {round(f.t * 15) for f in faces}
    assert 15 not in kept and 30 not in kept and len(faces) == 7
    assert all(f.image.shape == (256, 256, 3) for f in faces)


# --- percentiles and cut-offs ------------------------------------------------------------------------

def test_percentile_counts_ties_half():
    ref = reference(n=4)                                    # 0, 0.33, 0.66, 0.99
    assert ref.percentile("run3", [0.5])[0] == pytest.approx(0.5)
    assert ref.percentile("run3", [0.33])[0] == pytest.approx(0.375)
    assert ref.percentile("run3", [2.0])[0] == 1.0
    assert ref.combine({"run3": [0.5], "run5": [2.0], "gend": [-1]})[0] == pytest.approx(0.5)


def test_reference_builder_sets_cutoffs_at_5_and_1_percent():
    import make_detector_reference as mdr
    rng = np.random.default_rng(0)
    reals = pd.DataFrame({m: rng.random(400) for m in mdr.MODELS})
    ref = mdr.reference_from(reals)
    lists = {m: np.array(ref["scores"][m]) for m in mdr.MODELS}
    combined = np.mean([mdr.percentile(lists[m], reals[m]) for m in mdr.MODELS], axis=0)
    assert (combined >= ref["cutoffs"]["moderate"]).mean() == pytest.approx(0.05, abs=0.01)
    assert (combined >= ref["cutoffs"]["strong"]).mean() == pytest.approx(0.01, abs=0.01)


# --- one recording, end to end ---------------------------------------------------------------------

def test_fake_looking_recording_is_strong_with_its_worst_moments(tmp_path):
    clip = write_clip(tmp_path / "c.mp4", frames=90, fps=15)                # 6 seconds, 12 or 13 faces
    model = FakeDetector({"run3": 0.995, "run5": 0.995, "gend": 0.995}, spikes={1.0, 3.0, 4.0})
    result = det.assess(clip, None, model, reference(), fps=2)
    assert result.strength == "strong" and result.combined > 0.99
    assert result.top_times == [1.0, 3.0, 4.0]
    assert set(result.video) == {"run3", "run5", "gend"}


def test_real_looking_recording_is_info_and_window_is_split(tmp_path):
    clip = write_clip(tmp_path / "d.mp4", frames=90, fps=15)
    model = FakeDetector({"run3": 0.2, "run5": 0.3, "gend": 0.25}, spikes={2.0, 2.5})
    result = det.assess(clip, {"start_s": 2.0, "end_s": 3.0}, model, reference(), fps=2)
    assert result.strength == "info" and result.combined < 0.4
    assert result.window["faces_inside"] == 3
    assert result.window["combined_inside"] > result.window["combined_outside"]


def test_too_few_faces_is_inconclusive(tmp_path):
    clip = write_clip(tmp_path / "e.mp4", frames=45, fps=15, face=lambda n: STEADY if n < 10 else None)
    result = det.assess(clip, None, FakeDetector({"run3": 0.9, "run5": 0.9, "gend": 0.9}), reference(), fps=2)
    assert result.combined is None and result.faces < det.MIN_FACES
    signal = video.detector_signal(result, reference())
    assert signal.code == "deepfake_inconclusive" and signal.strength == "info"


# --- what the analysts see -------------------------------------------------------------------------

def make_case(tmp_path, window=None):
    write_clip(tmp_path / "interview.webm.mp4", frames=90, fps=15)
    (tmp_path / "interview.mp4").write_bytes((tmp_path / "interview.webm.mp4").read_bytes())
    return {"interview": {"recording": "interview.mp4", "liveness_step": window}}


def test_analyze_emits_deepfake_score_from_the_loaded_detector(tmp_path, monkeypatch):
    case = make_case(tmp_path, window={"start_s": 1, "end_s": 2})
    monkeypatch.setattr(det, "missing_files", lambda: [])
    monkeypatch.setattr(video, "_loaded", (FakeDetector({"run3": 0.97, "run5": 0.96, "gend": 0.97}), reference()))
    signals = video.analyze(tmp_path, case)
    score = [s for s in signals if s.code == "deepfake_score"]
    assert len(score) == 1 and score[0].strength == "moderate"
    assert score[0].text.startswith(f"Face-swap check (Run 3, {det.SHOWN['run5']}, GenD): combined score")
    assert set(score[0].data["models"]) == {"Run 3", det.SHOWN["run5"], "GenD"} and "liveness_window" in score[0].data
    json.dumps(score[0].to_dict())                          # evidence.json must be able to hold it


def test_run5z_holds_run5s_slot_by_default_with_its_own_reference():
    # Oct 24 (DECISIONS): Run 5z replaced Run 5 in the detector and the live check, with Run 5z's own reference file,
    # because its raw scores are on another scale. CHIMERA_RUN5_ADAPTER still puts any adapter in the slot.
    assert det.RUN5_DEFAULT == "qwen3vl-deepfake-v5z" and det.run5_label(det.RUN5_DEFAULT) == "Run 5z"
    if "CHIMERA_RUN5_ADAPTER" not in os.environ:
        assert det.MODELS["run5"].name == "qwen3vl-deepfake-v5z" and det.SHOWN["run5"] == "Run 5z"
    if "CHIMERA_DETECTOR_REFERENCE" not in os.environ:
        assert det.REFERENCE.name == "detector_reference_v5z.json"
    assert det.run5_label(Path("models") / "qwen3vl-deepfake-v5") == "Run 5"
    assert det.run5_label("models/qwen3vl-deepfake-v5z-s2") == "Run 5z-s2"
    assert det.run5_label("elsewhere/my-adapter") == "Run 5 slot (my-adapter)"
    assert any(m.startswith(f"{det.SHOWN['run5']} adapter") for m in det.missing_files()) or \
        (det.MODELS["run5"] / "adapter_model.safetensors").is_file()


def test_analyze_reports_missing_files_instead_of_scoring(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setattr(det, "missing_files", lambda: ["Run 5 adapter (models/qwen3vl-deepfake-v5/x)"])
    signals = video.analyze(tmp_path, case)
    codes = {s.code for s in signals}
    assert "detector_not_configured" in codes and "liveness_inconclusive" not in codes   # camera on is the only rule
    assert "Run 5 adapter" in [s for s in signals if s.code == "detector_not_configured"][0].text


def test_detector_can_be_switched_off(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setenv("CHIMERA_DETECTOR", "off")
    assert "detector_not_configured" in {s.code for s in video.analyze(tmp_path, case)}
