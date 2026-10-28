"""The most suspicious moments saved as pictures (chimera/evidence_frames.py), and the recording check that keeps them.
Pictures here are flat grey test arrays and the bright-square clips of video_helpers.py, never faces."""
import json
import sys
from pathlib import Path

import numpy as np
from video_helpers import write_clip

from chimera import detector as det
from chimera import evidence_frames as ef
from chimera import video

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_detector import FakeDetector, reference  # noqa: E402

FACE = np.full((256, 256, 3), 128, np.uint8)
FRAME = np.full((180, 320, 3), 64, np.uint8)


def offer_all(top, scored):
    return [top.offer(t, s, FACE, FRAME, (100, 80, 60)) for t, s in scored]


def test_keeps_the_five_highest_at_least_two_seconds_apart():
    top = ef.TopFrames()
    offer_all(top, [(0, 0.1), (1, 0.9), (1.5, 0.95), (4, 0.5), (8, 0.7), (12, 0.2), (16, 0.6), (20, 0.65)])
    kept = [(m.t, m.score) for m in top.ranked()]
    # 1.5 s is chosen first; 1.0 s and 0 s are under two seconds from it
    assert kept == [(1.5, 0.95), (8, 0.7), (20, 0.65), (16, 0.6), (4, 0.5)]
    assert all(abs(a.t - b.t) >= 2 for a in top.moments for b in top.moments if a is not b)


def test_a_rising_run_does_not_push_out_a_moment_that_qualifies():
    # Oct 26 review: kept one moment per stretch in time order, 13 s replaced 11.5 s, which had replaced 10 s, so
    # 10 s (3 s from 13 s, and 0.90) was lost to a 0.5 face at 50 s.
    top = ef.TopFrames()
    offer_all(top, [(10, 0.90), (11.5, 0.95), (13, 0.99), (20, 0.5), (30, 0.5), (40, 0.5), (50, 0.5)])
    assert [m.t for m in top.ranked()] == [13, 10, 20, 30, 40]


def test_the_pool_chooses_as_if_it_had_every_face():
    scored = [(i * 0.5, ((i * 37) % 101) / 100) for i in range(400)]          # 200 s at two checks a second
    top = ef.TopFrames(pool=50)
    offer_all(top, scored)
    every = ef.choose([ef.Moment(t, s) for t, s in scored])
    assert [(m.t, m.score) for m in top.ranked()] == [(m.t, m.score) for m in every]
    assert len(top.candidates) <= 50


def test_a_lower_face_never_displaces_a_kept_one_and_ties_use_the_raw_score():
    top = ef.TopFrames(keep=2)
    assert top.offer(0, 1.0, FACE, tie=0.98) and top.offer(5, 1.0, FACE, tie=0.95)
    assert not top.offer(10, 0.99, FACE)                       # lower than both kept
    assert top.offer(10, 1.0, FACE, tie=0.99)                  # same percentile, higher raw score: replaces 5 s
    assert [m.t for m in top.ranked()] == [10, 0]
    assert not top.offer(10.5, 1.0, FACE, tie=0.5)             # the same moment as 10 s, less suspicious


def test_autosave_writes_pictures_and_manifest_and_removes_dropped_ones(tmp_path):
    folder = tmp_path / "live_frames"
    top = ef.TopFrames(folder, keep=2, meta={"kind": "live", "cutoff": 0.46}, autosave=True)
    offer_all(top, [(1, 0.5), (5, 0.6)])
    assert sorted(p.name for p in folder.iterdir()) == ["m000010_face.png", "m000010_frame.jpg",
                                                        "m000050_face.png", "m000050_frame.jpg", "manifest.json"]
    offer_all(top, [(9, 0.9)])                                 # pushes out 1 s
    names = sorted(p.name for p in folder.iterdir())
    assert "m000010_face.png" not in names and "m000090_frame.jpg" in names
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["kind"] == "live" and manifest["cutoff"] == 0.46
    assert [(m["rank"], m["t"], m["clock"], m["face"]) for m in manifest["moments"]] == [
        (1, 9.0, "0:09", "m000090_face.png"), (2, 5.0, "0:05", "m000050_face.png")]
    assert manifest["moments"][0]["box"] == [100.0, 80.0, 60.0]


def test_offered_pictures_are_encoded_at_once(tmp_path):
    import cv2
    frame = FRAME.copy()
    top = ef.TopFrames()
    top.offer(1, 0.5, FACE, frame)
    frame[:] = 255                                             # the live check draws on its frame afterwards
    stored = cv2.imdecode(np.frombuffer(top.moments[0].frame, np.uint8), cv2.IMREAD_COLOR)
    assert stored.shape == (180, 320, 3) and stored.max() < 100


def test_a_picture_another_program_has_open_does_not_stop_the_live_check(tmp_path, monkeypatch):
    # Oct 26 review: on Windows a picture the Console is serving cannot be deleted; save() raised and the live
    # check died mid-call. Now the file is left, unlisted, and removed at a later save.
    folder = tmp_path / "live"
    top = ef.TopFrames(folder, keep=1, autosave=True)
    offer_all(top, [(1, 0.5)])
    real_unlink = Path.unlink

    def locked(self, missing_ok=False):
        if self.name.startswith("m000010"):
            raise PermissionError(32, "The process cannot access the file")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    assert offer_all(top, [(9, 0.9)]) == [True]                # 1 s is dropped but its file is locked
    assert [m["t"] for m in json.loads((folder / "manifest.json").read_text())["moments"]] == [9.0]
    monkeypatch.setattr(Path, "unlink", real_unlink)
    offer_all(top, [(20, 0.95)])
    assert not (folder / "m000010_face.png").exists()          # gone at the next save


