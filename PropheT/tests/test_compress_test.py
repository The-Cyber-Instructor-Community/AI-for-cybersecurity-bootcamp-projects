"""scripts/compress_test.py: re-encode the test videos at low bitrates and see how the model's scores hold up."""
import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from video_helpers import FakeJudge, square_finder, write_clip

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import compress_test  # noqa: E402

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
                                  reason="ffmpeg is not installed")
SCORE_COLUMNS = ["picture", "video", "label", "set", "official_test", "frame", "size", "confidence", "p_fake"]


def after(command, flag):
    """The word that follows `flag` in an ffmpeg command."""
    return command[command.index(flag) + 1]


def probe(path):
    """(width, height, frames per second, number of audio streams, bitrate in kbit/s) of a video file."""
    def ffprobe(*args):
        return subprocess.run(["ffprobe", "-v", "error", *args, "-of", "csv=p=0", str(path)],
                              capture_output=True, text=True, check=True).stdout.split()
    width, height, rate = ffprobe("-select_streams", "v:0", "-show_entries", "stream=width,height,r_frame_rate")[0].split(",")
    audio = ffprobe("-select_streams", "a", "-show_entries", "stream=index")
    kbps = int(ffprobe("-show_entries", "format=bit_rate")[0]) / 1000
    numerator, denominator = rate.split("/")
    return int(width), int(height), int(numerator) / int(denominator), len(audio), kbps


@pytest.fixture(scope="module")
def source_video(tmp_path_factory):
    """A 4-second test pattern about the size and speed of a Celeb-DF clip."""
    path = tmp_path_factory.mktemp("source") / "source.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc2=size=900x500:rate=30:duration=4", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True)
    return path


# --- Choosing the encoder --------------------------------------------------------------------

def test_the_gpu_encoder_is_used_only_if_a_test_encode_with_it_works(monkeypatch):
    seen = []

    def fake_run(command, **kwargs):
        seen.append(command)
        return subprocess.CompletedProcess(command, returncode=0 if fake_run.works else 1)

    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_run.works = True
    assert compress_test.pick_encoder() == "h264_nvenc"
    assert "h264_nvenc" in seen[0]                      # it really tried an encode with the GPU encoder
    fake_run.works = False
    assert compress_test.pick_encoder() == "libx264"


