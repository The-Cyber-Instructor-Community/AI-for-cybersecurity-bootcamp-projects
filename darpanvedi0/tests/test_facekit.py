"""scripts/facekit.py: the face cutting and the video-level maths that compress_test.py and score_external.py share."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from video_helpers import STEADY, square_finder, write_clip

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import facekit  # noqa: E402

SLOT_FRAMES = {0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 31}   # 16 spread over a 32-frame clip


# --- Writing only inside data/ ---------------------------------------------------------------

def test_inside_data_allows_files_under_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert facekit.inside_data("data/scores/x.csv") == Path("data/scores/x.csv")


@pytest.mark.parametrize("bad", ["../x.csv", "data/../x.csv", "data2/x.csv", "x.csv", "ELSEWHERE"])
def test_inside_data_refuses_everything_else(tmp_path, monkeypatch, bad):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    if bad == "ELSEWHERE":
        bad = str(tmp_path.parent / "elsewhere.csv")
    with pytest.raises(ValueError, match="outside data"):
        facekit.inside_data(bad)


# --- Cutting faces ---------------------------------------------------------------------------

def test_cut_gives_a_256_square_centered_on_the_face():
    frame = np.zeros((300, 400, 3), np.uint8)
    frame[100:160, 200:260] = (0, 0, 255)                    # a red 60 x 60 "face" centered at (230, 130)
    out = facekit.cut(frame, 230, 130, 60)
    assert out.shape == (256, 256, 3)
    assert tuple(out[128, 128]) == (0, 0, 255)               # the face is in the middle
    assert tuple(out[5, 5]) == (0, 0, 0)                     # and the box is 30% bigger, so the edge is background


def test_crop_video_keeps_the_requested_number_of_crops_in_frame_order(tmp_path):
    clip = write_clip(tmp_path / "a.avi")
    crops = facekit.crop_video(clip, square_finder, slots=16, keep=8)
    frames = [c.frame_no for c in crops]
    assert len(crops) == 8
    assert frames == sorted(frames)
    assert set(frames) <= SLOT_FRAMES
    assert all(c.image.shape == (256, 256, 3) for c in crops)


def test_crop_video_picks_the_same_frames_every_time(tmp_path):
    clip = write_clip(tmp_path / "a.avi")
    first = [c.frame_no for c in facekit.crop_video(clip, square_finder, key="Celeb-real/id0_0000.mp4")]
    again = [c.frame_no for c in facekit.crop_video(clip, square_finder, key="Celeb-real/id0_0000.mp4")]
    assert first == again


def test_losing_one_face_swaps_in_another_frame_without_reshuffling_the_rest(tmp_path):
    # This is what keeps the 500k, 250k and 128k copies of a video scored on (nearly) the same frames.
    full = write_clip(tmp_path / "full.avi")
    picked = [c.frame_no for c in facekit.crop_video(full, square_finder, key="v")]
    gone = picked[0]
    holey = write_clip(tmp_path / "holey.avi", face=lambda n: None if n == gone else STEADY)
    after = [c.frame_no for c in facekit.crop_video(holey, square_finder, key="v")]
    assert gone not in after
    assert len(after) == 8
    assert set(picked) - {gone} <= set(after)


def test_a_face_far_from_the_usual_place_is_not_cut(tmp_path):
    jumped = lambda n: (10, 100, 60, 250) if n in (8, 20) else STEADY      # frames 8 and 20: a face on the far left
    clip = write_clip(tmp_path / "a.avi", face=jumped)
    frames = [c.frame_no for c in facekit.crop_video(clip, square_finder, slots=16, keep=16)]
    assert 8 not in frames and 20 not in frames
    assert len(frames) == 14


def test_faces_the_finder_is_unsure_about_are_skipped_only_when_asked(tmp_path):
    dim = lambda n: (110, 50, 60, 120) if n in (4, 12) else STEADY         # a dim square reads as low confidence
    clip = write_clip(tmp_path / "a.avi", face=dim)
    everything = [c.frame_no for c in facekit.crop_video(clip, square_finder, slots=16, keep=16)]
    sure_only = [c.frame_no for c in facekit.crop_video(clip, square_finder, slots=16, keep=16, min_confidence=0.6)]
    assert 4 in everything and 12 in everything
    assert 4 not in sure_only and 12 not in sure_only
    assert len(sure_only) == 14


def test_a_clip_without_a_face_gives_no_crops(tmp_path):
    clip = write_clip(tmp_path / "empty.avi", face=lambda n: None)
    assert facekit.crop_video(clip, square_finder) == []


def test_a_file_that_cannot_be_read_gives_no_crops(tmp_path):
    assert facekit.crop_video(tmp_path / "missing.mp4", square_finder) == []


# --- Video scores, AUC, and the cut-off ------------------------------------------------------

def pictures(rows):
    return pd.DataFrame([{"video": video, "label": label, "p_fake": p} for video, label, scores in rows for p in scores])


# Video means: f1 .5, f2 .75, f3 .1875 (fakes) and r1 .25, r2 .75, r3 .0625, r4 .375 (real). All exact in binary.
ROWS = [("f1", 1, [.75, .25]), ("f2", 1, [.875, .625]), ("f3", 1, [.25, .125]),
        ("r1", 0, [.25, .25]), ("r2", 0, [.75, .75]), ("r3", 0, [0, .125]), ("r4", 0, [.375, .375])]


def test_video_score_is_the_mean_of_its_pictures():
    videos = facekit.video_scores(pictures(ROWS))
    assert videos.loc["f1", "p_fake"] == .5
    assert videos.loc["r3", "p_fake"] == .0625
    assert videos.loc["f1", "label"] == 1 and videos.loc["r1", "label"] == 0


def test_video_scores_keep_set_and_official_columns_when_present():
    table = pictures(ROWS[:2]).assign(set="test", official_test=True)
    videos = facekit.video_scores(table)
    assert videos.loc["f2", "set"] == "test" and bool(videos.loc["f2", "official_test"])


def test_auc_counts_ties_as_half():
    # 12 fake-real pairs: f1 wins 3 and f2 wins 3 and ties 1 (r2), f3 wins 1. 7.5 of 12.
    assert facekit.auc(facekit.video_scores(pictures(ROWS))) == pytest.approx(7.5 / 12)


def test_a_video_exactly_at_the_cutoff_counts_as_flagged():
    videos = facekit.video_scores(pictures(ROWS))
    recall, false_alarms = facekit.flag_rates(videos, 0.5)
    assert recall == pytest.approx(2 / 3)       # f1 (exactly .5) and f2 flagged, f3 missed
    assert false_alarms == pytest.approx(1 / 4)  # only r2 flagged


def test_one_class_only_gives_nan_instead_of_crashing():
    videos = facekit.video_scores(pictures(ROWS[:3]))                    # fakes only
    assert np.isnan(facekit.auc(videos))
    recall, false_alarms = facekit.flag_rates(videos, 0.5)
    assert recall == pytest.approx(2 / 3) and np.isnan(false_alarms)