def test_clear_removes_only_its_own_files_and_copy_replaces(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    top = ef.TopFrames(src, keep=3, meta={"kind": "live"}, autosave=True)
    offer_all(top, [(1, 0.5), (5, 0.6)])
    dst.mkdir()
    (dst / "m000990_face.png").write_bytes(b"old")
    copied = ef.copy(src, dst, {"attached_to": "case_001"})
    assert copied["attached_to"] == "case_001" and len(copied["moments"]) == 2
    assert not (dst / "m000990_face.png").exists() and all((dst / m["frame"]).is_file() for m in copied["moments"])
    (src / "notes.txt").write_text("someone else's file")
    ef.clear(src)
    assert [p.name for p in src.iterdir()] == ["notes.txt"]
    ef.clear(dst)
    assert not dst.exists()
    assert ef.read_manifest(dst) is None and ef.copy(dst, tmp_path / "x") is None


def test_attaching_is_all_or_nothing(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    top = ef.TopFrames(src, keep=3, autosave=True)
    offer_all(top, [(1, 0.5), (5, 0.6)])
    assert ef.copy(src, dst, {"attached_to": "case_001"})["moments"]
    # The live check dropped 5 s while we copied: its picture is listed but gone. Only 1 s comes through.
    (src / "m000050_frame.jpg").unlink()
    again = ef.copy(src, dst)
    assert [m["t"] for m in again["moments"]] == [1.0]
    assert sorted(p.name for p in dst.iterdir()) == sorted([again["moments"][0]["face"], again["moments"][0]["frame"],
                                                            "manifest.json"])
    # Nothing comes through at all: the case keeps what it had.
    for p in src.glob("m*_*"):                                  # the pictures; the manifest still lists them
        p.unlink()
    assert ef.read_manifest(src) and ef.copy(src, dst) is None
    kept = ef.read_manifest(dst)["moments"]
    assert [m["t"] for m in kept] == [1.0] and (dst / kept[0]["frame"]).is_file()


def test_attaching_again_never_overwrites_a_picture_that_is_open(tmp_path, monkeypatch):
    # Second Oct 26 review: re-attaching the same session wrote the same names; Windows refuses to replace a picture
    # the Console is serving, and the case was left with none. Each copy now has names of its own, the manifest
    # changes in one step, and an old picture that cannot be removed stays, unlisted.
    src, dst = tmp_path / "src", tmp_path / "dst"
    top = ef.TopFrames(src, keep=3, autosave=True)
    offer_all(top, [(3, 0.5), (8, 0.6)])
    first = ef.copy(src, dst)
    open_name = first["moments"][0]["face"]
    real_unlink = Path.unlink

    def locked(self, missing_ok=False):
        if self.name == open_name:
            raise PermissionError(32, "The process cannot access the file")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    second = ef.copy(src, dst)
    names = {n for m in second["moments"] for n in (m["face"], m["frame"])}
    assert open_name not in names and all((dst / n).is_file() for n in names)
    assert ef.read_manifest(dst) == second and (dst / open_name).is_file()     # left, unlisted
    assert all(ef.PICTURE.match(n) for n in names)


def test_recording_check_saves_its_most_suspicious_moments(tmp_path):
    clip = write_clip(tmp_path / "c.mp4", frames=300, fps=15)                # 20 seconds at 2 checks a second
    # Whole seconds land exactly on a sampled frame at 15 fps. Six moments spike; 1 s and 2 s are one moment.
    model = FakeDetector({"run3": 0.9, "run5": 0.9, "gend": 0.9}, spikes={1.0, 2.0, 5.0, 8.0, 11.0, 14.0, 17.0})
    folder = tmp_path / "evidence_frames"
    result = det.assess(clip, None, model, reference(), fps=2, frames_dir=folder)
    times = [m["t"] for m in result.evidence_frames["moments"]]
    assert len(times) == 5 and set(times) <= {1.0, 2.0, 5.0, 8.0, 11.0, 14.0, 17.0}
    assert not {1.0, 2.0} <= set(times)                        # one second apart: one moment
    for m in result.evidence_frames["moments"]:
        assert (folder / m["face"]).is_file() and (folder / m["frame"]).is_file()
        assert set(m["models"]) == {"Run 3", det.SHOWN["run5"], "GenD"}
    assert result.evidence_frames["kind"] == "recording" and result.evidence_frames["source"] == "c.mp4"
    import cv2
    assert cv2.imread(str(folder / result.evidence_frames["moments"][0]["frame"])).shape == (180, 320, 3)


def test_analyze_points_to_the_pictures_and_clears_old_ones(tmp_path, monkeypatch):
    write_clip(tmp_path / "interview.mp4", frames=90, fps=15)
    case = {"interview": {"recording": "interview.mp4"}}
    monkeypatch.setattr(det, "missing_files", lambda: [])
    monkeypatch.setattr(video, "_loaded", (FakeDetector({"run3": 0.97, "run5": 0.96, "gend": 0.97}, spikes={2.0}),
                                           reference()))
    folder = tmp_path / "out" / video.EVIDENCE_FRAMES
    signal = next(s for s in video.analyze(tmp_path, case, folder) if s.code == "deepfake_score")
    pointer = signal.data["evidence_frames"]
    assert pointer["folder"] == "evidence_frames" and pointer["count"] == len(pointer["times_s"]) >= 1
    assert pointer["times_s"][0] == 2.0
    assert "evidence_frames" not in signal.text                 # the analysts' line is unchanged
    json.dumps(signal.to_dict())
    # The recording goes away: the next run leaves no pictures from the old one.
    (tmp_path / "interview.mp4").unlink()
    signals = video.analyze(tmp_path, case, folder)
    assert [s.code for s in signals] == ["no_recording"] and not folder.exists()
