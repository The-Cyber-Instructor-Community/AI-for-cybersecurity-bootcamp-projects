"""Run 5z's data: the meeting-like encode settings, which targets are re-encoded, and the picture swap."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ffpp_meeting_faces as mf  # noqa: E402
import make_training_files_v5z as v5z  # noqa: E402


def test_encode_settings_keep_the_zoom_like_bits_per_pixel_and_never_scale_up():
    assert mf.encode_settings(1280, 720) == (1280, 720, 1200)
    assert mf.encode_settings(1920, 1080) == (1280, 720, 1200)
    w, h, kbps = mf.encode_settings(854, 480)
    assert (w, h) == (854, 480) and 530 <= kbps <= 540
    assert mf.encode_settings(320, 240)[2] == mf.MIN_KBPS


def test_half_the_training_targets_and_every_test_target():
    rows = [{"target": f"{i:03d}", "set": "train"} for i in range(20)] + \
           [{"target": f"{i:03d}", "set": "test"} for i in range(100, 105)] + \
           [{"target": f"{i:03d}", "set": "val"} for i in range(200, 204)]
    videos = pd.DataFrame(rows)
    chosen = mf.chosen_targets(videos)
    assert len([t for t in chosen if int(t) < 20]) == 10
    assert {f"{i:03d}" for i in range(100, 105)} <= chosen and not any(int(t) >= 200 for t in chosen)
    assert chosen == mf.chosen_targets(videos)                       # fixed by the seed


def test_swap_keeps_videos_labels_and_count_and_only_touches_encoded_targets():
    base = pd.DataFrame([
        {"picture": "o/a/0001.png", "video": "original/a.mp4", "label": 0, "set": "train", "method": "original",
         "target": "a", "source": "", "frame": 1, "size": 150, "confidence": 0.9, "clip": 0},
        {"picture": "o/a/0009.png", "video": "original/a.mp4", "label": 0, "set": "train", "method": "original",
         "target": "a", "source": "", "frame": 9, "size": 150, "confidence": 0.9, "clip": 0},
        {"picture": "d/a_b/0001.png", "video": "Deepfakes/a_b.mp4", "label": 1, "set": "train", "method": "Deepfakes",
         "target": "a", "source": "b", "frame": 1, "size": 150, "confidence": 0.9, "clip": 0},
        {"picture": "o/c/0001.png", "video": "original/c.mp4", "label": 0, "set": "train", "method": "original",
         "target": "c", "source": "", "frame": 1, "size": 150, "confidence": 0.9, "clip": 0},
    ])
    meet = pd.DataFrame([
        {"picture": "m/o/a/0001.png", "video": "original/a.mp4", "label": 0, "set": "train", "target": "a",
         "frame": 1, "size": 120, "confidence": 0.8, "clip": 0},
        {"picture": "m/o/a/0005.png", "video": "original/a.mp4", "label": 0, "set": "train", "target": "a",
         "frame": 5, "size": 120, "confidence": 0.8, "clip": 0},                 # stands in for frame 9 (face lost)
        {"picture": "m/d/a_b/0001.png", "video": "Deepfakes/a_b.mp4", "label": 1, "set": "train", "target": "a",
         "frame": 1, "size": 120, "confidence": 0.5, "clip": 0},                 # too unsure: original stays
    ])
    out = v5z.swap_in(base, meet)
    assert len(out) == 4 and list(out["label"]) == [0, 0, 1, 0]
    assert list(out["meeting"]) == [True, True, False, False]
    assert list(out["picture"]) == ["m/o/a/0001.png", "m/o/a/0005.png", "d/a_b/0001.png", "o/c/0001.png"]


def test_compare_meeting_reads_both_conditions_and_pairs_them(tmp_path, monkeypatch):
    import numpy as np
    import compare_meeting as cm
    rng = np.random.default_rng(0)
    rows = []
    for t in range(30):
        rows.append({"video": f"original/{t:03d}.mp4", "label": 0, "method": "original", "target": f"{t:03d}"})
        for m in cm.METHODS:
            rows.append({"video": f"{m}/{t:03d}_x.mp4", "label": 1, "method": m, "target": f"{t:03d}"})
    base = pd.DataFrame(rows)
    def write(name, prefix, shift):
        df = base.copy()
        df["p_fake"] = np.where(df["label"] == 1, 0.7 - shift, 0.3) + rng.normal(0, 0.15, len(df))
        df.to_csv(tmp_path / f"{prefix}_{name}.csv", index=False)
    write("a", "ffpp", 0.0); write("a", "ffpp_meet", 0.3)           # fragile: fakes fall after the encode
    write("b", "ffpp", 0.0); write("b", "ffpp_meet", 0.0)           # robust
    monkeypatch.setattr(cm, "SCORES", tmp_path)
    table = cm.main(["a", "b"])
    assert table.loc[("b", "meeting encode"), "AUC"] > table.loc[("a", "meeting encode"), "AUC"]
    d, lo, hi, ahead = cm.paired(cm.videos(tmp_path / "ffpp_meet_a.csv"), cm.videos(tmp_path / "ffpp_meet_b.csv"))
    assert d > 0 and lo <= d <= hi and ahead > 0.9