def test_a_missing_ffmpeg_stops_the_script_with_a_clear_message(monkeypatch):
    def no_ffmpeg(command, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(subprocess, "run", no_ffmpeg)
    with pytest.raises(SystemExit, match="ffmpeg"):
        compress_test.pick_encoder()


# --- The ffmpeg command ----------------------------------------------------------------------

@pytest.mark.parametrize("encoder", ["h264_nvenc", "libx264"])
@pytest.mark.parametrize("name, kbps", [("500k", 500), ("250k", 250), ("128k", 128)])
def test_the_command_fixes_the_bitrate_and_uses_no_quality_setting(name, kbps, encoder):
    # A quality setting (crf, cq, qp, preset) would make the bitrate whatever the picture needs.
    command = compress_test.ffmpeg_command("in.mp4", "out.mp4", compress_test.PROFILES[name], encoder)
    assert after(command, "-b:v") == f"{kbps}k"
    assert after(command, "-maxrate") == f"{kbps}k"
    assert after(command, "-c:v") == encoder
    assert "-an" in command                              # no audio
    assert not {"-crf", "-cq", "-qp", "-preset"} & set(command)


# --- Re-encoding real files ------------------------------------------------------------------

@needs_ffmpeg
@pytest.mark.parametrize("name, kbps, width, height", [("500k", 500, 640, 360), ("250k", 250, 640, 360),
                                                       ("128k", 128, 480, 270)])
def test_a_copy_has_the_planned_size_speed_and_bitrate_and_no_sound(name, kbps, width, height, source_video, tmp_path,
                                                                    monkeypatch):
    monkeypatch.chdir(tmp_path)
    copy = Path("data/compressed") / name / "clip.mp4"
    assert compress_test.reencode(source_video, copy, compress_test.PROFILES[name], "libx264") is True
    got_width, got_height, fps, audio_streams, got_kbps = probe(copy)
    assert (got_width, got_height, fps, audio_streams) == (width, height, 15, 0)
    assert 0.75 * kbps < got_kbps < 1.25 * kbps


@needs_ffmpeg
def test_a_copy_that_already_exists_is_left_alone(source_video, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    copy = Path("data/compressed/500k/clip.mp4")
    compress_test.reencode(source_video, copy, compress_test.PROFILES["500k"], "libx264")
    before = copy.stat().st_mtime_ns
    assert compress_test.reencode(source_video, copy, compress_test.PROFILES["500k"], "libx264") is False
    assert copy.stat().st_mtime_ns == before


@needs_ffmpeg
def test_a_failed_encode_names_the_video_and_leaves_no_half_written_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    broken = tmp_path / "broken.mp4"
    broken.write_bytes(b"this is not a video")
    copy = Path("data/compressed/500k/broken.mp4")
    with pytest.raises(RuntimeError, match="broken.mp4"):
        compress_test.reencode(broken, copy, compress_test.PROFILES["500k"], "libx264")
    assert list(Path("data/compressed/500k").glob("*")) == []


def test_reencode_refuses_to_write_outside_data(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="outside data"):
        compress_test.reencode("in.mp4", tmp_path / "elsewhere.mp4", compress_test.PROFILES["500k"], "libx264")


# --- Numbers for the table -------------------------------------------------------------------

def test_the_table_numbers_come_from_the_right_videos(tmp_path):
    # Video scores (mean of 2 pictures): held-out people = set "test"; official list = official_test True.
    #   test/official  t_f1 fake .8   t_r1 real .2          test/not official  t_f2 fake .3   t_r2 real .6
    #   official_only  o_f1 fake .9   o_r1 real .95
    rows = [("t_f1", 1, "test", True, [.9, .7]), ("t_f2", 1, "test", False, [.4, .2]),
            ("t_r1", 0, "test", True, [.2, .2]), ("t_r2", 0, "test", False, [.7, .5]),
            ("o_f1", 1, "official_only", True, [.95, .85]), ("o_r1", 0, "official_only", True, [.95, .95])]
    path = tmp_path / "scores.csv"
    pd.DataFrame([{"picture": f"{v}_{i}.png", "video": v, "label": label, "set": s, "official_test": official,
                   "frame": i, "size": 100, "confidence": .9, "p_fake": p}
                  for v, label, s, official, scores in rows for i, p in enumerate(scores)]).to_csv(path, index=False)
    got = compress_test.profile_metrics(path, 0.601)
    # Held-out: fakes .8 and .3, reals .2 and .6. Fakes win 3 of 4 pairs. Only .8 is at or above .601.
    assert got["auc_held_out"] == pytest.approx(0.75)
    assert got["recall"] == pytest.approx(0.5)
    assert got["fpr"] == pytest.approx(0.0)
    # Official list = t_f1, t_r1, o_f1, o_r1: fakes .8 and .9 against reals .2 and .95. The fakes win 2 of 4 pairs.
    # (Only the official_only videos would give 0, and only the test set 0.75, so this checks the right ones are used.)
    assert got["auc_official"] == pytest.approx(0.5)
    assert got["videos"] == 6


# --- The whole script, with a stand-in face finder and model ---------------------------------

VIDEOS = [  # video, label, set, official_test
    ("Celeb-real/id0_0000.mp4", 0, "test", True), ("Celeb-real/id0_0001.mp4", 0, "test", False),
    ("Celeb-synthesis/id0_id1_0000.mp4", 1, "test", True), ("Celeb-synthesis/id0_id1_0001.mp4", 1, "test", False),
    ("Celeb-real/id5_0000.mp4", 0, "official_only", True), ("Celeb-synthesis/id5_id6_0000.mp4", 1, "official_only", True),
    ("Celeb-real/id9_0000.mp4", 0, "train", False),            # not part of this test
]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A tiny stand-in for the chimera folder: a video table, and the clips in a Celeb-DF-v2 folder next to it."""
    work = tmp_path / "chimera"
    (work / "data").mkdir(parents=True)
    root = tmp_path / "Celeb-DF-v2"
    with (work / "data/celebdf_videos.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["video", "label", "people", "set", "official_test"])
        for video, label, which, official in VIDEOS:
            writer.writerow([video, label, "", which, official])
            (root / video).parent.mkdir(parents=True, exist_ok=True)
            write_clip(root / video)
    monkeypatch.chdir(work)
    return work, root


def run_script(root, *args, judges=None):
    """Run the whole script with the stand-in finder and model; returns the stand-in models it made."""
    judges = [] if judges is None else judges

    def make_judge():
        judges.append(FakeJudge())
        return judges[-1]

    compress_test.main(["--encoder", "libx264", "--root", str(root), *args], find_face=square_finder,
                       make_judge=make_judge)
    return judges


def files_under(folder):
    return {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}


@needs_ffmpeg
def test_the_script_scores_every_profile_and_prints_one_table(project, capsys):
    work, root = project
    judges = run_script(root)
    shown = capsys.readouterr().out
    assert len(judges) == 1                                           # the model was loaded once, for all four

    for name in ["orig", "500k", "250k", "128k"]:
        scores = pd.read_csv(work / f"data/scores/compress_{name}.csv")
        assert scores.columns.tolist() == SCORE_COLUMNS               # score_model.py's picture-level format
        assert scores["video"].nunique() == 6                         # the train video is left out
        assert len(scores) == 6 * 8                                   # 8 pictures per video
        assert Path(scores["picture"].iloc[0]).exists()
        row = next(line for line in shown.splitlines() if line.split()[:1] == [name])
        assert row.split() == [name, "1.000", "1.000", "100%", "0%"]  # the stand-in model is always right
    assert (work / "data/compressed/500k/Celeb-real/id0_0000.mp4").exists()
    assert not (work / "data/compressed/orig/Celeb-real").exists()    # "orig" is read from the dataset, not copied
    assert "0.601" in shown


@needs_ffmpeg
def test_profiles_with_a_score_file_are_skipped_and_the_rest_are_done(project, capsys):
    work, root = project
    run_script(root)
    done = work / "data/scores/compress_500k.csv"
    before = done.stat().st_mtime_ns
    (work / "data/scores/compress_250k.csv").unlink()

    judges = run_script(root)
    assert len(judges) == 1 and judges[0].scored == 6 * 8             # only the 250k pictures were scored
    assert done.stat().st_mtime_ns == before
    assert (work / "data/scores/compress_250k.csv").exists()

    capsys.readouterr()
    judges = run_script(root)                                         # nothing left to do: no model, no ffmpeg
    assert judges == []
    rows = [line.split()[0] for line in capsys.readouterr().out.splitlines() if line.split()]
    assert {"orig", "500k", "250k", "128k"} <= set(rows)              # and the table still shows every profile


@needs_ffmpeg
def test_a_limited_run_cannot_make_a_later_full_run_skip_a_profile(project):
    work, root = project
    run_script(root, "--limit", "3", "orig")
    assert (work / "data/scores/compress_orig_first3.csv").exists()
    assert not (work / "data/scores/compress_orig.csv").exists()
    assert pd.read_csv(work / "data/scores/compress_orig_first3.csv")["video"].nunique() == 3


@needs_ffmpeg
def test_nothing_is_written_outside_data(project):
    work, root = project
    before = files_under(work.parent)
    run_script(root)
    new = files_under(work.parent) - before
    assert new and all(name.startswith("chimera/data/") for name in new)


@needs_ffmpeg
def test_the_script_uses_the_v3_adapter_unless_told_otherwise(project):
    work, root = project
    assert run_script(root, "orig")[0].adapter == "models/qwen3vl-deepfake-v3"
    (work / "data/scores/compress_orig.csv").unlink()
    assert run_script(root, "orig", "--adapter", "models/other")[0].adapter == "models/other"
